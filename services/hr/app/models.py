from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, Date, Index, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from packages.campus_common.database import NAMING, TenantRow, UTCDateTime, tenant_args


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class KnownTenant(Base):
    """Infrastructure table (no RLS) so background jobs can iterate institutions."""
    __tablename__ = "known_tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)


class Department(TenantRow, Base):
    __tablename__ = "departments"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class Employee(TenantRow, Base):
    __tablename__ = "employees"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "employee_no"), UniqueConstraint("tenant_id", "user_id"),
                                 CheckConstraint("base_salary > 0 AND allowances >= 0", name="pay_positive"),
                                 Index("ix_employees_tenant_department", "tenant_id", "department_id"),
                                 refs={"department_id": "departments"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    employee_no: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(20), default="")
    department_id: Mapped[str] = mapped_column(String(64))
    position: Mapped[str] = mapped_column(String(120))
    hired_on: Mapped[date] = mapped_column(Date)
    base_salary: Mapped[int] = mapped_column(BigInteger)
    allowances: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(12), default="active")


class Vacancy(TenantRow, Base):
    __tablename__ = "vacancies"
    __table_args__ = tenant_args(refs={"department_id": "departments"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    department_id: Mapped[str] = mapped_column(String(64))
    openings: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Applicant(TenantRow, Base):
    __tablename__ = "applicants"
    __table_args__ = tenant_args(Index("ix_applicants_tenant_vacancy_stage", "tenant_id", "vacancy_id", "stage"),
                                 refs={"vacancy_id": "vacancies", "employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vacancy_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(20), default="")
    stage: Mapped[str] = mapped_column(String(12), default="applied")
    offered_salary: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    history: Mapped[list] = mapped_column(JSON, default=list)


class RuleSet(TenantRow, Base):
    __tablename__ = "rule_sets"
    __table_args__ = tenant_args()
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    effective_from: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    rules: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PayrollRun(TenantRow, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "period"), refs={"rule_set_id": "rule_sets"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    rule_set_id: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finalized_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    totals: Mapped[dict] = mapped_column(JSON, default=dict)


class Payslip(TenantRow, Base):
    __tablename__ = "payslips"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "run_id", "employee_id"),
                                 Index("ix_payslips_tenant_employee", "tenant_id", "employee_id"),
                                 refs={"run_id": "payroll_runs", "employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64))
    employee_id: Mapped[str] = mapped_column(String(64))
    employee_name: Mapped[str] = mapped_column(String(160))
    period: Mapped[str] = mapped_column(String(7))
    gross: Mapped[int] = mapped_column(BigInteger)
    employee_deductions: Mapped[int] = mapped_column(BigInteger)
    net: Mapped[int] = mapped_column(BigInteger)
    employer_contributions: Mapped[int] = mapped_column(BigInteger)
    lines: Mapped[dict] = mapped_column(JSON)


class AttendanceChallenge(TenantRow, Base):
    __tablename__ = "attendance_challenges"
    __table_args__ = tenant_args(Index("ix_attendance_challenges_tenant_code", "tenant_id", "code"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    kiosk: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AttendanceLog(TenantRow, Base):
    __tablename__ = "attendance_logs"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "employee_id", "work_date"),
                                 Index("ix_attendance_logs_tenant_date", "tenant_id", "work_date"),
                                 refs={"employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64))
    work_date: Mapped[date] = mapped_column(Date)
    check_in_at: Mapped[datetime] = mapped_column(UTCDateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    method: Mapped[str] = mapped_column(String(12), default="qr")
    kiosk: Mapped[str] = mapped_column(String(80), default="")


class LeaveBalance(TenantRow, Base):
    __tablename__ = "leave_balances"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "employee_id", "year", "kind"),
                                 CheckConstraint("used >= 0 AND used <= entitled", name="within_entitlement"),
                                 refs={"employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64))
    year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    entitled: Mapped[int] = mapped_column(Integer)
    used: Mapped[int] = mapped_column(Integer, default=0)


class LeaveRequest(TenantRow, Base):
    __tablename__ = "leave_requests"
    __table_args__ = tenant_args(CheckConstraint("ends_on >= starts_on AND days > 0", name="valid_range"),
                                 Index("ix_leave_requests_tenant_status", "tenant_id", "status"),
                                 refs={"employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Review(TenantRow, Base):
    __tablename__ = "reviews"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "employee_id", "period"),
                                 CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="rating_range"),
                                 refs={"employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(10))
    goals: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[str] = mapped_column(Text, default="")
    reviewer_user_id: Mapped[str] = mapped_column(String(64))
    reviewer_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Asset(TenantRow, Base):
    __tablename__ = "assets"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "tag"), Index("ix_assets_tenant_status", "tenant_id", "status"),
                                 refs={"employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tag: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40))
    serial: Mapped[str] = mapped_column(String(80), default="")
    location: Mapped[str] = mapped_column(String(80))
    condition: Mapped[str] = mapped_column(String(12), default="good")
    status: Mapped[str] = mapped_column(String(12), default="available")
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchased_on: Mapped[date] = mapped_column(Date)
    value: Mapped[int] = mapped_column(BigInteger)


class AssetAssignment(TenantRow, Base):
    __tablename__ = "asset_assignments"
    __table_args__ = tenant_args(refs={"asset_id": "assets", "employee_id": "employees"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    employee_id: Mapped[str] = mapped_column(String(64))
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime)
    returned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")


class InventoryItem(TenantRow, Base):
    __tablename__ = "inventory_items"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "sku"), CheckConstraint("quantity >= 0", name="non_negative"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0)


class StockMovement(TenantRow, Base):
    __tablename__ = "stock_movements"
    __table_args__ = tenant_args(CheckConstraint("delta <> 0", name="non_zero"), refs={"item_id": "inventory_items"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    balance_after: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Notification(TenantRow, Base):
    __tablename__ = "notifications"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "dedupe_key"),
                                 Index("ix_notifications_tenant_user", "tenant_id", "recipient_user_id", "read_at"),
                                 Index("ix_notifications_tenant_email", "tenant_id", "email_status"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipient_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    link: Mapped[str] = mapped_column(String(160), default="")
    dedupe_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    email_status: Mapped[str] = mapped_column(String(10), default="pending")
    email_attempts: Mapped[int] = mapped_column(Integer, default=0)
