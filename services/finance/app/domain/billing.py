from datetime import datetime, timedelta

from sqlalchemy import select

from packages.campus_common.database import LOCAL_TZ, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.events import PermanentEventError, record_event
from services.finance.app.domain.ledger import post_entry
from services.finance.app.models import (BillingIssue, Counter, FeePlan, Invoice, InvoiceLine, KnownTenant, OutboxEvent,
                                         ProcessedEvent)

ENROLLMENT_CONFIRMED = "academic.enrollment.confirmed.v1"
INVOICE_CREATED = "finance.invoice.created.v1"
INVOICE_SETTLED = "finance.invoice.settled.v1"
BILLING_ISSUE = "finance.billing.issue.v1"
REQUIRED = ("registration_id", "student_id", "student_name", "program_id", "program_name", "term_id", "term_name")


class FeePlanMissing(DomainError):
    pass


def next_number(session, tenant_id: str, name: str, prefix: str, year: int) -> str:
    key = f"{tenant_id}:{name}:{year}"
    counter = session.scalar(select(Counter).where(Counter.id == key).with_for_update())
    if counter is None:
        counter = Counter(id=key, tenant_id=tenant_id, value=0)
        session.add(counter)
    counter.value += 1
    session.flush()
    return f"{prefix}-{year}-{counter.value:05d}"


def remember_tenant(session, tenant_id: str, name: str | None = None, first_period: str | None = None) -> KnownTenant:
    tenant = session.get(KnownTenant, tenant_id)
    if tenant is None:
        tenant = KnownTenant(id=tenant_id, name=name or tenant_id, first_period=first_period or local_now().strftime("%Y-%m"))
        session.add(tenant)
    elif name:
        tenant.name = name
    return tenant


def status_event(session, tenant_id: str, invoice: Invoice, correlation_id: str | None = None) -> None:
    kind = INVOICE_SETTLED if invoice.status == "paid" else INVOICE_CREATED
    record_event(session, OutboxEvent, tenant_id, kind, {"registration_id": invoice.registration_id, "invoice_id": invoice.id,
                                                         "invoice_number": invoice.number, "total": invoice.total,
                                                         "paid": invoice.paid, "due_on": invoice.due_on.isoformat()}, correlation_id)


def create_invoice(session, tenant_id: str, data: dict, source: str = "event", issued_at: datetime | None = None,
                   correlation_id: str | None = None) -> tuple[Invoice, bool]:
    """Idempotent by business key: one invoice per programme/term registration, priced from a snapshot of the fee plan."""
    existing = session.scalar(select(Invoice).where(Invoice.registration_id == data["registration_id"]))
    if existing is not None:
        return existing, False
    plan = session.scalar(select(FeePlan).where(FeePlan.program_id == data["program_id"], FeePlan.term_id == data["term_id"],
                                                FeePlan.active.is_(True)))
    if plan is None:
        raise FeePlanMissing(f"No active fee plan for {data['program_name']} in {data['term_name']}.", 409)
    issued = issued_at or utcnow()
    issued_on = issued.astimezone(LOCAL_TZ).date()
    number = next_number(session, tenant_id, "invoice", "INV", issued_on.year)
    invoice = Invoice(id=new_id("inv"), tenant_id=tenant_id, number=number, registration_id=data["registration_id"],
                      student_id=data["student_id"], student_user_id=data.get("student_user_id"), student_name=data["student_name"],
                      student_no=data.get("student_no") or "", program_id=data["program_id"], program_name=data["program_name"],
                      term_id=data["term_id"], term_name=data["term_name"], total=plan.amount, paid=0, status="issued", source=source,
                      issued_at=issued, due_on=issued_on + timedelta(days=plan.due_days),
                      fee_snapshot={"fee_plan_id": plan.id, "amount": plan.amount, "due_days": plan.due_days,
                                    "courses": data.get("courses", []), "captured_at": issued.isoformat()})
    session.add(invoice)
    session.flush()
    session.add(InvoiceLine(id=new_id("inl"), tenant_id=tenant_id, invoice_id=invoice.id,
                            description=f"Tuition - {data['program_name']}, {data['term_name']}", amount=plan.amount))
    post_entry(session, tenant_id, issued_on, f"Tuition invoice {number}", "invoice", invoice.id,
               [("1200", plan.amount, 0), ("4000", 0, plan.amount)])
    status_event(session, tenant_id, invoice, correlation_id)
    return invoice, True


def open_issue(session, tenant_id: str, event_id: str, data: dict, reason: str) -> BillingIssue:
    issue = session.scalar(select(BillingIssue).where(BillingIssue.registration_id == data["registration_id"]))
    if issue is None:
        issue = BillingIssue(id=new_id("bil"), tenant_id=tenant_id, registration_id=data["registration_id"], event_id=event_id,
                             reason=reason, payload=data, status="open", attempts=1, created_at=utcnow())
        session.add(issue)
    else:
        issue.status, issue.reason, issue.attempts, issue.payload = "open", reason, issue.attempts + 1, data
    record_event(session, OutboxEvent, tenant_id, BILLING_ISSUE, {"registration_id": data["registration_id"], "reason": reason})
    return issue


def resolve_issue(session, registration_id: str) -> None:
    issue = session.scalar(select(BillingIssue).where(BillingIssue.registration_id == registration_id, BillingIssue.status == "open"))
    if issue is not None:
        issue.status, issue.resolved_at = "resolved", utcnow()


def handle_enrollment_event(database, event: dict) -> str:
    data = event["data"]
    if any(not isinstance(data.get(key), str) or not data.get(key) for key in REQUIRED):
        raise PermanentEventError("Enrollment event is missing required fields.")
    tenant_id = event["tenant_id"]
    with database.session(tenant_id) as session:
        if session.get(ProcessedEvent, event["event_id"]):
            return "duplicate"
        remember_tenant(session, tenant_id)
        try:
            invoice, created = create_invoice(session, tenant_id, data, "event", correlation_id=event["correlation_id"])
            if not created:
                status_event(session, tenant_id, invoice, event["correlation_id"])
            resolve_issue(session, data["registration_id"])
            outcome = "invoiced" if created else "existing"
        except FeePlanMissing as error:
            open_issue(session, tenant_id, event["event_id"], data, error.message)
            outcome = "issue"
        session.add(ProcessedEvent(event_id=event["event_id"], event_type=event["event_type"], tenant_id=tenant_id, processed_at=utcnow()))
    return outcome


def retry_issue(session, tenant_id: str, issue: BillingIssue) -> Invoice:
    if issue.status != "open":
        raise DomainError("This billing issue is already resolved.", 409)
    try:
        invoice, _ = create_invoice(session, tenant_id, issue.payload, "event")
    except FeePlanMissing as error:
        issue.attempts += 1
        raise DomainError(f"{error.message} Create the fee plan, then retry.", 409) from error
    issue.status, issue.resolved_at = "resolved", utcnow()
    return invoice


def retry_issues_for_plan(session, tenant_id: str, plan: FeePlan) -> int:
    resolved = 0
    for issue in session.scalars(select(BillingIssue).where(BillingIssue.status == "open")).all():
        if issue.payload.get("program_id") == plan.program_id and issue.payload.get("term_id") == plan.term_id:
            retry_issue(session, tenant_id, issue)
            resolved += 1
    return resolved
