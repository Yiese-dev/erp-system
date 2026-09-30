import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from packages.campus_common.config import LOCAL_SECRET
from packages.campus_common.database import Database
from packages.campus_common.errors import DomainError
from packages.campus_common.testing import bearer, settings_for
from services.finance.app.domain import payments
from services.finance.app.domain.billing import handle_enrollment_event
from services.finance.app.domain.ledger import post_entry, trial_balance
from services.finance.app.domain.reports import periods_between, run_monthly_schedule
from services.finance.app.main import create_app
from services.finance.app.models import (Base, BillingIssue, Invoice, JournalEntry, MonthlyReport, OutboxEvent, Payment, PaymentIntent,
                                         Receipt)
from services.finance.app.seed import seed
from services.finance.app.simulator import outcome

P = "/api/v1/finance"


class FakeProvider:
    def __init__(self):
        self.requests = []

    def request_to_pay(self, tenant_id, intent, msisdn):
        self.requests.append((tenant_id, intent.reference, intent.amount, msisdn))


@pytest.fixture
def api(tmp_path):
    settings = settings_for("finance", f"sqlite:///{tmp_path / 'finance.db'}")
    provider = FakeProvider()
    with TestClient(create_app(settings, provider)) as client:
        client.settings, client.provider = settings, provider
        client.database = Database(settings.database_url)
        yield client


def event(registration="reg_1", event_id="evt_1", tenant="tn_a", program="prg_se", term="trm_fall", user="usr_student"):
    return {"event_id": event_id, "event_type": "academic.enrollment.confirmed.v1", "tenant_id": tenant, "correlation_id": "corr",
            "schema_version": 1, "data": {"registration_id": registration, "student_id": "stu_1", "student_user_id": user,
                                          "student_name": "Nadia Nfor", "student_no": "ICT250001", "program_id": program,
                                          "program_name": "BSc Software Engineering", "term_id": term, "term_name": "2026 Fall",
                                          "courses": ["SEN201"]}}


def plan(api, tenant="tn_a", amount=425_000):
    return api.post(f"{P}/fee-plans", headers=bearer(api.settings, "finance", tenant), json={
        "program_id": "prg_se", "program_name": "BSc Software Engineering", "term_id": "trm_fall", "term_name": "2026 Fall", "amount": amount})


def callback(api, reference, status="SUCCESSFUL", amount=100_000, event_id="sim-1", tenant="tn_a", secret=LOCAL_SECRET, timestamp=None):
    body = json.dumps({"event_id": event_id, "reference": reference, "status": status, "amount": amount, "currency": "XAF"}).encode()
    stamp = timestamp or str(int(time.time()))
    return api.post(f"{P}/payment-webhooks/simulated/{tenant}", content=body,
                    headers={"Content-Type": "application/json", "X-Timestamp": stamp, "X-Signature": payments.sign(secret, stamp, body)})


def test_ledger_rejects_unbalanced_entries(api):
    with api.database.session("tn_a") as session:
        with pytest.raises(DomainError, match="unbalanced"):
            post_entry(session, "tn_a", date(2026, 9, 1), "bad", "test", "1", [("1200", 100, 0), ("4000", 0, 90)])
        with pytest.raises(DomainError, match="single positive"):
            post_entry(session, "tn_a", date(2026, 9, 1), "bad", "test", "2", [("1200", 100, 100), ("4000", 0, 0)])
        with pytest.raises(DomainError, match="Unknown ledger account"):
            post_entry(session, "tn_a", date(2026, 9, 1), "bad", "test", "3", [("9999", 100, 0), ("4000", 0, 100)])


def test_enrollment_events_are_idempotent_and_missing_plans_are_recoverable(api):
    assert handle_enrollment_event(api.database, event()) == "issue"
    with api.database.session("tn_a") as session:
        assert session.scalar(select(func.count()).select_from(BillingIssue).where(BillingIssue.status == "open")) == 1
    created = plan(api)
    assert created.status_code == 201 and created.json()["resolved_issues"] == 1
    assert handle_enrollment_event(api.database, event()) == "duplicate"
    assert handle_enrollment_event(api.database, event(event_id="evt_2")) == "existing"
    with api.database.session("tn_a") as session:
        invoices = session.scalars(select(Invoice)).all()
        assert len(invoices) == 1 and invoices[0].total == 425_000 and invoices[0].number.startswith("INV-")
        assert invoices[0].fee_snapshot["courses"] == ["SEN201"]
        types = [row.event_type for row in session.scalars(select(OutboxEvent)).all()]
        assert "finance.billing.issue.v1" in types and "finance.invoice.created.v1" in types
        assert trial_balance(session)["balanced"]
    with pytest.raises(Exception, match="missing required"):
        handle_enrollment_event(api.database, {**event(event_id="evt_bad"), "data": {"registration_id": "x"}})


