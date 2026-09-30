import re
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

from fastapi import Depends, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from packages.campus_common.config import Settings, load_settings
from packages.campus_common.database import Database, fetch, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.http import create_application
from packages.campus_common.schemas import Page, as_dict, out_schema, paginate
from packages.campus_common.security import Actor, current_actor
from services.finance.app.domain import billing, marketing, payments, reports
from services.finance.app.domain.ledger import ACCOUNTS, EXPENSE_ACCOUNTS, trial_balance
from services.finance.app.models import (Base, BillingIssue, Campaign, Expense, FeePlan, Invoice, InvoiceLine, JournalEntry, JournalLine,
                                         Lead, MonthlyReport, Payment, PaymentIntent, Receipt)

READ = ("finance:read", "finance:write")
TENANT_PATTERN = r"^[a-z0-9_]{1,64}$"


class FeePlanIn(BaseModel):
    program_id: str = Field(max_length=64)
    program_name: str = Field(min_length=2, max_length=160)
    term_id: str = Field(max_length=64)
    term_name: str = Field(min_length=2, max_length=60)
    amount: int = Field(gt=0, le=50_000_000)
    due_days: int = Field(30, ge=0, le=180)


class FeePlanPatch(BaseModel):
    amount: int | None = Field(None, gt=0, le=50_000_000)
    due_days: int | None = Field(None, ge=0, le=180)
    active: bool | None = None


class PaymentStart(BaseModel):
    provider: Literal["mtn_momo", "orange_money"]
    msisdn: str = Field(min_length=9, max_length=20)
    amount: int = Field(gt=0, le=50_000_000)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9-]+$")


class ManualPayment(BaseModel):
    method: Literal["bank_transfer", "cash"]
    amount: int = Field(gt=0, le=50_000_000)
    reference: str = Field(min_length=3, max_length=80)


class ExpenseIn(BaseModel):
    category: Literal["marketing", "supplies", "maintenance", "utilities", "it_services", "travel", "other"]
    description: str = Field(min_length=3, max_length=200)
    vendor: str = Field(min_length=2, max_length=160)
    amount: int = Field(gt=0, le=500_000_000)
    expense_date: date
    campaign_id: str | None = Field(None, max_length=64)


class NoteIn(BaseModel):
    note: str = Field("", max_length=300)


class PayIn(BaseModel):
    reference: str = Field(min_length=3, max_length=80)


class CampaignIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    channel: Literal["social", "radio", "events", "print", "referral", "search", "email"]
    starts_on: date
    ends_on: date
    budget: int = Field(ge=0, le=500_000_000)


class CampaignPatch(BaseModel):
    status: Literal["planned", "active", "completed", "paused"]


class LeadIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    phone: str = Field(min_length=9, max_length=20)
    email: str | None = Field(None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    program_interest: str = Field("", max_length=160)
    notes: str = Field("", max_length=2000)


class LeadPatch(BaseModel):
    stage: Literal["new", "contacted", "qualified", "applied", "lost"] | None = None
    notes: str | None = Field(None, max_length=2000)


class ConvertIn(BaseModel):
    student_id: str = Field(max_length=64)


class ReportIn(BaseModel):
    period: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")


FeePlanOut = out_schema(FeePlan)
InvoiceOut = out_schema(Invoice, balance=(int, 0), overdue=(bool, False))
IntentOut = out_schema(PaymentIntent, exclude=("idempotency_key",), receipt_id=(str | None, None), receipt_number=(str | None, None))
ReceiptOut = out_schema(Receipt, amount=(int, 0), method=(str, ""), invoice_number=(str, ""), student_name=(str, ""), term_name=(str, ""))
ExpenseOut = out_schema(Expense)
LeadOut = out_schema(Lead)
IssueOut = out_schema(BillingIssue)
ReportOut = out_schema(MonthlyReport)


def invoice_view(invoice: Invoice) -> dict:
    today = local_now().date()
    return as_dict(invoice, balance=invoice.total - invoice.paid,
                   overdue=invoice.status in ("issued", "partially_paid") and invoice.due_on < today)


def receipt_views(session, receipts: list[Receipt]) -> list[dict]:
    if not receipts:
        return []
    paid = {row.id: row for row in session.scalars(select(Payment).where(Payment.id.in_([r.payment_id for r in receipts]))).all()}
    invoices = {row.id: row for row in session.scalars(select(Invoice).where(Invoice.id.in_([r.invoice_id for r in receipts]))).all()}
    return [as_dict(r, amount=paid[r.payment_id].amount, method=paid[r.payment_id].method, invoice_number=invoices[r.invoice_id].number,
                    student_name=invoices[r.invoice_id].student_name, term_name=invoices[r.invoice_id].term_name) for r in receipts]


def intent_view(session, intent: PaymentIntent) -> dict:
    receipt = None
    if intent.status == "succeeded":
        receipt = session.scalar(select(Receipt).join(Payment, Payment.id == Receipt.payment_id).where(Payment.intent_id == intent.id))
    return as_dict(intent, receipt_id=receipt.id if receipt else None, receipt_number=receipt.number if receipt else None)


def create_app(settings: Settings, provider=None):
    database = Database(settings.database_url)
    gateway = provider or (payments.SimulatedMobileMoneyProvider(settings.simulator_url, settings.simulator_key, settings.callback_base_url)
                           if settings.simulator_url else None)

    @asynccontextmanager
    async def lifespan(application):
        if settings.create_schema:
            database.create_all(Base.metadata)
        yield
        database.engine.dispose()

    app = create_application(settings, database, lifespan)
    p = "/api/v1/finance"

    def scoped(actor: Actor):
        return database.session(actor.tenant_id)

    def own_invoice(session, actor: Actor, invoice_id: str) -> Invoice:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None or not (actor.can(*READ) or (actor.can("finance:self") and invoice.student_user_id == actor.user_id)):
            raise DomainError("Invoice not found.", 404)
        return invoice

    # ---------- Fee plans and billing issues ----------
    @app.get(f"{p}/fee-plans", response_model=list[FeePlanOut], tags=["Billing"])
    def list_fee_plans(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            return [as_dict(plan) for plan in session.scalars(select(FeePlan).order_by(FeePlan.term_name.desc(), FeePlan.program_name)).all()]

    @app.post(f"{p}/fee-plans", status_code=201, tags=["Billing"])
    def create_fee_plan(payload: FeePlanIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        """Creating a missing plan automatically re-bills registrations that were waiting on it."""
        actor.require("finance:write")
        with scoped(actor) as session:
            billing.remember_tenant(session, actor.tenant_id, actor.tenant_name)
            plan = FeePlan(id=new_id("fee"), tenant_id=actor.tenant_id, active=True, created_at=utcnow(), **payload.model_dump())
            session.add(plan)
            session.flush()
            resolved = billing.retry_issues_for_plan(session, actor.tenant_id, plan)
            return {"plan": as_dict(plan), "resolved_issues": resolved}

    @app.patch(f"{p}/fee-plans/{{plan_id}}", response_model=FeePlanOut, tags=["Billing"])
    def update_fee_plan(plan_id: str, payload: FeePlanPatch, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            plan = fetch(session, FeePlan, plan_id, "Fee plan")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(plan, key, value)
            return as_dict(plan)

    @app.get(f"{p}/billing-issues", response_model=list[IssueOut], tags=["Billing"])
    def list_issues(status: str = "open", actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(BillingIssue).order_by(BillingIssue.created_at.desc())
            if status:
                query = query.where(BillingIssue.status == status)
            return [as_dict(row) for row in session.scalars(query).all()]

    @app.post(f"{p}/billing-issues/{{issue_id}}/retry", response_model=InvoiceOut, tags=["Billing"])
    def retry(issue_id: str, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            return invoice_view(billing.retry_issue(session, actor.tenant_id, fetch(session, BillingIssue, issue_id, "Billing issue")))

    # ---------- Invoices ----------
    @app.get(f"{p}/invoices", response_model=Page[InvoiceOut], tags=["Invoices"])
    def list_invoices(q: str = "", status: str = "", term_id: str = "", overdue: bool = False, page: int = 1, size: int = 25,
                      actor: Actor = Depends(current_actor)):
        actor.require(*READ, "finance:self")
        with scoped(actor) as session:
            query = select(Invoice).order_by(Invoice.issued_at.desc(), Invoice.number.desc())
            if not actor.can(*READ):
                query = query.where(Invoice.student_user_id == actor.user_id)
            if q:
                query = query.where(or_(Invoice.number.ilike(f"%{q}%"), Invoice.student_name.ilike(f"%{q}%"), Invoice.student_no.ilike(f"%{q}%")))
            if status:
                query = query.where(Invoice.status == status)
            if term_id:
                query = query.where(Invoice.term_id == term_id)
            if overdue:
                query = query.where(Invoice.status.in_(("issued", "partially_paid")), Invoice.due_on < local_now().date())
            return paginate(session, query, page, size, serialize=invoice_view)

    @app.get(f"{p}/invoices/{{invoice_id}}", tags=["Invoices"])
    def invoice_detail(invoice_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        with scoped(actor) as session:
            invoice = own_invoice(session, actor, invoice_id)
            lines = session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).all()
            receipts = session.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id).order_by(Receipt.issued_at)).all()
            intents = session.scalars(select(PaymentIntent).where(PaymentIntent.invoice_id == invoice.id).order_by(PaymentIntent.created_at.desc())).all()
            return {"invoice": invoice_view(invoice), "lines": [as_dict(line) for line in lines], "receipts": receipt_views(session, receipts),
                    "attempts": [intent_view(session, intent) for intent in intents], "available": payments.outstanding(session, invoice)}

    @app.post(f"{p}/invoices/{{invoice_id}}/payment-intents", response_model=IntentOut, status_code=201, tags=["Payments"])
    def start_payment(invoice_id: str, payload: PaymentStart, actor: Actor = Depends(current_actor)):
        """Starts a mobile-money collection. Idempotent per idempotency_key; the outcome arrives by signed provider callback."""
        actor.require(*READ, "finance:self")
        if gateway is None:
            raise DomainError("The mobile-money gateway is not configured.", 503)
        msisdn = payments.normalize_msisdn(payload.msisdn)
        with scoped(actor) as session:
            intent, created = payments.start_payment(session, actor.tenant_id, invoice_id, actor.user_id, actor.can("finance:write"),
                                                     payload.provider, msisdn, payload.amount, payload.idempotency_key)
            view = intent_view(session, intent)
        if created:
            try:
                gateway.request_to_pay(actor.tenant_id, intent, msisdn)
            except Exception as error:  # noqa: BLE001 - any provider failure fails this attempt, never the invoice
                with scoped(actor) as session:
                    failed = fetch(session, PaymentIntent, intent.id, "Payment")
                    failed.status, failed.failure_reason, failed.completed_at = "failed", "The provider could not be reached. Try again.", utcnow()
                    view = intent_view(session, failed)
                raise DomainError("The mobile-money provider is unavailable. No money was taken; please try again.", 503) from error
        return view

    @app.get(f"{p}/payment-intents/{{intent_id}}", response_model=IntentOut, tags=["Payments"])
    def payment_status(intent_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            intent = fetch(session, PaymentIntent, intent_id, "Payment")
            own_invoice(session, actor, intent.invoice_id)
            return intent_view(session, intent)

    @app.post(f"{p}/payment-webhooks/simulated/{{tenant_id}}", tags=["Payments"])
    async def provider_callback(tenant_id: str, request: Request, x_timestamp: str | None = Header(None),
                                x_signature: str | None = Header(None)) -> dict[str, Any]:
        """Provider callback: authenticated by HMAC-SHA256 signature and timestamp, not by a user session."""
        if not re.fullmatch(TENANT_PATTERN, tenant_id):
            raise DomainError("Unknown payment reference.", 404)
        body = await request.body()
        if len(body) > 8192:
            raise DomainError("Callback too large.", 400)
        return payments.handle_callback(database, settings.webhook_secret, tenant_id, x_timestamp, x_signature, body, int(time.time()))

    @app.post(f"{p}/invoices/{{invoice_id}}/payments", status_code=201, tags=["Payments"])
    def manual_payment(invoice_id: str, payload: ManualPayment, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("finance:write")
        with scoped(actor) as session:
            invoice = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
            if invoice is None:
                raise DomainError("Invoice not found.", 404)
            if payload.amount > payments.outstanding(session, invoice):
                raise DomainError("Amount exceeds the balance available (including payments in progress).", 409)
            payment, receipt = payments.apply_payment(session, actor.tenant_id, invoice, payload.amount, payload.method, payload.reference,
                                                      actor.user_id)
            return {"payment": as_dict(payment), "receipt": receipt_views(session, [receipt])[0], "invoice": invoice_view(invoice)}

    # ---------- Receipts ----------
    @app.get(f"{p}/receipts", response_model=Page[ReceiptOut], tags=["Receipts"])
    def list_receipts(page: int = 1, size: int = 25, actor: Actor = Depends(current_actor)):
        actor.require(*READ, "finance:self")
        with scoped(actor) as session:
            query = select(Receipt).order_by(Receipt.issued_at.desc())
            if not actor.can(*READ):
                query = query.join(Invoice, Invoice.id == Receipt.invoice_id).where(Invoice.student_user_id == actor.user_id)
            result = paginate(session, query, page, size, serialize=lambda row: row)
            result["items"] = receipt_views(session, result["items"])
            return result

    @app.get(f"{p}/receipts/{{receipt_id}}.pdf", tags=["Receipts"], response_class=Response)
    def receipt_pdf(receipt_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            receipt = fetch(session, Receipt, receipt_id, "Receipt")
            invoice = own_invoice(session, actor, receipt.invoice_id)
            content = reports.receipt_pdf(actor.tenant_name or "Campus ERP", receipt, session.get(Payment, receipt.payment_id), invoice)
            return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{receipt.number}.pdf"'})

    # ---------- Expenses ----------
    @app.get(f"{p}/expenses", response_model=Page[ExpenseOut], tags=["Expenses"])
    def list_expenses(status: str = "", category: str = "", q: str = "", page: int = 1, size: int = 25, actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Expense).order_by(Expense.expense_date.desc(), Expense.created_at.desc())
            if status:
                query = query.where(Expense.status == status)
            if category:
                query = query.where(Expense.category == category)
            if q:
                query = query.where(or_(Expense.vendor.ilike(f"%{q}%"), Expense.description.ilike(f"%{q}%")))
            return paginate(session, query, page, size)

    @app.post(f"{p}/expenses", response_model=ExpenseOut, status_code=201, tags=["Expenses"])
    def create_expense(payload: ExpenseIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            expense = marketing.submit_expense(session, actor.tenant_id, actor.user_id, **payload.model_dump())
            session.flush()
            return as_dict(expense)

    @app.post(f"{p}/expenses/{{expense_id}}/approve", response_model=ExpenseOut, tags=["Expenses"])
    def approve(expense_id: str, payload: NoteIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            return as_dict(marketing.approve_expense(fetch(session, Expense, expense_id, "Expense"), actor.user_id, payload.note))

    @app.post(f"{p}/expenses/{{expense_id}}/reject", response_model=ExpenseOut, tags=["Expenses"])
    def reject(expense_id: str, payload: NoteIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        if len(payload.note) < 3:
            raise DomainError("Give a reason for rejecting the expense.", 422)
        with scoped(actor) as session:
            return as_dict(marketing.reject_expense(fetch(session, Expense, expense_id, "Expense"), actor.user_id, payload.note))

    @app.post(f"{p}/expenses/{{expense_id}}/pay", response_model=ExpenseOut, tags=["Expenses"])
    def pay(expense_id: str, payload: PayIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            return as_dict(marketing.pay_expense(session, actor.tenant_id, fetch(session, Expense, expense_id, "Expense"), payload.reference))

    # ---------- Marketing ----------
    @app.get(f"{p}/campaigns", tags=["Marketing"])
    def list_campaigns(actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        actor.require(*READ)
        with scoped(actor) as session:
            rows = session.scalars(select(Campaign).order_by(Campaign.starts_on.desc())).all()
            metrics = {row["campaign_id"]: row for row in marketing.campaign_metrics(session, list(rows))}
            return [{**as_dict(row), **metrics[row.id]} for row in rows]

    @app.post(f"{p}/campaigns", status_code=201, tags=["Marketing"])
    def create_campaign(payload: CampaignIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("finance:write")
        if payload.ends_on < payload.starts_on:
            raise DomainError("The campaign must end after it starts.", 422)
        with scoped(actor) as session:
            status = "active" if payload.starts_on <= local_now().date() <= payload.ends_on else "planned"
            campaign = Campaign(id=new_id("cmp"), tenant_id=actor.tenant_id, status=status, created_at=utcnow(), **payload.model_dump())
            session.add(campaign)
            session.flush()
            return {**as_dict(campaign), **marketing.campaign_metrics(session, [campaign])[0]}

    @app.patch(f"{p}/campaigns/{{campaign_id}}", tags=["Marketing"])
    def update_campaign(campaign_id: str, payload: CampaignPatch, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("finance:write")
        with scoped(actor) as session:
            campaign = fetch(session, Campaign, campaign_id, "Campaign")
            campaign.status = payload.status
            return as_dict(campaign)

    @app.get(f"{p}/campaigns/{{campaign_id}}/leads", response_model=list[LeadOut], tags=["Marketing"])
    def list_leads(campaign_id: str, stage: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            fetch(session, Campaign, campaign_id, "Campaign")
            query = select(Lead).where(Lead.campaign_id == campaign_id).order_by(Lead.created_at.desc())
            if stage:
                query = query.where(Lead.stage == stage)
            return [as_dict(row) for row in session.scalars(query).all()]

    @app.post(f"{p}/campaigns/{{campaign_id}}/leads", response_model=LeadOut, status_code=201, tags=["Marketing"])
    def create_lead(campaign_id: str, payload: LeadIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            fetch(session, Campaign, campaign_id, "Campaign")
            lead = Lead(id=new_id("led"), tenant_id=actor.tenant_id, campaign_id=campaign_id, stage="new", created_at=utcnow(),
                        **{**payload.model_dump(), "phone": payments.normalize_msisdn(payload.phone)})
            session.add(lead)
            session.flush()
            return as_dict(lead)

    @app.patch(f"{p}/leads/{{lead_id}}", response_model=LeadOut, tags=["Marketing"])
    def update_lead(lead_id: str, payload: LeadPatch, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            lead = fetch(session, Lead, lead_id, "Lead")
            if payload.stage:
                marketing.move_lead(lead, payload.stage)
            if payload.notes is not None:
                lead.notes = payload.notes
            return as_dict(lead)

    @app.post(f"{p}/leads/{{lead_id}}/convert", response_model=LeadOut, tags=["Marketing"])
    def convert(lead_id: str, payload: ConvertIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        with scoped(actor) as session:
            return as_dict(marketing.convert_lead(session, fetch(session, Lead, lead_id, "Lead"), payload.student_id))

    @app.get(f"{p}/students", tags=["Marketing"])
    def billed_students(q: str = "", actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        """Students known to Finance through invoices (used to attribute campaign conversions)."""
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Invoice.student_id, Invoice.student_name, Invoice.student_no).distinct().order_by(Invoice.student_name).limit(20)
            if q:
                query = query.where(or_(Invoice.student_name.ilike(f"%{q}%"), Invoice.student_no.ilike(f"%{q}%")))
            return [{"student_id": sid, "name": name, "student_no": number} for sid, name, number in session.execute(query).all()]

    # ---------- Reports and ledger ----------
    @app.get(f"{p}/reports/monthly", response_model=list[ReportOut], tags=["Reports"])
    def list_reports(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            return [as_dict(row) for row in session.scalars(select(MonthlyReport).order_by(MonthlyReport.period.desc(), MonthlyReport.version.desc())).all()]

    @app.post(f"{p}/reports/monthly", response_model=ReportOut, status_code=201, tags=["Reports"])
    def regenerate(payload: ReportIn, actor: Actor = Depends(current_actor)):
        actor.require("finance:write")
        if payload.period >= local_now().strftime("%Y-%m"):
            raise DomainError("Only closed months can be reported.", 422)
        with scoped(actor) as session:
            return as_dict(reports.generate_report(session, actor.tenant_id, payload.period, "manual", actor.user_id))

    @app.get(f"{p}/reports/monthly/{{report_id}}.pdf", tags=["Reports"], response_class=Response)
    def report_pdf(report_id: str, actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            report = fetch(session, MonthlyReport, report_id, "Report")
            return Response(reports.report_pdf(actor.tenant_name or "Campus ERP", report), media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="financial-summary-{report.period}-v{report.version}.pdf"'})

    @app.get(f"{p}/ledger/trial-balance", tags=["Ledger"])
    def ledger_balance(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            return trial_balance(session)

    @app.get(f"{p}/ledger/entries", tags=["Ledger"])
    def ledger_entries(page: int = 1, size: int = 25, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            result = paginate(session, select(JournalEntry).order_by(JournalEntry.created_at.desc()), page, size, serialize=lambda row: row)
            ids = [row.id for row in result["items"]]
            lines: dict[str, list[dict]] = {}
            for line in session.scalars(select(JournalLine).where(JournalLine.entry_id.in_(ids))).all() if ids else []:
                lines.setdefault(line.entry_id, []).append({**as_dict(line), "account_name": ACCOUNTS[line.account_code][0]})
            result["items"] = [{**as_dict(row), "lines": lines.get(row.id, [])} for row in result["items"]]
            return result

    @app.get(f"{p}/dashboard", tags=["Dashboard"])
    def finance_dashboard(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            data = reports.dashboard(session)
            data["billing_issues"] = session.scalar(select(func.count()).select_from(BillingIssue).where(BillingIssue.status == "open")) or 0
            data["ledger_balanced"] = trial_balance(session)["balanced"]
            return data

    @app.get(f"{p}/me/summary", tags=["Self service"])
    def my_summary(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("finance:self")
        with scoped(actor) as session:
            invoices = session.scalars(select(Invoice).where(Invoice.student_user_id == actor.user_id).order_by(Invoice.issued_at.desc())).all()
            receipts = session.scalars(select(Receipt).where(Receipt.invoice_id.in_([row.id for row in invoices])).order_by(Receipt.issued_at.desc())
                                       .limit(10)).all() if invoices else []
            return {"invoices": [invoice_view(row) for row in invoices], "receipts": receipt_views(session, list(receipts)),
                    "balance": sum(row.total - row.paid for row in invoices if row.status in ("issued", "partially_paid")),
                    "categories": sorted(EXPENSE_ACCOUNTS)}

    return app


def application():
    return create_app(load_settings("finance"))
