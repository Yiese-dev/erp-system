from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.campus_common.database import LOCAL_TZ, local_now, new_id, utcnow
from packages.campus_common.pdf import money, render_pdf
from services.finance.app.domain.ledger import ACCOUNTS, EXPENSE_ACCOUNTS
from services.finance.app.domain.marketing import campaign_metrics
from services.finance.app.domain.payments import MANUAL_METHODS, PROVIDERS
from services.finance.app.models import Campaign, Expense, Invoice, KnownTenant, Lead, MonthlyReport, Payment, Receipt

METHOD_LABELS = {**PROVIDERS, **MANUAL_METHODS}


def month_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1, tzinfo=LOCAL_TZ)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=LOCAL_TZ)
    return start, end


def periods_between(first: str, last_exclusive: str) -> list[str]:
    year, month = map(int, first.split("-"))
    periods = []
    while f"{year:04d}-{month:02d}" < last_exclusive:
        periods.append(f"{year:04d}-{month:02d}")
        year, month = year + (month == 12), month % 12 + 1
    return periods


def recent_periods(today: date, count: int) -> list[str]:
    year, month = today.year, today.month
    periods = []
    for _ in range(count):
        periods.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return periods[::-1]


def monthly_summary(session, period: str) -> dict:
    start, end = month_bounds(period)
    invoices = session.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0))
                               .where(Invoice.issued_at >= start, Invoice.issued_at < end)).one()
    by_method: dict[str, int] = defaultdict(int)
    payments = 0
    for method, amount in session.execute(select(Payment.method, Payment.amount).where(Payment.paid_at >= start, Payment.paid_at < end)).all():
        by_method[method] += amount
        payments += 1
    by_category: dict[str, int] = defaultdict(int)
    for category, amount in session.execute(select(Expense.category, Expense.amount)
                                            .where(Expense.status == "paid", Expense.paid_at >= start, Expense.paid_at < end)).all():
        by_category[category] += amount
    billed_to_date = session.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.issued_at < end)) or 0
    collected_to_date = session.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.paid_at < end)) or 0
    collected, spent = sum(by_method.values()), sum(by_category.values())
    campaigns = []
    for row in campaign_metrics(session, session.scalars(select(Campaign).where(Campaign.starts_on < end.date(),
                                                                              Campaign.ends_on >= start.date())).all()):
        leads = session.scalar(select(func.count()).select_from(Lead).where(Lead.campaign_id == row["campaign_id"],
                                                                            Lead.created_at >= start, Lead.created_at < end)) or 0
        won = session.scalar(select(func.count()).select_from(Lead).where(Lead.campaign_id == row["campaign_id"],
                                                                          Lead.converted_at >= start, Lead.converted_at < end)) or 0
        campaigns.append({"name": row["name"], "channel": row["channel"], "new_leads": leads, "conversions": won,
                          "spend_to_date": row["spend"], "roi_percent": row["roi_percent"]})
    return {"period": period, "currency": "XAF", "invoices_issued": invoices[0], "billed": int(invoices[1]),
            "payments_received": payments, "collected": collected, "collections_by_method": dict(by_method),
            "expenses_paid": spent, "expenses_by_category": dict(by_category), "net_cash_flow": collected - spent,
            "receivables_at_month_end": int(billed_to_date - collected_to_date), "campaigns": campaigns}


def generate_report(session, tenant_id: str, period: str, trigger: str, user_id: str) -> MonthlyReport:
    version = (session.scalar(select(func.max(MonthlyReport.version)).where(MonthlyReport.period == period)) or 0) + 1
    report = MonthlyReport(id=new_id("mrp"), tenant_id=tenant_id, period=period, version=version, trigger=trigger, generated_by=user_id,
                           generated_at=utcnow(), summary=monthly_summary(session, period))
    session.add(report)
    session.flush()
    return report


def run_monthly_schedule(database, today: date | None = None) -> list[tuple[str, str]]:
    """Catch-up scheduler: every closed month without a report gets exactly one version-1 report per institution."""
    current = (today or local_now().date()).strftime("%Y-%m")
    with database.session() as session:
        tenants = [(tenant.id, tenant.first_period) for tenant in session.scalars(select(KnownTenant)).all()]
    generated = []
    for tenant_id, first in tenants:
        for period in periods_between(first, current):
            try:
                with database.session(tenant_id) as session:
                    if session.scalar(select(MonthlyReport.id).where(MonthlyReport.period == period).limit(1)):
                        continue
                    generate_report(session, tenant_id, period, "scheduled", "system:scheduler")
                    generated.append((tenant_id, period))
            except IntegrityError:
                continue
    return generated