def test_mobile_money_payment_callback_flow(api):
    plan(api)
    handle_enrollment_event(api.database, event())
    student = bearer(api.settings, "student", user_id="usr_student")
    invoice = api.get(f"{P}/invoices", headers=student).json()["items"][0]
    assert api.get(f"{P}/invoices", headers=bearer(api.settings, "student", user_id="usr_other")).json()["total"] == 0
    assert api.get(f"{P}/invoices/{invoice['id']}", headers=bearer(api.settings, "student", user_id="usr_other")).status_code == 404
    assert api.get(f"{P}/invoices/{invoice['id']}", headers=bearer(api.settings, "finance", "tn_b")).status_code == 404

    too_much = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student,
                        json={"provider": "mtn_momo", "msisdn": "677123456", "amount": 500_000, "idempotency_key": "key-overpay"})
    assert too_much.status_code == 409
    body = {"provider": "mtn_momo", "msisdn": "+237 677 12 34 56", "amount": 100_000, "idempotency_key": "key-first-attempt"}
    started = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student, json=body)
    assert started.status_code == 201 and started.json()["status"] == "pending" and started.json()["msisdn_masked"] == "677****56"
    again = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student, json=body)
    assert again.json()["id"] == started.json()["id"] and len(api.provider.requests) == 1
    reference = api.provider.requests[0][1]

    assert callback(api, reference, secret="wrong-secret").status_code == 401
    assert callback(api, reference, timestamp=str(int(time.time()) - 3600)).status_code == 401
    assert callback(api, reference, tenant="tn_b").status_code == 404
    settled = callback(api, reference)
    assert settled.status_code == 200 and settled.json()["status"] == "settled"
    assert callback(api, reference).json()["status"] == "duplicate"
    assert callback(api, reference, event_id="sim-2").json()["status"] == "ignored"

    status = api.get(f"{P}/payment-intents/{started.json()['id']}", headers=student).json()
    assert status["status"] == "succeeded" and status["receipt_number"].startswith("RCT-")
    detail = api.get(f"{P}/invoices/{invoice['id']}", headers=student).json()
    assert detail["invoice"]["status"] == "partially_paid" and detail["invoice"]["balance"] == 325_000
    pdf = api.get(f"{P}/receipts/{status['receipt_id']}.pdf", headers=student)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    second = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student,
                      json={**body, "amount": 325_000, "idempotency_key": "key-second-attempt"}).json()
    assert callback(api, api.provider.requests[1][1], amount=1, event_id="sim-3").json()["status"] == "rejected"
    third = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student,
                     json={**body, "amount": 325_000, "idempotency_key": "key-third-attempt"}).json()
    assert callback(api, api.provider.requests[2][1], status="FAILED", amount=325_000, event_id="sim-4").json()["status"] == "failed"
    assert second["id"] != third["id"]
    fourth = api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student,
                      json={**body, "amount": 325_000, "idempotency_key": "key-fourth-attempt"}).json()
    assert callback(api, api.provider.requests[3][1], amount=325_000, event_id="sim-5").json()["status"] == "settled"
    final = api.get(f"{P}/invoices/{invoice['id']}", headers=student).json()
    assert final["invoice"]["status"] == "paid" and len(final["receipts"]) == 2 and fourth["status"] == "pending"
    with api.database.session("tn_a") as session:
        assert trial_balance(session)["balanced"]
        assert "finance.invoice.settled.v1" in {row.event_type for row in session.scalars(select(OutboxEvent)).all()}


