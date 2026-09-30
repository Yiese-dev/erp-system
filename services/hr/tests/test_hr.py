from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from packages.campus_common.database import Database, local_now, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.testing import bearer, settings_for
from services.hr.app.domain import attendance, operations
from services.hr.app.domain.notifications import send_pending
from services.hr.app.domain.payroll import DRAFT_RULES, calculate, progressive_tax, validate_rules
from services.hr.app.main import create_app
from services.hr.app.models import Base, Employee, Notification
from services.hr.app.seed import seed

P = "/api/v1/hr"
BRACKETS = DRAFT_RULES["irpp"]["brackets"]


def test_progressive_tax_bracket_boundaries():
    from decimal import Decimal
    assert progressive_tax(Decimal(2_000_000), BRACKETS) == Decimal("200000.00")
    assert progressive_tax(Decimal(3_000_000), BRACKETS) == Decimal("350000.00")
    assert progressive_tax(Decimal(5_000_000), BRACKETS) == Decimal("850000.00")
    assert progressive_tax(Decimal(6_000_000), BRACKETS) == Decimal("1200000.00")
    assert progressive_tax(Decimal(0), BRACKETS) == 0


def test_payslip_matches_hand_calculation():
    slip = calculate(450_000, 50_000, DRAFT_RULES)
    codes = {line["code"]: line["amount"] for line in slip["employee"] + slip["employer"]}
    # 500,000 gross: CNPS 21,000; taxable 350,000 - 21,000 - 41,666.67 = 287,333 -> annual 3,448,000 -> 462,000/yr -> 38,500/month
    assert (slip["gross"], codes["CNPS_PVID"], codes["IRPP"], codes["CAC"], codes["CFC"]) == (500_000, 21_000, 38_500, 3_850, 5_000)
    assert slip["net"] == 500_000 - 21_000 - 38_500 - 3_850 - 5_000
    assert (codes["CNPS_PVID_ER"], codes["CNPS_PF"], codes["CNPS_AT"], codes["CFC_ER"], codes["FNE"]) == (21_000, 35_000, 8_750, 7_500, 5_000)
    assert slip["employer_total"] == 77_250


def test_ceiling_and_exemption():
    high = {line["code"]: line["amount"] for line in calculate(1_200_000, 0, DRAFT_RULES)["employee"]}
    assert high["CNPS_PVID"] == 31_500
    low = {line["code"]: line["amount"] for line in calculate(60_000, 0, DRAFT_RULES)["employee"]}
    assert (low["IRPP"], low["CAC"], low["CNPS_PVID"]) == (0, 0, 2_520)


def test_rule_validation_rejects_bad_scales():
    bad = {**DRAFT_RULES, "irpp": {**DRAFT_RULES["irpp"], "brackets": [[3_000_000, "0.1"], [2_000_000, "0.15"], [None, "0.35"]]}}
    with pytest.raises(DomainError, match="ascend"):
        validate_rules(bad)
    with pytest.raises(DomainError, match="between 0 and 1"):
        validate_rules({**DRAFT_RULES, "cnps": {**DRAFT_RULES["cnps"], "employee_rate": "4.2"}})


def test_working_days_skip_weekends_and_holidays():
    from datetime import date
    assert operations.working_days(date(2026, 12, 21), date(2026, 12, 27)) == 4
    assert operations.working_days(date(2026, 10, 3), date(2026, 10, 4)) == 0


@pytest.fixture
def api(tmp_path):
    settings = settings_for("hr", f"sqlite:///{tmp_path / 'hr.db'}")
    with TestClient(create_app(settings)) as client:
        client.settings = settings
        client.database = Database(settings.database_url)
        yield client


def staff(api, tenant="tn_a"):
    hr = bearer(api.settings, "hr", tenant, "usr_hr")
    department = api.post(f"{P}/departments", headers=hr, json={"name": "IT Services"}).json()
    make = lambda name, user, salary: api.post(f"{P}/employees", headers=hr, json={  # noqa: E731
        "name": name, "email": f"{user}@example.test", "department_id": department["id"], "position": "Officer",
        "base_salary": salary, "allowances": 0, "hired_on": "2024-01-10", "user_id": user}).json()
    return {"hr": hr, "department": department, "hr_employee": make("Marie Ngono", "usr_hr", 600_000),
            "employee": make("Daniel Ekane", "usr_employee", 450_000)}


