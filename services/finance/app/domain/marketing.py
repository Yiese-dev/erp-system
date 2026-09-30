from datetime import date, datetime

from sqlalchemy import select

from packages.campus_common.database import LOCAL_TZ, fetch, new_id, utcnow
from packages.campus_common.errors import DomainError
from services.finance.app.domain.ledger import EXPENSE_ACCOUNTS, post_entry
from services.finance.app.models import Campaign, Expense, Invoice, Lead, Payment

LEAD_STAGES = ("new", "contacted", "qualified", "applied", "converted", "lost")
OPEN_STAGES = ("new", "contacted", "qualified", "applied")


def submit_expense(session, tenant_id: str, user_id: str, category: str, description: str, vendor: str, amount: int,
                   expense_date: date, campaign_id: str | None) -> Expense:
    if category not in EXPENSE_ACCOUNTS:
        raise DomainError("Unknown expense category.", 422)
    if campaign_id:
        fetch(session, Campaign, campaign_id, "Campaign")
    expense = Expense(id=new_id("exp"), tenant_id=tenant_id, category=category, description=description, vendor=vendor, amount=amount,
                      expense_date=expense_date, status="submitted", campaign_id=campaign_id or None, submitted_by=user_id,
                      created_at=utcnow())
    session.add(expense)
    return expense


def approve_expense(expense: Expense, user_id: str, note: str = "") -> Expense:
    if expense.status != "submitted":
        raise DomainError(f"Only submitted expenses can be approved (this one is {expense.status}).", 409)
    if expense.submitted_by == user_id:
        raise DomainError("Segregation of duties: you cannot approve an expense you submitted.", 403)
    expense.status, expense.approved_by, expense.decision_note = "approved", user_id, note or None
    return expense


def reject_expense(expense: Expense, user_id: str, note: str) -> Expense:
    if expense.status not in ("submitted", "approved"):
        raise DomainError("Only unpaid expenses can be rejected.", 409)
    expense.status, expense.approved_by, expense.decision_note = "rejected", user_id, note
    return expense


def pay_expense(session, tenant_id: str, expense: Expense, reference: str, paid_at: datetime | None = None) -> Expense:
    if expense.status != "approved":
        raise DomainError("Only approved expenses can be paid.", 409)
    when = paid_at or utcnow()
    post_entry(session, tenant_id, when.astimezone(LOCAL_TZ).date(), f"{expense.vendor}: {expense.description}", "expense", expense.id,
               [(EXPENSE_ACCOUNTS[expense.category], expense.amount, 0), ("1010", 0, expense.amount)])
    expense.status, expense.paid_at, expense.reference = "paid", when, reference
    return expense


def move_lead(lead: Lead, stage: str) -> Lead:
    if stage not in LEAD_STAGES or stage == "converted":
        raise DomainError("Use the convert action to mark a lead as enrolled.", 422)
    if lead.stage in ("converted", "lost") and stage != lead.stage:
        raise DomainError(f"The lead is already {lead.stage}.", 409)
    lead.stage = stage
    return lead


def convert_lead(session, lead: Lead, student_id: str) -> Lead:
    if lead.stage in ("converted", "lost"):
        raise DomainError(f"The lead is already {lead.stage}.", 409)
    if not session.scalar(select(Invoice.id).where(Invoice.student_id == student_id).limit(1)):
        raise DomainError("Link the lead to a student who has been registered and invoiced.", 422)
    if session.scalar(select(Lead.id).where(Lead.student_id == student_id, Lead.stage == "converted")):
        raise DomainError("That student is already attributed to another converted lead.", 409)
    lead.stage, lead.student_id, lead.converted_at = "converted", student_id, utcnow()
    return lead


def campaign_metrics(session, campaigns: list[Campaign]) -> list[dict]:
    """ROI = (collected tuition from converted students after conversion - paid campaign spend) / spend x 100."""
    if not campaigns:
        return []
    ids = [campaign.id for campaign in campaigns]
    leads = session.scalars(select(Lead).where(Lead.campaign_id.in_(ids))).all()
    spend: dict[str, int] = {}
    for expense in session.scalars(select(Expense).where(Expense.campaign_id.in_(ids), Expense.status == "paid")).all():
        spend[expense.campaign_id] = spend.get(expense.campaign_id, 0) + expense.amount
    converted = [lead for lead in leads if lead.stage == "converted" and lead.student_id]
    payments: dict[str, list[tuple[datetime, int]]] = {}
    if converted:
        for student_id, paid_at, amount in session.execute(select(Invoice.student_id, Payment.paid_at, Payment.amount)
                                                           .join(Payment, Payment.invoice_id == Invoice.id)
                                                           .where(Invoice.student_id.in_({lead.student_id for lead in converted}))).all():
            payments.setdefault(student_id, []).append((paid_at, amount))
    results = []
    for campaign in campaigns:
        own = [lead for lead in leads if lead.campaign_id == campaign.id]
        wins = [lead for lead in own if lead.stage == "converted"]
        revenue = sum(amount for lead in wins for paid_at, amount in payments.get(lead.student_id or "", []) if paid_at >= lead.converted_at)
        cost = spend.get(campaign.id, 0)
        stages = {stage: sum(lead.stage == stage for lead in own) for stage in LEAD_STAGES}
        results.append({"campaign_id": campaign.id, "name": campaign.name, "channel": campaign.channel, "status": campaign.status,
                        "budget": campaign.budget, "spend": cost, "leads": len(own), "conversions": len(wins),
                        "conversion_rate": round(len(wins) / len(own), 4) if own else None, "revenue": revenue,
                        "roi_percent": round((revenue - cost) / cost * 100, 1) if cost else None,
                        "cost_per_conversion": round(cost / len(wins)) if wins and cost else None, "stages": stages})
    return results