def test_payment_and_ledger_roll_back_together(api, monkeypatch):
    plan(api)
    handle_enrollment_event(api.database, event())
    student = bearer(api.settings, "student", user_id="usr_student")
    invoice = api.get(f"{P}/invoices", headers=student).json()["items"][0]
    api.post(f"{P}/invoices/{invoice['id']}/payment-intents", headers=student,
             json={"provider": "orange_money", "msisdn": "699123456", "amount": 50_000, "idempotency_key": "key-rollback-1"})

    def broken_ledger(*args, **kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(payments, "post_entry", broken_ledger)
    with api.database.session("tn_a") as session:
        entries_before = session.scalar(select(func.count()).select_from(JournalEntry))
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        callback(api, api.provider.requests[0][1], amount=50_000)
    with api.database.session("tn_a") as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 0
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0
        assert session.scalar(select(func.count()).select_from(JournalEntry)) == entries_before
        assert session.get(Invoice, invoice["id"]).paid == 0
        assert session.scalar(select(PaymentIntent)).status == "pending"
    monkeypatch.undo()
    assert callback(api, api.provider.requests[0][1], amount=50_000).json()["status"] == "settled"


def test_expenses_campaign_roi_and_reports(api):
    plan(api)
    handle_enrollment_event(api.database, event())
    finance, admin = bearer(api.settings, "finance"), bearer(api.settings, "admin")
    campaign = api.post(f"{P}/campaigns", headers=finance, json={"name": "Radio", "channel": "radio", "starts_on": "2026-01-01",
                                                                 "ends_on": "2026-12-31", "budget": 500_000}).json()
    expense = api.post(f"{P}/expenses", headers=finance, json={"category": "marketing", "description": "Radio spots", "vendor": "FM",
                                                               "amount": 200_000, "expense_date": "2026-09-01", "campaign_id": campaign["id"]}).json()
    assert api.post(f"{P}/expenses/{expense['id']}/approve", headers=finance, json={}).status_code == 403
    assert api.post(f"{P}/expenses/{expense['id']}/pay", headers=admin, json={"reference": "CHQ-1"}).status_code == 409
    assert api.post(f"{P}/expenses/{expense['id']}/approve", headers=admin, json={}).json()["status"] == "approved"
    assert api.post(f"{P}/expenses/{expense['id']}/pay", headers=admin, json={"reference": "CHQ-1"}).json()["status"] == "paid"
    lead = api.post(f"{P}/campaigns/{campaign['id']}/leads", headers=finance, json={"name": "Nadia Nfor", "phone": "677000111"}).json()
    assert api.patch(f"{P}/leads/{lead['id']}", headers=finance, json={"stage": "qualified"}).json()["stage"] == "qualified"
    assert api.post(f"{P}/leads/{lead['id']}/convert", headers=finance, json={"student_id": "stu_unknown"}).status_code == 422
    assert api.post(f"{P}/leads/{lead['id']}/convert", headers=finance, json={"student_id": "stu_1"}).json()["stage"] == "converted"
    invoice = api.get(f"{P}/invoices", headers=finance).json()["items"][0]
    manual = api.post(f"{P}/invoices/{invoice['id']}/payments", headers=finance, json={"method": "bank_transfer", "amount": 300_000,
                                                                                      "reference": "VIR-001"})
    assert manual.status_code == 201 and manual.json()["invoice"]["status"] == "partially_paid"
    metrics = next(row for row in api.get(f"{P}/campaigns", headers=finance).json() if row["id"] == campaign["id"])
    assert (metrics["spend"], metrics["revenue"], metrics["conversions"], metrics["roi_percent"]) == (200_000, 300_000, 1, 50.0)
    assert api.get(f"{P}/campaigns", headers=bearer(api.settings, "student")).status_code == 403
    dashboard = api.get(f"{P}/dashboard", headers=finance).json()
    assert dashboard["totals"]["collected"] == 300_000 and dashboard["ledger_balanced"] is True
    assert api.get(f"{P}/ledger/trial-balance", headers=finance).json()["balanced"] is True
    assert api.post(f"{P}/reports/monthly", headers=finance, json={"period": "2099-01"}).status_code == 422
    report = api.post(f"{P}/reports/monthly", headers=finance, json={"period": "2026-01"}).json()
    assert report["version"] == 1 and report["summary"]["currency"] == "XAF"
    assert api.get(f"{P}/reports/monthly/{report['id']}.pdf", headers=finance).content.startswith(b"%PDF")


def test_monthly_scheduler_catches_up_once(api):
    plan(api)
    handle_enrollment_event(api.database, event())
    with api.database.session() as session:
        from services.finance.app.models import KnownTenant
        session.get(KnownTenant, "tn_a").first_period = "2026-01"
    first = run_monthly_schedule(api.database, today=date(2026, 4, 2))
    assert first == [("tn_a", "2026-01"), ("tn_a", "2026-02"), ("tn_a", "2026-03")]
    assert run_monthly_schedule(api.database, today=date(2026, 4, 30)) == []
    with api.database.session("tn_a") as session:
        assert session.scalar(select(func.count()).select_from(MonthlyReport)) == 3
    assert periods_between("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01"]


def test_simulator_rules_and_msisdn_validation():
    assert outcome("677123450")[0] == "FAILED"
    assert outcome("677123459")[0] is None
    assert outcome("677123451")[0] == "SUCCESSFUL"
    assert payments.normalize_msisdn("+237 699-12-34-56") == "699123456"
    with pytest.raises(DomainError):
        payments.normalize_msisdn("0712345678")


def test_demo_seed_balances(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'seed.db'}")
    database.create_all(Base.metadata)
    seed(database)
    seed(database)
    with database.session("tn_ictu") as session:
        assert session.scalar(select(func.count()).select_from(Invoice)) == 24 + 6 + 17
        balance = trial_balance(session)
        assert balance["balanced"] and balance["total_debit"] > 0
    assert len(run_monthly_schedule(database, today=date(2026, 9, 30))) == 16
