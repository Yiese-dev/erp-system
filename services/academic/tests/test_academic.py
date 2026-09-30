import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from packages.campus_common.database import LOCAL_TZ, Database
from packages.campus_common.events import MAX_ATTEMPTS, deliver, relay_once
from packages.campus_common.testing import bearer, settings_for
from services.academic.app.domain.enrollment import creates_cycle
from services.academic.app.domain.grading import letter_for, weighted_score
from services.academic.app.domain.risk import RiskPolicy, attendance_rate, evaluate
from services.academic.app.main import create_app
from services.academic.app.models import Base, OutboxEvent, ProcessedEvent, Registration, Result
from services.academic.app.seed import seed
from services.academic.app.worker import handle_finance_event

P = "/api/v1/academic"


def test_cycle_detection():
    edges = {"c": {"b"}, "b": {"a"}}
    assert creates_cycle(edges, "a", "c")
    assert not creates_cycle(edges, "d", "c")


def test_risk_rule_is_documented_threshold():
    policy = RiskPolicy()
    assert attendance_rate(["excused", "excused"]) is None
    assert attendance_rate(["present", "late", "absent", "excused"]) == pytest.approx(2 / 3)
    low = evaluate(["present", "absent", "absent", "present"], [70, 80], policy)
    assert low["status"] == "at_risk" and low["reasons"][0]["code"] == "low_attendance"
    failing = evaluate(["present"] * 4, [72, 45, 41], policy)
    assert [reason["code"] for reason in failing["reasons"]] == ["consecutive_failures"]
    recovered = evaluate(["present"] * 4, [45, 41, 60], policy)
    assert recovered["status"] == "on_track"
    assert evaluate([], [], policy)["status"] == "unknown"


def test_grade_scale_and_weighting():
    assert [letter_for(value) for value in (95, 70, 65, 50, 49.99)] == ["A", "B", "C", "D", "F"]
    assert weighted_score({"a": 30, "b": 70}, {"a": 100, "b": 50}) == 65


@pytest.fixture
def api(tmp_path):
    settings = settings_for("academic", f"sqlite:///{tmp_path / 'academic.db'}")
    with TestClient(create_app(settings)) as client:
        client.settings = settings
        yield client


def headers(api, role, tenant="tn_a", user=None):
    return bearer(api.settings, role, tenant, user)


def build_catalogue(api, tenant="tn_a"):
    admin = headers(api, "admin", tenant)
    program = api.post(f"{P}/programs", json={"code": "BSE", "name": "Software Engineering"}, headers=admin).json()
    intro = api.post(f"{P}/courses", json={"program_id": program["id"], "code": "SEN101", "title": "Programming", "credits": 4}, headers=admin).json()
    data = api.post(f"{P}/courses", json={"program_id": program["id"], "code": "SEN201", "title": "Data Structures", "credits": 4}, headers=admin).json()
    assert api.post(f"{P}/courses/{data['id']}/prerequisites", json={"prerequisite_id": intro["id"]}, headers=admin).status_code == 201
    cycle = api.post(f"{P}/courses/{intro['id']}/prerequisites", json={"prerequisite_id": data["id"]}, headers=admin)
    assert cycle.status_code == 409 and "circular" in cycle.json()["error"]["message"]
    spring = api.post(f"{P}/terms", json={"name": "Spring", "starts_on": "2026-02-01", "ends_on": "2026-06-30", "status": "active"}, headers=admin).json()
    fall = api.post(f"{P}/terms", json={"name": "Fall", "starts_on": "2026-09-01", "ends_on": "2027-01-20", "status": "active"}, headers=admin).json()
    offering = lambda course, term, room: api.post(f"{P}/offerings", headers=admin, json={  # noqa: E731
        "course_id": course["id"], "term_id": term["id"], "instructor_user_id": "usr_instructor", "instructor_name": "Dr. Test", "room": room}).json()
    student = api.post(f"{P}/students", json={"name": "Nadia Nfor", "email": "nadia@example.test", "program_id": program["id"],
                                              "user_id": "usr_student"}, headers=admin).json()
    return {"program": program, "intro": intro, "data": data, "spring": spring, "fall": fall, "student": student,
            "intro_spring": offering(intro, spring, "Hall A"), "data_fall": offering(data, fall, "Hall B"),
            "intro_fall": offering(intro, fall, "Hall C")}


