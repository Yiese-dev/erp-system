from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, Index, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from packages.campus_common.database import NAMING, TenantRow, UTCDateTime, tenant_args
from packages.campus_common.events import event_tables


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class KnownTenant(Base):
    """Infrastructure table (no RLS) so schedulers can iterate institutions before setting tenant context."""
    __tablename__ = "known_tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    first_period: Mapped[str] = mapped_column(String(7))


class Counter(TenantRow, Base):
    __tablename__ = "counters"
    __table_args__ = tenant_args()
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class FeePlan(TenantRow, Base):
    __tablename__ = "fee_plans"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "program_id", "term_id"), CheckConstraint("amount > 0", name="positive"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(64))
    program_name: Mapped[str] = mapped_column(String(160))
    term_id: Mapped[str] = mapped_column(String(64))
    term_name: Mapped[str] = mapped_column(String(60))
    amount: Mapped[int] = mapped_column(BigInteger)
    due_days: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Invoice(TenantRow, Base):
    __tablename__ = "invoices"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "registration_id"), UniqueConstraint("tenant_id", "number"),
                                 CheckConstraint("paid >= 0 AND paid <= total", name="paid_within_total"),
                                 Index("ix_invoices_tenant_status_due", "tenant_id", "status", "due_on"),
                                 Index("ix_invoices_tenant_student_user", "tenant_id", "student_user_id"),
                                 Index("ix_invoices_tenant_student", "tenant_id", "student_id"),
                                 Index("ix_invoices_tenant_issued", "tenant_id", "issued_at"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(40))
    registration_id: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[str] = mapped_column(String(64))
    student_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    student_name: Mapped[str] = mapped_column(String(160))
    student_no: Mapped[str] = mapped_column(String(32), default="")
    program_id: Mapped[str] = mapped_column(String(64))
    program_name: Mapped[str] = mapped_column(String(160))
    term_id: Mapped[str] = mapped_column(String(64))
    term_name: Mapped[str] = mapped_column(String(60))
    total: Mapped[int] = mapped_column(BigInteger)
    paid: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="issued")
    source: Mapped[str] = mapped_column(String(16), default="event")
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    due_on: Mapped[date] = mapped_column(Date)
    fee_snapshot: Mapped[dict] = mapped_column(JSON)


class InvoiceLine(TenantRow, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = tenant_args(refs={"invoice_id": "invoices"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(BigInteger)


class PaymentIntent(TenantRow, Base):
    __tablename__ = "payment_intents"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "idempotency_key"), UniqueConstraint("reference"),
                                 CheckConstraint("amount > 0", name="positive"),
                                 Index("ix_payment_intents_tenant_status", "tenant_id", "status", "created_at"),
                                 refs={"invoice_id": "invoices"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    msisdn_masked: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="XAF")
    status: Mapped[str] = mapped_column(String(12), default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    initiated_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ProviderEvent(TenantRow, Base):
    __tablename__ = "provider_events"
    __table_args__ = tenant_args(refs={"intent_id": "payment_intents"})
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict] = mapped_column(JSON)


class Payment(TenantRow, Base):
    __tablename__ = "payments"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "intent_id"), CheckConstraint("amount > 0", name="positive"),
                                 Index("ix_payments_tenant_paid", "tenant_id", "paid_at"),
                                 refs={"invoice_id": "invoices", "intent_id": "payment_intents"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(64), index=True)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(80))
    recorded_by: Mapped[str] = mapped_column(String(64))
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Receipt(TenantRow, Base):
    __tablename__ = "receipts"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "payment_id"),
                                 refs={"payment_id": "payments", "invoice_id": "invoices"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(40))
    payment_id: Mapped[str] = mapped_column(String(64))
    invoice_id: Mapped[str] = mapped_column(String(64), index=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)


class JournalEntry(TenantRow, Base):
    __tablename__ = "journal_entries"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "source_type", "source_id"),
                                 Index("ix_journal_entries_tenant_date", "tenant_id", "entry_date"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date)
    memo: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class JournalLine(TenantRow, Base):
    __tablename__ = "journal_lines"
    __table_args__ = tenant_args(CheckConstraint("debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0) AND debit + credit > 0",
                                                 name="one_sided"),
                                 Index("ix_journal_lines_tenant_account", "tenant_id", "account_code"),
                                 refs={"entry_id": "journal_entries"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(64), index=True)
    account_code: Mapped[str] = mapped_column(String(8))
    debit: Mapped[int] = mapped_column(BigInteger, default=0)
    credit: Mapped[int] = mapped_column(BigInteger, default=0)


class Campaign(TenantRow, Base):
    __tablename__ = "campaigns"
    __table_args__ = tenant_args(CheckConstraint("budget >= 0", name="budget_positive"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(30))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    budget: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Lead(TenantRow, Base):
    __tablename__ = "leads"
    __table_args__ = tenant_args(Index("ix_leads_tenant_campaign_stage", "tenant_id", "campaign_id", "stage"),
                                 refs={"campaign_id": "campaigns"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    program_interest: Mapped[str] = mapped_column(String(160), default="")
    stage: Mapped[str] = mapped_column(String(16), default="new")
    student_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    converted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Expense(TenantRow, Base):
    __tablename__ = "expenses"
    __table_args__ = tenant_args(CheckConstraint("amount > 0", name="positive"),
                                 Index("ix_expenses_tenant_status_date", "tenant_id", "status", "expense_date"),
                                 refs={"campaign_id": "campaigns"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(200))
    vendor: Mapped[str] = mapped_column(String(160))
    amount: Mapped[int] = mapped_column(BigInteger)
    expense_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="submitted")
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_by: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BillingIssue(TenantRow, Base):
    __tablename__ = "billing_issues"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "registration_id"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    registration_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="open")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MonthlyReport(TenantRow, Base):
    __tablename__ = "monthly_reports"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "period", "version"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[str] = mapped_column(String(7))
    version: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(12))
    generated_by: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    summary: Mapped[dict] = mapped_column(JSON)


OutboxEvent, ProcessedEvent = event_tables(Base)