def test_payroll_requires_approved_rules_and_is_immutable(api):
    people = staff(api)
    hr = people["hr"]
    period = (local_now().date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    draft = api.post(f"{P}/payroll/rule-sets", headers=hr, json={"name": "Cameroon 2026 draft", "effective_from": "2026-01-01",
                                                                 "rules": DRAFT_RULES, "sources": [{"title": "CGI 2026", "url": "https://www.impots.cm"}]}).json()
    blocked = api.post(f"{P}/payroll/runs", headers=hr, json={"period": period})
    assert blocked.status_code == 409 and "approve" in blocked.json()["error"]["message"]
    assert api.post(f"{P}/payroll/rule-sets/{draft['id']}/approve", headers=hr, json={"note": "ok"}).status_code == 422
    assert api.post(f"{P}/payroll/rule-sets/{draft['id']}/approve", headers=bearer(api.settings, "employee", user_id="usr_employee"),
                    json={"note": "Verified against CGI 2026 Art. 69"}).status_code == 403
    approved = api.post(f"{P}/payroll/rule-sets/{draft['id']}/approve", headers=hr, json={"note": "Verified against CGI 2026 Art. 69 and CNPS schedule"})
    assert approved.json()["status"] == "approved"
    run = api.post(f"{P}/payroll/runs", headers=hr, json={"period": period}).json()
    assert run["totals"]["headcount"] == 2 and run["totals"]["gross"] == 1_050_000
    assert api.post(f"{P}/payroll/runs", headers=hr, json={"period": period}).status_code == 409
    future = (local_now().date() + timedelta(days=40)).strftime("%Y-%m")
    assert api.post(f"{P}/payroll/runs", headers=hr, json={"period": future}).status_code == 422
    employee = bearer(api.settings, "employee", user_id="usr_employee")
    assert api.get(f"{P}/me", headers=employee).json()["payslips"] == []
    assert api.post(f"{P}/payroll/runs/{run['id']}/finalize", headers=hr).json()["status"] == "finalized"
    assert api.post(f"{P}/payroll/runs/{run['id']}/finalize", headers=hr).status_code == 409
    assert api.delete(f"{P}/payroll/runs/{run['id']}", headers=hr).status_code == 409
    mine = api.get(f"{P}/me", headers=employee).json()["payslips"]
    assert len(mine) == 1 and mine[0]["gross"] == 450_000
    pdf = api.get(f"{P}/payslips/{mine[0]['id']}.pdf", headers=employee)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other = api.get(f"{P}/payroll/runs/{run['id']}", headers=hr).json()["payslips"]
    hr_slip = next(slip for slip in other if slip["employee_name"] == "Marie Ngono")
    assert api.get(f"{P}/payslips/{hr_slip['id']}.pdf", headers=employee).status_code == 404
    titles = [row["title"] for row in api.get(f"{P}/notifications", headers=employee).json()]
    assert any("Payslip" in title for title in titles)


def test_qr_attendance_is_signed_expiring_and_tenant_bound(api):
    people = staff(api)
    kiosk = api.post(f"{P}/attendance/challenges", headers=people["hr"], json={"kiosk": "Main entrance"}).json()
    assert kiosk["qr"].startswith("data:image/png;base64,") and len(kiosk["code"]) == 6
    employee = bearer(api.settings, "employee", user_id="usr_employee")
    forged = kiosk["token"][:-4] + "0000"
    assert api.post(f"{P}/attendance/check-in", headers=employee, json={"token": forged}).status_code == 422
    assert api.post(f"{P}/attendance/check-in", headers=bearer(api.settings, "employee", "tn_b", "usr_employee"),
                    json={"token": kiosk["token"]}).status_code == 404
    first = api.post(f"{P}/attendance/check-in", headers=employee, json={"token": kiosk["token"]})
    assert first.status_code == 200 and first.json()["action"] == "check_in"
    assert api.post(f"{P}/attendance/check-in", headers=employee, json={"code": kiosk["code"]}).status_code == 409
    assert api.post(f"{P}/attendance/check-in", headers=bearer(api.settings, "student"), json={"code": kiosk["code"]}).status_code == 403
    with api.database.session("tn_a") as session:
        worker = session.scalar(select(Employee).where(Employee.user_id == "usr_employee"))
        later = utcnow() + timedelta(minutes=30)
        with pytest.raises(DomainError, match="expired"):
            attendance.check_in(session, "tn_a", worker, api.settings.qr_secret, token=kiosk["token"], now=later)
        _, token = attendance.issue_challenge(session, "tn_a", "Staff room", "usr_hr", api.settings.qr_secret, now=later)
        action, log = attendance.check_in(session, "tn_a", worker, api.settings.qr_secret, token=token, now=later)
        assert action == "check_out" and log.check_out_at == later
    board = api.get(f"{P}/attendance", headers=people["hr"]).json()
    assert board["present"] == 1 and board["headcount"] == 2


def test_leave_workflow_balances_and_self_approval(api):
    people = staff(api)
    hr, employee = people["hr"], bearer(api.settings, "employee", user_id="usr_employee")
    start = local_now().date() + timedelta(days=14)
    while start.weekday():
        start += timedelta(days=1)
    request = api.post(f"{P}/leave", headers=employee, json={"kind": "annual", "starts_on": start.isoformat(),
                                                             "ends_on": (start + timedelta(days=4)).isoformat(), "reason": "Family"})
    assert request.status_code == 201 and request.json()["days"] == 5
    assert api.post(f"{P}/leave", headers=employee, json={"kind": "annual", "starts_on": start.isoformat(),
                                                          "ends_on": start.isoformat()}).status_code == 409
    too_long = api.post(f"{P}/leave", headers=employee, json={"kind": "annual", "starts_on": (start + timedelta(days=21)).isoformat(),
                                                              "ends_on": (start + timedelta(days=46)).isoformat()})
    assert too_long.status_code == 409 and "remain" in too_long.json()["error"]["message"]
    hr_titles = [row["title"] for row in api.get(f"{P}/notifications", headers=hr).json()]
    assert "Leave request from Daniel Ekane" in hr_titles
    own = api.post(f"{P}/leave", headers=hr, json={"kind": "sick", "starts_on": start.isoformat(), "ends_on": start.isoformat()}).json()
    assert api.post(f"{P}/leave/{own['id']}/decision", headers=hr, json={"decision": "approved"}).status_code == 403
    approved = api.post(f"{P}/leave/{request.json()['id']}/decision", headers=hr, json={"decision": "approved", "note": "Enjoy"})
    assert approved.json()["status"] == "approved"
    assert api.post(f"{P}/leave/{request.json()['id']}/decision", headers=hr, json={"decision": "rejected"}).status_code == 409
    profile = api.get(f"{P}/me", headers=employee).json()
    annual = next(row for row in profile["balances"] if row["kind"] == "annual")
    assert (annual["used"], annual["available"]) == (5, 13)
    assert any(row["title"] == "Leave request approved" for row in api.get(f"{P}/notifications", headers=employee).json())
    assert api.post(f"{P}/leave/{request.json()['id']}/cancel", headers=employee).json()["status"] == "cancelled"
    assert next(row for row in api.get(f"{P}/me", headers=employee).json()["balances"] if row["kind"] == "annual")["used"] == 0
    assert api.get(f"{P}/leave", headers=bearer(api.settings, "hr", "tn_b", "usr_hr")).json() == []


def test_recruitment_assets_inventory_and_dashboard(api):
    people = staff(api)
    hr = people["hr"]
    vacancy = api.post(f"{P}/recruitment/vacancies", headers=hr, json={"title": "Network Technician", "department_id": people["department"]["id"]}).json()
    applicant = api.post(f"{P}/recruitment/applicants", headers=hr, json={"vacancy_id": vacancy["id"], "name": "Ines Nkwenti",
                                                                           "email": "ines@example.test"}).json()
    assert api.post(f"{P}/recruitment/applicants/{applicant['id']}/stage", headers=hr, json={"stage": "hired"}).status_code == 409
    for stage in ("screened", "interview"):
        assert api.post(f"{P}/recruitment/applicants/{applicant['id']}/stage", headers=hr, json={"stage": stage}).status_code == 200
    assert api.post(f"{P}/recruitment/applicants/{applicant['id']}/stage", headers=hr, json={"stage": "offered"}).status_code == 422
    api.post(f"{P}/recruitment/applicants/{applicant['id']}/stage", headers=hr, json={"stage": "offered", "offered_salary": 350_000})
    hired = api.post(f"{P}/recruitment/applicants/{applicant['id']}/stage", headers=hr, json={"stage": "hired"}).json()
    assert hired["employee_id"]
    assert api.get(f"{P}/employees", headers=hr).json()["total"] == 3
    assert api.get(f"{P}/recruitment/vacancies", headers=hr).json()[0]["status"] == "filled"

    asset = api.post(f"{P}/assets", headers=hr, json={"tag": "LPT-001", "name": "Laptop", "category": "laptop", "location": "Lab 1",
                                                      "purchased_on": "2025-01-01", "value": 600_000}).json()
    assert api.post(f"{P}/assets/{asset['id']}/assign", headers=hr, json={"employee_id": hired["employee_id"]}).json()["status"] == "assigned"
    assert api.post(f"{P}/assets/{asset['id']}/assign", headers=hr, json={"employee_id": hired["employee_id"]}).status_code == 409
    assert api.post(f"{P}/assets/{asset['id']}/return", headers=hr, json={"condition": "poor"}).json()["status"] == "maintenance"
    assert len(api.get(f"{P}/assets/{asset['id']}/history", headers=hr).json()) == 1

    item = api.post(f"{P}/inventory", headers=hr, json={"sku": "TON-1", "name": "Toner", "unit": "cartridges", "quantity": 5,
                                                        "reorder_level": 2}).json()
    assert api.post(f"{P}/inventory/{item['id']}/movements", headers=hr, json={"delta": -9, "reason": "Issue"}).status_code == 409
    moved = api.post(f"{P}/inventory/{item['id']}/movements", headers=hr, json={"delta": -3, "reason": "Issued to printer room"}).json()
    assert moved["item"]["quantity"] == 2 and moved["item"]["low"] is True
    assert any(row["title"] == "Low stock: Toner" for row in api.get(f"{P}/notifications", headers=hr).json())
    board = api.get(f"{P}/dashboard", headers=hr).json()
    assert board["headcount"] == 3 and board["assets_by_status"] == {"maintenance": 1} and board["low_stock"][0]["sku"] == "TON-1"
    assert api.get(f"{P}/dashboard", headers=bearer(api.settings, "employee", user_id="usr_employee")).status_code == 403
    assert api.get(f"{P}/employees/{hired['employee_id']}", headers=bearer(api.settings, "hr", "tn_b", "usr_hr")).status_code == 404


def test_email_delivery_is_retried_without_blocking(api, monkeypatch):
    people = staff(api)
    start = local_now().date() + timedelta(days=10)
    while start.weekday():
        start += timedelta(days=1)
    api.post(f"{P}/leave", headers=bearer(api.settings, "employee", user_id="usr_employee"),
             json={"kind": "annual", "starts_on": start.isoformat(), "ends_on": start.isoformat()})
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            if host == "down":
                raise OSError("connection refused")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send_message(self, message):
            sent.append(message["To"])

    monkeypatch.setattr("services.hr.app.domain.notifications.smtplib.SMTP", FakeSMTP)
    assert send_pending(api.database, "down", 25, "erp@test") == 0
    with api.database.session("tn_a") as session:
        note = session.scalar(select(Notification))
        assert (note.email_status, note.email_attempts) == ("pending", 1)
    assert send_pending(api.database, "mail", 25, "erp@test") == 1
    assert sent == [api.settings.hr_mailbox]
    assert send_pending(api.database, "mail", 25, "erp@test") == 0
    assert people["employee"]["employee_no"] == "EMP002"


def test_demo_seed(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'seed.db'}")
    database.create_all(Base.metadata)
    seed(database)
    seed(database)
    with database.session("tn_ictu") as session:
        assert session.scalar(select(func.count()).select_from(Employee)) == 14
        assert session.scalar(select(func.count()).select_from(Notification)) >= 3