def test_prerequisites_results_appeals_and_outbox(api, tmp_path):
    ids = build_catalogue(api)
    admin, teacher, student = headers(api, "admin"), headers(api, "instructor"), headers(api, "student")
    early = api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["fall"]["id"],
                                                                "offering_ids": [ids["data_fall"]["id"]]})
    assert early.status_code == 409 and early.json()["error"]["details"][0]["missing"] == ["SEN101"]
    spring = api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["spring"]["id"],
                                                                 "offering_ids": [ids["intro_spring"]["id"]]})
    assert spring.status_code == 201
    offering = ids["intro_spring"]["id"]
    assessment = api.post(f"{P}/offerings/{offering}/assessments", json={"name": "Final", "weight": 60, "held_on": "2026-06-01"}, headers=teacher).json()
    assert api.post(f"{P}/offerings/{offering}/results/publish", headers=teacher).status_code == 422
    other = api.post(f"{P}/offerings/{offering}/assessments", json={"name": "Project", "weight": 40, "held_on": "2026-05-01"}, headers=teacher).json()
    assert api.put(f"{P}/assessments/{assessment['id']}/grades", headers=student,
                   json={"entries": [{"student_id": ids["student"]["id"], "score": 100}]}).status_code == 403
    for item, score in ((assessment, 70), (other, 40)):
        assert api.put(f"{P}/assessments/{item['id']}/grades", headers=teacher,
                       json={"entries": [{"student_id": ids["student"]["id"], "score": score}]}).status_code == 200
    published = api.post(f"{P}/offerings/{offering}/results/publish", headers=teacher)
    assert published.status_code == 200 and published.json()[0]["score"] == 58 and published.json()[0]["letter"] == "D"
    fall = api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["fall"]["id"],
                                                               "offering_ids": [ids["data_fall"]["id"]]})
    assert fall.status_code == 201 and fall.json()["courses"] == ["SEN201"]
    duplicate = api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["fall"]["id"],
                                                                    "offering_ids": [ids["data_fall"]["id"]]})
    assert duplicate.status_code == 409

    result_id = api.get(f"{P}/me/results", headers=student).json()[0]["id"]
    appeal = api.post(f"{P}/appeals", headers=student, json={"result_id": result_id, "reason": "Project mark omitted section two."})
    assert appeal.status_code == 201
    assert api.post(f"{P}/appeals", headers=student, json={"result_id": result_id, "reason": "Second appeal on same result"}).status_code == 409
    decided = api.post(f"{P}/appeals/{appeal.json()['id']}/decision", headers=teacher,
                       json={"decision": "approved", "note": "Section two re-marked", "revised_score": 66})
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    results = api.get(f"{P}/me/results", headers=student).json()
    assert [(row["revision"], row["current"], row["score"]) for row in results if row["current"]] == [(2, True, 66)]
    assert len(results) == 2
    transcript = api.get(f"{P}/me/transcript.pdf", headers=student)
    assert transcript.status_code == 200 and transcript.content.startswith(b"%PDF")

    database = Database(api.settings.database_url)
    with database.session() as session:
        events = session.scalars(select(OutboxEvent).order_by(OutboxEvent.occurred_at)).all()
        assert [event.event_type for event in events] == ["academic.enrollment.confirmed.v1"] * 2
        assert [event.payload["courses"] for event in events] == [["SEN101"], ["SEN201"]]
        assert {event.tenant_id for event in events} == {"tn_a"}

    class Channel:
        published = []

        def basic_publish(self, exchange, key, body, properties, mandatory):
            self.published.append((exchange, key, json.loads(body)))

    channel = Channel()
    assert relay_once(database, OutboxEvent, channel) == 2
    assert relay_once(database, OutboxEvent, channel) == 0
    message = channel.published[1][2]
    assert message["data"]["registration_id"] == fall.json()["id"] and message["schema_version"] == 1

    invoiced = {"event_id": "evt-1", "event_type": "finance.invoice.created.v1", "tenant_id": "tn_a", "correlation_id": "c",
                "schema_version": 1, "data": {"registration_id": fall.json()["id"], "invoice_number": "INV-1"}}
    handle_finance_event(database, invoiced)
    handle_finance_event(database, {**invoiced, "data": {"registration_id": fall.json()["id"], "invoice_number": "INV-2"}})
    with database.session("tn_a") as session:
        registration = session.get(Registration, fall.json()["id"])
        assert (registration.billing_status, registration.invoice_number) == ("invoiced", "INV-1")
        assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1