def report_pdf(institution: str, report: MonthlyReport) -> bytes:
    data = report.summary
    label = datetime.strptime(data["period"], "%Y-%m").strftime("%B %Y")
    blocks = [("kv", [("Tuition billed", money(data["billed"])), ("Invoices issued", data["invoices_issued"]),
                      ("Collections received", money(data["collected"])), ("Payments", data["payments_received"]),
                      ("Operating expenses paid", money(data["expenses_paid"])), ("Net cash flow", money(data["net_cash_flow"])),
                      ("Receivables at month end", money(data["receivables_at_month_end"]))]),
              ("heading", "Collections by channel"),
              ("table", ["Channel", "Amount"], [[METHOD_LABELS.get(key, key), money(value)] for key, value in data["collections_by_method"].items()]),
              ("heading", "Expenses by category"),
              ("table", ["Category", "Ledger account", "Amount"],
               [[key.replace("_", " ").title(), ACCOUNTS[EXPENSE_ACCOUNTS[key]][0], money(value)] for key, value in data["expenses_by_category"].items()]),
              ("heading", "Marketing campaigns active this month"),
              ("table", ["Campaign", "Channel", "New leads", "Conversions", "Spend to date", "ROI"],
               [[row["name"], row["channel"], row["new_leads"], row["conversions"], money(row["spend_to_date"]),
                 "n/a" if row["roi_percent"] is None else f"{row['roi_percent']:.1f}%"] for row in data["campaigns"]]),
              ("text", f"Version {report.version} ({report.trigger}). All amounts in FCFA (XAF). Cash-basis collections and expenses; "
                       "billed revenue is recognised when a term registration is invoiced.")]
    return render_pdf(f"Monthly Financial Summary - {label}", institution, f"Reporting period {data['period']} (Africa/Douala)", blocks,
                      report.generated_at)


def receipt_pdf(institution: str, receipt: Receipt, payment: Payment, invoice: Invoice) -> bytes:
    blocks = [("kv", [("Receipt number", receipt.number), ("Date", payment.paid_at.astimezone(LOCAL_TZ).strftime("%d %B %Y, %H:%M")),
                      ("Received from", f"{invoice.student_name} ({invoice.student_no})"), ("For", f"{invoice.program_name} - {invoice.term_name}"),
                      ("Invoice", invoice.number), ("Amount received", money(payment.amount)),
                      ("Payment channel", METHOD_LABELS.get(payment.method, payment.method)), ("Transaction reference", payment.reference),
                      ("Invoice total", money(invoice.total)), ("Balance remaining", money(invoice.total - invoice.paid))]),
              ("text", "This digital receipt was generated automatically when the payment was confirmed and posted to the ledger.")]
    return render_pdf("Payment Receipt", institution, f"Receipt {receipt.number}", blocks, receipt.issued_at)


def dashboard(session, months: int = 9) -> dict:
    today = local_now().date()
    periods = recent_periods(today, months)
    series = {period: {"period": period, "billed": 0, "collected": 0, "expenses": 0} for period in periods}
    start, _ = month_bounds(periods[0])

    def bucket(value: datetime) -> str:
        return value.astimezone(LOCAL_TZ).strftime("%Y-%m")

    for issued_at, total in session.execute(select(Invoice.issued_at, Invoice.total).where(Invoice.issued_at >= start)).all():
        if bucket(issued_at) in series:
            series[bucket(issued_at)]["billed"] += total
    for paid_at, amount in session.execute(select(Payment.paid_at, Payment.amount).where(Payment.paid_at >= start)).all():
        if bucket(paid_at) in series:
            series[bucket(paid_at)]["collected"] += amount
    for paid_at, amount in session.execute(select(Expense.paid_at, Expense.amount).where(Expense.status == "paid", Expense.paid_at >= start)).all():
        if bucket(paid_at) in series:
            series[bucket(paid_at)]["expenses"] += amount
    billed = session.scalar(select(func.coalesce(func.sum(Invoice.total), 0))) or 0
    collected = session.scalar(select(func.coalesce(func.sum(Payment.amount), 0))) or 0
    year_start = datetime(today.year, 1, 1, tzinfo=LOCAL_TZ)
    expenses_ytd = session.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.status == "paid", Expense.paid_at >= year_start)) or 0
    collected_ytd = session.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.paid_at >= year_start)) or 0
    statuses = dict(session.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    methods = dict(session.execute(select(Payment.method, func.sum(Payment.amount)).group_by(Payment.method)).all())
    overdue = session.scalars(select(Invoice).where(Invoice.status.in_(("issued", "partially_paid")), Invoice.due_on < today)
                              .order_by(Invoice.due_on).limit(8)).all()
    overdue_total = session.scalar(select(func.coalesce(func.sum(Invoice.total - Invoice.paid), 0))
                                   .where(Invoice.status.in_(("issued", "partially_paid")), Invoice.due_on < today)) or 0
    pending_expenses = session.scalar(select(func.count()).select_from(Expense).where(Expense.status.in_(("submitted", "approved")))) or 0
    return {"totals": {"billed": int(billed), "collected": int(collected), "outstanding": int(billed - collected),
                       "collection_rate": round(collected / billed, 4) if billed else None, "overdue": int(overdue_total),
                       "collected_ytd": int(collected_ytd), "expenses_ytd": int(expenses_ytd), "net_cash_ytd": int(collected_ytd - expenses_ytd),
                       "pending_expenses": pending_expenses},
            "monthly": list(series.values()), "invoice_status": statuses,
            "collections_by_method": [{"method": key, "label": METHOD_LABELS.get(key, key), "amount": int(value)} for key, value in methods.items()],
            "overdue": [{"id": row.id, "number": row.number, "student_name": row.student_name, "due_on": row.due_on.isoformat(),
                         "balance": row.total - row.paid} for row in overdue],
            "campaigns": campaign_metrics(session, session.scalars(select(Campaign).order_by(Campaign.starts_on.desc())).all())}
