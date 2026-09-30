from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, Float, Index, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from packages.campus_common.database import NAMING, TenantRow, UTCDateTime, tenant_args
from packages.campus_common.events import event_tables


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Policy(TenantRow, Base):
    __tablename__ = "policies"
    __table_args__ = tenant_args()
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attendance_threshold: Mapped[float] = mapped_column(Float, default=0.75)
    failing_score: Mapped[float] = mapped_column(Float, default=50)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=2)
    appeal_window_days: Mapped[int] = mapped_column(Integer, default=14)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Program(TenantRow, Base):
    __tablename__ = "programs"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "code"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(40), default="Bachelor")
    duration_terms: Mapped[int] = mapped_column(Integer, default=6)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Course(TenantRow, Base):
    __tablename__ = "courses"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "code"), refs={"program_id": "programs"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(160))
    credits: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Prerequisite(TenantRow, Base):
    __tablename__ = "course_prerequisites"
    __table_args__ = tenant_args(CheckConstraint("course_id <> prerequisite_id", name="not_self"), keyed=False,
                                 refs={"course_id": "courses", "prerequisite_id": "courses"})
    course_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prerequisite_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class Term(TenantRow, Base):
    __tablename__ = "terms"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")


class Offering(TenantRow, Base):
    __tablename__ = "offerings"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "course_id", "term_id"),
                                 Index("ix_offerings_tenant_instructor", "tenant_id", "instructor_user_id"),
                                 refs={"course_id": "courses", "term_id": "terms"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(64))
    term_id: Mapped[str] = mapped_column(String(64))
    instructor_user_id: Mapped[str] = mapped_column(String(64))
    instructor_name: Mapped[str] = mapped_column(String(160))
    room: Mapped[str] = mapped_column(String(40))
    capacity: Mapped[int] = mapped_column(Integer, default=40)
    results_status: Mapped[str] = mapped_column(String(16), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Student(TenantRow, Base):
    __tablename__ = "students"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "student_no"), UniqueConstraint("tenant_id", "user_id"),
                                 refs={"program_id": "programs"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    student_no: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    program_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")
    admitted_on: Mapped[date] = mapped_column(Date)


class Registration(TenantRow, Base):
    __tablename__ = "registrations"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "student_id", "term_id"),
                                 refs={"student_id": "students", "term_id": "terms", "program_id": "programs"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(64))
    program_id: Mapped[str] = mapped_column(String(64))
    term_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    billing_status: Mapped[str] = mapped_column(String(16), default="pending")
    invoice_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Enrollment(TenantRow, Base):
    __tablename__ = "enrollments"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "offering_id", "student_id"),
                                 Index("ix_enrollments_tenant_student", "tenant_id", "student_id"),
                                 refs={"registration_id": "registrations", "offering_id": "offerings", "student_id": "students"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    registration_id: Mapped[str] = mapped_column(String(64))
    offering_id: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="enrolled")


class Assessment(TenantRow, Base):
    __tablename__ = "assessments"
    __table_args__ = tenant_args(CheckConstraint("weight > 0 AND weight <= 100", name="weight_range"), refs={"offering_id": "offerings"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offering_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(80))
    weight: Mapped[int] = mapped_column(Integer)
    held_on: Mapped[date] = mapped_column(Date)


class Grade(TenantRow, Base):
    __tablename__ = "grades"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "assessment_id", "student_id"),
                                 CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
                                 Index("ix_grades_tenant_student", "tenant_id", "student_id"),
                                 refs={"assessment_id": "assessments", "student_id": "students"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    recorded_by: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AttendanceSession(TenantRow, Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "offering_id", "held_on"), refs={"offering_id": "offerings"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offering_id: Mapped[str] = mapped_column(String(64))
    held_on: Mapped[date] = mapped_column(Date)
    topic: Mapped[str] = mapped_column(String(160), default="")


class AttendanceRecord(TenantRow, Base):
    __tablename__ = "attendance_records"
    __table_args__ = tenant_args(CheckConstraint("status IN ('present','late','absent','excused')", name="status_valid"),
                                 Index("ix_attendance_records_tenant_student", "tenant_id", "student_id"),
                                 keyed=False, refs={"session_id": "attendance_sessions", "student_id": "students"})
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(10))


class Exam(TenantRow, Base):
    __tablename__ = "exams"
    __table_args__ = tenant_args(CheckConstraint("ends_at > starts_at", name="positive_duration"),
                                 Index("ix_exams_tenant_window", "tenant_id", "starts_at", "ends_at"),
                                 refs={"offering_id": "offerings"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offering_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    room: Mapped[str] = mapped_column(String(40))
    invigilator_user_id: Mapped[str] = mapped_column(String(64))
    invigilator_name: Mapped[str] = mapped_column(String(160))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Result(TenantRow, Base):
    __tablename__ = "results"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "offering_id", "student_id", "revision"),
                                 Index("ix_results_tenant_student_current", "tenant_id", "student_id", "current"),
                                 refs={"offering_id": "offerings", "student_id": "students"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offering_id: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    letter: Mapped[str] = mapped_column(String(2))
    passed: Mapped[bool] = mapped_column(Boolean)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    current: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(String(160), default="Initial publication")
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Appeal(TenantRow, Base):
    __tablename__ = "appeals"
    __table_args__ = tenant_args(refs={"result_id": "results", "student_id": "students", "offering_id": "offerings"})
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[str] = mapped_column(String(64))
    offering_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    original_score: Mapped[float] = mapped_column(Float)
    revised_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    history: Mapped[list] = mapped_column(JSON, default=list)


OutboxEvent, ProcessedEvent = event_tables(Base)