def test_tenant_and_role_isolation(api):
    ids = build_catalogue(api, "tn_a")
    other_admin = headers(api, "admin", "tn_b")
    assert api.get(f"{P}/programs", headers=other_admin).json()["total"] == 0
    assert api.patch(f"{P}/programs/{ids['program']['id']}", json={"name": "Hijacked name"}, headers=other_admin).status_code == 404
    assert api.post(f"{P}/courses", headers=other_admin, json={"program_id": ids["program"]["id"], "code": "X101", "title": "Injected",
                                                               "credits": 3}).status_code == 404
    assert api.get(f"{P}/students", headers=headers(api, "student")).status_code == 403
    assert api.get(f"{P}/students", headers=headers(api, "finance")).status_code == 403
    outsider = headers(api, "instructor", user="usr_someone_else")
    assert api.get(f"{P}/offerings/{ids['intro_fall']['id']}/roster", headers=outsider).status_code == 403
    assert api.get(f"{P}/programs").status_code == 401
    assert api.get(f"{P}/programs", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


def test_exam_conflicts(api):
    ids = build_catalogue(api)
    admin = headers(api, "admin")
    registration = api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["fall"]["id"],
                                                                       "offering_ids": [ids["intro_fall"]["id"]]}).json()
    assert registration["courses"] == ["SEN101"]
    base = {"title": "Midterm", "invigilator_name": "Dr. Test"}
    first = api.post(f"{P}/exams", headers=admin, json={**base, "offering_id": ids["intro_fall"]["id"], "room": "Hall A",
                                                        "invigilator_user_id": "usr_a", "starts_at": "2026-10-19T09:00:00", "ends_at": "2026-10-19T11:00:00"})
    assert first.status_code == 201
    clash = api.post(f"{P}/exams", headers=admin, json={**base, "offering_id": ids["data_fall"]["id"], "room": "hall a",
                                                        "invigilator_user_id": "usr_b", "starts_at": "2026-10-19T10:00:00", "ends_at": "2026-10-19T12:00:00"})
    assert clash.status_code == 409 and "Room Hall A is already booked" in clash.json()["error"]["details"][0]["reasons"]
    back_to_back = api.post(f"{P}/exams", headers=admin, json={**base, "offering_id": ids["data_fall"]["id"], "room": "Hall A",
                                                               "invigilator_user_id": "usr_a", "starts_at": "2026-10-19T11:00:00", "ends_at": "2026-10-19T13:00:00"})
    assert back_to_back.status_code == 201
    invigilator = api.post(f"{P}/exams/check", headers=admin, json={**base, "offering_id": ids["data_fall"]["id"], "room": "Lab 9",
                                                                    "invigilator_user_id": "usr_a", "starts_at": "2026-10-19T08:00:00", "ends_at": "2026-10-19T09:30:00"})
    assert invigilator.json()["ok"] is False
    listed = api.get(f"{P}/exams", headers=headers(api, "student")).json()
    assert [exam["course_code"] for exam in listed] == ["SEN101"]


def test_attendance_and_risk_endpoints(api):
    ids = build_catalogue(api)
    admin, teacher = headers(api, "admin"), headers(api, "instructor")
    api.post(f"{P}/registrations", headers=admin, json={"student_id": ids["student"]["id"], "term_id": ids["fall"]["id"],
                                                        "offering_ids": [ids["intro_fall"]["id"]]})
    offering = ids["intro_fall"]["id"]
    for day, status in (("2026-09-08", "present"), ("2026-09-10", "absent"), ("2026-09-15", "absent"), ("2026-09-17", "excused")):
        response = api.post(f"{P}/offerings/{offering}/attendance", headers=teacher,
                            json={"held_on": day, "records": [{"student_id": ids["student"]["id"], "status": status}]})
        assert response.status_code == 201
    future = (datetime.now(LOCAL_TZ).date() + timedelta(days=3)).isoformat()
    assert api.post(f"{P}/offerings/{offering}/attendance", headers=teacher,
                    json={"held_on": future, "records": [{"student_id": ids["student"]["id"], "status": "present"}]}).status_code == 422
    rows = api.get(f"{P}/risk", params={"offering_id": offering}, headers=teacher).json()
    assert rows[0]["status"] == "at_risk" and rows[0]["attendance_rate"] == pytest.approx(1 / 3, rel=1e-3)
    mine = api.get(f"{P}/risk", headers=headers(api, "student")).json()
    assert mine[0]["reasons"][0]["code"] == "low_attendance"
    pdf = api.get(f"{P}/reports/offerings/{offering}/attendance.pdf", headers=teacher)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    summaries = {row["id"]: row for row in api.get(f"{P}/dashboard", headers=teacher).json()["offerings"]}
    assert summaries[offering]["at_risk"] == 1
    assert api.get(f"{P}/dashboard", headers=admin).json()["totals"]["students"] == 1
    assert api.get(f"{P}/dashboard", headers=headers(api, "student")).json()["role"] == "student"


def test_message_delivery_retries_then_dead_letters():
    class Properties:
        def __init__(self, count):
            self.headers = {"x-death": [{"queue": "q", "reason": "rejected", "count": count}]} if count else {}

    class Method:
        delivery_tag = 7

    class Channel:
        def __init__(self):
            self.calls = []

        def basic_ack(self, tag):
            self.calls.append("ack")

        def basic_nack(self, tag, requeue):
            self.calls.append(f"nack:{requeue}")

        def basic_publish(self, exchange, key, body, properties):
            self.calls.append(f"publish:{exchange}")

    good = json.dumps({"event_id": "e", "event_type": "t", "tenant_id": "tn", "correlation_id": "c", "schema_version": 1, "data": {}}).encode()

    def failing(event):
        raise RuntimeError("database unavailable")

    channel = Channel()
    assert deliver(channel, "q", Method(), Properties(0), good, lambda event: None) == "ack"
    assert deliver(channel, "q", Method(), Properties(1), good, failing) == "retry"
    assert deliver(channel, "q", Method(), Properties(MAX_ATTEMPTS - 1), good, failing) == "dead"
    assert deliver(channel, "q", Method(), Properties(0), b"{not json", lambda event: None) == "dead"
    assert deliver(channel, "q", Method(), Properties(0), json.dumps({"event_id": "e"}).encode(), lambda event: None) == "dead"
    assert channel.calls == ["ack", "nack:False", "publish:campus.dead", "ack", "publish:campus.dead", "ack", "publish:campus.dead", "ack"]


def test_demo_seed_is_consistent(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'seed.db'}")
    database.create_all(Base.metadata)
    seed(database)
    seed(database)
    with database.session("tn_ictu") as session:
        assert session.scalar(select(func.count()).select_from(Registration)) > 40
        assert session.scalar(select(func.count()).select_from(Result).where(Result.current.is_(True))) > 40
        events = session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == "tn_ictu")).all()
        assert len(events) == 22 and all(event.payload["term_name"] == "2026 Fall" for event in events)
    with database.session("tn_atlantic") as session:
        assert session.scalar(select(func.count()).select_from(Registration)) > 40
    assert date.today() is not None
