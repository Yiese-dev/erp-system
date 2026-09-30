from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from packages.campus_common.config import Settings, load_settings
from packages.campus_common.database import LOCAL_TZ, Database, fetch, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.http import create_application
from packages.campus_common.schemas import Page, as_dict, out_schema, paginate, paginate_rows
from packages.campus_common.security import Actor, current_actor
from services.academic.app.domain import enrollment, exams, grading, reports
from services.academic.app.domain.risk import RiskPolicy, attendance_rate, risk_rows
from services.academic.app.models import (Appeal, Assessment, AttendanceRecord, AttendanceSession, Base, Course, Enrollment, Exam,
                                          Grade, Offering, Policy, Prerequisite, Program, Registration, Result, Student, Term)

ANY = ("academic:read", "academic:write", "academic:teach", "academic:self")
CATALOG = (*ANY, "catalog:read")
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
CODE = r"^[A-Za-z0-9-]+$"


class ProgramIn(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=CODE)
    name: str = Field(min_length=3, max_length=160)
    level: str = Field("Bachelor", min_length=2, max_length=40)
    duration_terms: int = Field(6, ge=1, le=16)


class ProgramPatch(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=160)
    level: str | None = Field(None, min_length=2, max_length=40)
    duration_terms: int | None = Field(None, ge=1, le=16)
    active: bool | None = None


class CourseIn(BaseModel):
    program_id: str = Field(max_length=64)
    code: str = Field(min_length=3, max_length=20, pattern=CODE)
    title: str = Field(min_length=3, max_length=160)
    credits: int = Field(ge=1, le=12)


class CoursePatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=160)
    credits: int | None = Field(None, ge=1, le=12)
    active: bool | None = None


class PrerequisiteIn(BaseModel):
    prerequisite_id: str = Field(max_length=64)


class TermIn(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    starts_on: date
    ends_on: date
    status: Literal["planned", "active", "closed"] = "planned"


class TermPatch(BaseModel):
    status: Literal["planned", "active", "closed"]


class OfferingIn(BaseModel):
    course_id: str = Field(max_length=64)
    term_id: str = Field(max_length=64)
    instructor_user_id: str = Field(min_length=1, max_length=64)
    instructor_name: str = Field(min_length=3, max_length=160)
    room: str = Field(min_length=1, max_length=40)
    capacity: int = Field(40, ge=1, le=500)


class StudentIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(max_length=254, pattern=EMAIL)
    program_id: str = Field(max_length=64)
    user_id: str | None = Field(None, max_length=64)


class RegistrationIn(BaseModel):
    student_id: str = Field(max_length=64)
    term_id: str = Field(max_length=64)
    offering_ids: list[str] = Field(min_length=1, max_length=10)


class EnrollmentIn(BaseModel):
    offering_id: str = Field(max_length=64)


class AssessmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    weight: int = Field(ge=1, le=100)
    held_on: date


class GradeEntry(BaseModel):
    student_id: str = Field(max_length=64)
    score: float = Field(ge=0, le=100)


class GradesIn(BaseModel):
    entries: list[GradeEntry] = Field(min_length=1, max_length=500)


class AttendanceEntry(BaseModel):
    student_id: str = Field(max_length=64)
    status: Literal["present", "late", "absent", "excused"]


class AttendanceIn(BaseModel):
    held_on: date
    topic: str = Field("", max_length=160)
    records: list[AttendanceEntry] = Field(min_length=1, max_length=500)


class ExamIn(BaseModel):
    offering_id: str = Field(max_length=64)
    title: str = Field(min_length=3, max_length=120)
    room: str = Field(min_length=1, max_length=40)
    invigilator_user_id: str = Field(min_length=1, max_length=64)
    invigilator_name: str = Field(min_length=3, max_length=160)
    starts_at: datetime
    ends_at: datetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def localize(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value


class AppealIn(BaseModel):
    result_id: str = Field(max_length=64)
    reason: str = Field(min_length=10, max_length=2000)


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(min_length=3, max_length=1000)
    revised_score: float | None = Field(None, ge=0, le=100)


class PolicyIn(BaseModel):
    attendance_threshold: float = Field(ge=0.5, le=1)
    failing_score: float = Field(ge=1, le=100)
    consecutive_failures: int = Field(ge=1, le=5)
    appeal_window_days: int = Field(ge=1, le=60)


ProgramOut = out_schema(Program)
CourseOut = out_schema(Course, prerequisites=(list[str], []), program_code=(str, ""))
TermOut = out_schema(Term)
OfferingOut = out_schema(Offering, course_code=(str, ""), course_title=(str, ""), credits=(int, 0), term_name=(str, ""), enrolled=(int, 0))
StudentOut = out_schema(Student, program_code=(str, ""), program_name=(str, ""))
RegistrationOut = out_schema(Registration, student_name=(str, ""), student_no=(str, ""), term_name=(str, ""), courses=(list[str], []))
AssessmentOut = out_schema(Assessment)
ExamOut = out_schema(Exam, course_code=(str, ""), course_title=(str, ""))
ResultOut = out_schema(Result, course_code=(str, ""), course_title=(str, ""), credits=(int, 0), term_name=(str, ""), student_name=(str, ""))
AppealOut = out_schema(Appeal, student_name=(str, ""), course_code=(str, ""), course_title=(str, ""))
PolicyOut = out_schema(Policy)


def policy_of(session, tenant_id: str) -> Policy:
    return session.scalar(select(Policy)) or Policy(id="default", tenant_id=tenant_id, attendance_threshold=0.75, failing_score=50,
                                                     consecutive_failures=2, appeal_window_days=14, updated_at=utcnow())


def risk_policy(policy: Policy) -> RiskPolicy:
    return RiskPolicy(policy.attendance_threshold, policy.failing_score, policy.consecutive_failures)


def own_offering(actor: Actor, offering: Offering) -> Offering:
    if actor.can("academic:write") or (actor.can("academic:teach") and offering.instructor_user_id == actor.user_id):
        return offering
    raise DomainError("You can only manage course offerings assigned to you.", 403)


def linked_student(session, actor: Actor) -> Student:
    student = session.scalar(select(Student).where(Student.user_id == actor.user_id))
    if student is None:
        raise DomainError("No student record is linked to your account in this institution.", 404)
    return student


def current_term(session) -> Term | None:
    today = local_now().date()
    return (session.scalar(select(Term).where(Term.status == "active", Term.starts_on <= today, Term.ends_on >= today)
                           .order_by(Term.starts_on.desc()))
            or session.scalar(select(Term).where(Term.status == "active").order_by(Term.starts_on.desc())))


def offering_views(session, offerings: list[Offering]) -> list[dict]:
    if not offerings:
        return []
    ids = [item.id for item in offerings]
    counts = dict(session.execute(select(Enrollment.offering_id, func.count()).where(Enrollment.offering_id.in_(ids), Enrollment.status == "enrolled")
                                  .group_by(Enrollment.offering_id)).all())
    courses = {row.id: row for row in session.scalars(select(Course).where(Course.id.in_({item.course_id for item in offerings}))).all()}
    terms = {row.id: row for row in session.scalars(select(Term).where(Term.id.in_({item.term_id for item in offerings}))).all()}
    return [as_dict(item, course_code=courses[item.course_id].code, course_title=courses[item.course_id].title,
                    credits=courses[item.course_id].credits, term_name=terms[item.term_id].name, enrolled=counts.get(item.id, 0))
            for item in offerings]


def exam_views(session, rows: list[Exam]) -> list[dict]:
    courses = dict(session.execute(select(Offering.id, Course).join(Course, Course.id == Offering.course_id)
                                   .where(Offering.id.in_({row.offering_id for row in rows}))).all()) if rows else {}
    return [as_dict(row, course_code=courses[row.offering_id].code, course_title=courses[row.offering_id].title) for row in rows]


def result_views(session, rows: list[Result]) -> list[dict]:
    if not rows:
        return []
    details = {offering.id: (course, term) for offering, course, term in session.execute(
        select(Offering, Course, Term).join(Course, Course.id == Offering.course_id).join(Term, Term.id == Offering.term_id)
        .where(Offering.id.in_({row.offering_id for row in rows}))).all()}
    names = dict(session.execute(select(Student.id, Student.name).where(Student.id.in_({row.student_id for row in rows}))).all())
    return [as_dict(row, course_code=details[row.offering_id][0].code, course_title=details[row.offering_id][0].title,
                    credits=details[row.offering_id][0].credits, term_name=details[row.offering_id][1].name,
                    student_name=names.get(row.student_id, "")) for row in rows]


def appeal_views(session, rows: list[Appeal]) -> list[dict]:
    if not rows:
        return []
    courses = dict(session.execute(select(Offering.id, Course).join(Course, Course.id == Offering.course_id)
                                   .where(Offering.id.in_({row.offering_id for row in rows}))).all())
    names = dict(session.execute(select(Student.id, Student.name).where(Student.id.in_({row.student_id for row in rows}))).all())
    return [as_dict(row, student_name=names.get(row.student_id, ""), course_code=courses[row.offering_id].code,
                    course_title=courses[row.offering_id].title) for row in rows]


def pdf_response(content: bytes, filename: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def create_app(settings: Settings):
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        if settings.create_schema:
            database.create_all(Base.metadata)
        yield
        database.engine.dispose()

    app = create_application(settings, database, lifespan)
    p = "/api/v1/academic"

    def scoped(actor: Actor):
        return database.session(actor.tenant_id)

    # ---------- Policy ----------
    @app.get(f"{p}/policy", response_model=PolicyOut, tags=["Policy"])
    def read_policy(actor: Actor = Depends(current_actor)):
        actor.require(*ANY)
        with scoped(actor) as session:
            return as_dict(policy_of(session, actor.tenant_id))

    @app.put(f"{p}/policy", response_model=PolicyOut, tags=["Policy"])
    def update_policy(payload: PolicyIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            policy = session.scalar(select(Policy))
            if policy is None:
                policy = Policy(id=new_id("pol"), tenant_id=actor.tenant_id)
                session.add(policy)
            for key, value in payload.model_dump().items():
                setattr(policy, key, value)
            policy.updated_at = utcnow()
            session.flush()
            return as_dict(policy)

    # ---------- Programmes and courses ----------
    @app.get(f"{p}/programs", response_model=Page[ProgramOut], tags=["Catalogue"])
    def list_programs(q: str = "", include_archived: bool = False, page: int = 1, size: int = 50, actor: Actor = Depends(current_actor)):
        actor.require(*CATALOG)
        with scoped(actor) as session:
            query = select(Program).order_by(Program.code)
            if q:
                query = query.where(or_(Program.name.ilike(f"%{q}%"), Program.code.ilike(f"%{q}%")))
            if not include_archived:
                query = query.where(Program.active.is_(True))
            return paginate(session, query, page, size)

    @app.post(f"{p}/programs", response_model=ProgramOut, status_code=201, tags=["Catalogue"])
    def create_program(payload: ProgramIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            program = Program(id=new_id("prg"), tenant_id=actor.tenant_id, active=True, **{**payload.model_dump(), "code": payload.code.upper()})
            session.add(program)
            session.flush()
            return as_dict(program)

    @app.patch(f"{p}/programs/{{program_id}}", response_model=ProgramOut, tags=["Catalogue"])
    def update_program(program_id: str, payload: ProgramPatch, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            program = fetch(session, Program, program_id, "Programme")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(program, key, value)
            return as_dict(program)

    def course_views(session, courses: list[Course]) -> list[dict]:
        ids = [course.id for course in courses]
        links: dict[str, list[str]] = {}
        for link in session.scalars(select(Prerequisite).where(Prerequisite.course_id.in_(ids))).all() if ids else []:
            links.setdefault(link.course_id, []).append(link.prerequisite_id)
        programs = dict(session.execute(select(Program.id, Program.code)).all())
        return [as_dict(course, prerequisites=links.get(course.id, []), program_code=programs.get(course.program_id, "")) for course in courses]

    @app.get(f"{p}/courses", response_model=Page[CourseOut], tags=["Catalogue"])
    def list_courses(q: str = "", program_id: str = "", include_archived: bool = False, page: int = 1, size: int = 100,
                     actor: Actor = Depends(current_actor)):
        actor.require(*CATALOG)
        with scoped(actor) as session:
            query = select(Course).order_by(Course.code)
            if q:
                query = query.where(or_(Course.title.ilike(f"%{q}%"), Course.code.ilike(f"%{q}%")))
            if program_id:
                query = query.where(Course.program_id == program_id)
            if not include_archived:
                query = query.where(Course.active.is_(True))
            result = paginate(session, query, page, size, serialize=lambda row: row)
            result["items"] = course_views(session, result["items"])
            return result

    @app.post(f"{p}/courses", response_model=CourseOut, status_code=201, tags=["Catalogue"])
    def create_course(payload: CourseIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            fetch(session, Program, payload.program_id, "Programme")
            course = Course(id=new_id("crs"), tenant_id=actor.tenant_id, active=True, **{**payload.model_dump(), "code": payload.code.upper()})
            session.add(course)
            session.flush()
            return course_views(session, [course])[0]

    @app.patch(f"{p}/courses/{{course_id}}", response_model=CourseOut, tags=["Catalogue"])
    def update_course(course_id: str, payload: CoursePatch, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            course = fetch(session, Course, course_id, "Course")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(course, key, value)
            return course_views(session, [course])[0]

    @app.post(f"{p}/courses/{{course_id}}/prerequisites", response_model=CourseOut, status_code=201, tags=["Catalogue"])
    def add_prerequisite(course_id: str, payload: PrerequisiteIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            enrollment.add_prerequisite(session, actor.tenant_id, course_id, payload.prerequisite_id)
            session.flush()
            return course_views(session, [fetch(session, Course, course_id, "Course")])[0]

    @app.delete(f"{p}/courses/{{course_id}}/prerequisites/{{prerequisite_id}}", status_code=204, tags=["Catalogue"])
    def remove_prerequisite(course_id: str, prerequisite_id: str, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            link = session.get(Prerequisite, (course_id, prerequisite_id))
            if link is None:
                raise DomainError("Prerequisite link not found.", 404)
            session.delete(link)

    # ---------- Terms and offerings ----------
    @app.get(f"{p}/terms", response_model=list[TermOut], tags=["Terms"])
    def list_terms(actor: Actor = Depends(current_actor)):
        actor.require(*CATALOG)
        with scoped(actor) as session:
            return [as_dict(term) for term in session.scalars(select(Term).order_by(Term.starts_on.desc())).all()]

    @app.post(f"{p}/terms", response_model=TermOut, status_code=201, tags=["Terms"])
    def create_term(payload: TermIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        if payload.ends_on <= payload.starts_on:
            raise DomainError("The term must end after it starts.", 422)
        with scoped(actor) as session:
            term = Term(id=new_id("trm"), tenant_id=actor.tenant_id, **payload.model_dump())
            session.add(term)
            session.flush()
            return as_dict(term)

    @app.patch(f"{p}/terms/{{term_id}}", response_model=TermOut, tags=["Terms"])
    def update_term(term_id: str, payload: TermPatch, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            term = fetch(session, Term, term_id, "Term")
            term.status = payload.status
            return as_dict(term)

    @app.get(f"{p}/offerings", response_model=list[OfferingOut], tags=["Offerings"])
    def list_offerings(term_id: str = "", mine: bool = False, actor: Actor = Depends(current_actor)):
        actor.require(*ANY)
        with scoped(actor) as session:
            query = select(Offering)
            if term_id:
                query = query.where(Offering.term_id == term_id)
            if mine or (actor.can("academic:teach") and not actor.can("academic:write")):
                query = query.where(Offering.instructor_user_id == actor.user_id)
            views = offering_views(session, session.scalars(query).all())
            return sorted(views, key=lambda item: (item["term_name"], item["course_code"]))

    @app.post(f"{p}/offerings", response_model=OfferingOut, status_code=201, tags=["Offerings"])
    def create_offering(payload: OfferingIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            fetch(session, Course, payload.course_id, "Course")
            term = fetch(session, Term, payload.term_id, "Term")
            if term.status == "closed":
                raise DomainError("Offerings cannot be added to a closed term.", 409)
            offering = Offering(id=new_id("off"), tenant_id=actor.tenant_id, results_status="draft", **payload.model_dump())
            session.add(offering)
            session.flush()
            return offering_views(session, [offering])[0]

    @app.get(f"{p}/offerings/{{offering_id}}/roster", tags=["Offerings"])
    def roster(offering_id: str, actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        with scoped(actor) as session:
            own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            rows = session.execute(select(Student, Enrollment).join(Enrollment, Enrollment.student_id == Student.id)
                                   .where(Enrollment.offering_id == offering_id, Enrollment.status == "enrolled").order_by(Student.name)).all()
            return [{"student_id": s.id, "name": s.name, "student_no": s.student_no, "email": s.email, "enrollment_id": e.id} for s, e in rows]

    # ---------- Students and registrations ----------
    @app.get(f"{p}/students", response_model=Page[StudentOut], tags=["Students"])
    def list_students(q: str = "", program_id: str = "", page: int = 1, size: int = 25, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            query = select(Student, Program).join(Program, Program.id == Student.program_id).order_by(Student.name)
            if q:
                query = query.where(or_(Student.name.ilike(f"%{q}%"), Student.student_no.ilike(f"%{q}%"), Student.email.ilike(f"%{q}%")))
            if program_id:
                query = query.where(Student.program_id == program_id)
            return paginate_rows(session, query, page, size,
                                 lambda student, program: as_dict(student, program_code=program.code, program_name=program.name))

    @app.post(f"{p}/students", response_model=StudentOut, status_code=201, tags=["Students"])
    def create_student(payload: StudentIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            program = fetch(session, Program, payload.program_id, "Programme")
            count = session.scalar(select(func.count()).select_from(Student)) or 0
            student = Student(id=new_id("stu"), tenant_id=actor.tenant_id, user_id=payload.user_id or None,
                              student_no=f"STU{local_now().year % 100:02d}{count + 1:04d}", name=payload.name,
                              email=payload.email.lower(), program_id=program.id, status="active", admitted_on=local_now().date())
            session.add(student)
            session.flush()
            return as_dict(student, program_code=program.code, program_name=program.name)

    @app.get(f"{p}/students/{{student_id}}/transcript", tags=["Reports"])
    def student_transcript(student_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        with scoped(actor) as session:
            student = fetch(session, Student, student_id, "Student")
            if not actor.can("academic:write") and student.user_id != actor.user_id:
                raise DomainError("Student not found.", 404)
            return reports.transcript(session, student)

    @app.get(f"{p}/registrations", response_model=Page[RegistrationOut], tags=["Registrations"])
    def list_registrations(term_id: str = "", student_id: str = "", billing_status: str = "", page: int = 1, size: int = 25,
                           actor: Actor = Depends(current_actor)):
        actor.require("academic:write")
        with scoped(actor) as session:
            query = (select(Registration, Student, Term).join(Student, Student.id == Registration.student_id)
                     .join(Term, Term.id == Registration.term_id).order_by(Registration.created_at.desc()))
            if term_id:
                query = query.where(Registration.term_id == term_id)
            if student_id:
                query = query.where(Registration.student_id == student_id)
            if billing_status:
                query = query.where(Registration.billing_status == billing_status)
            result = paginate_rows(session, query, page, size, lambda r, s, t: (r, s, t))
            ids = [r.id for r, _, _ in result["items"]]
            codes: dict[str, list[str]] = {}
            for registration_id, code in session.execute(select(Enrollment.registration_id, Course.code)
                                                         .join(Offering, Offering.id == Enrollment.offering_id)
                                                         .join(Course, Course.id == Offering.course_id)
                                                         .where(Enrollment.registration_id.in_(ids))).all() if ids else []:
                codes.setdefault(registration_id, []).append(code)
            result["items"] = [as_dict(r, student_name=s.name, student_no=s.student_no, term_name=t.name, courses=sorted(codes.get(r.id, [])))
                               for r, s, t in result["items"]]
            return result

    @app.post(f"{p}/registrations", response_model=RegistrationOut, status_code=201, tags=["Registrations"])
    def create_registration(payload: RegistrationIn, actor: Actor = Depends(current_actor)):
        """Confirms a term registration and emits academic.enrollment.confirmed.v1 for Finance billing."""
        actor.require("academic:write")
        with scoped(actor) as session:
            registration = enrollment.register_student(session, actor.tenant_id, payload.student_id, payload.term_id, payload.offering_ids)
            student, term = session.get(Student, registration.student_id), session.get(Term, registration.term_id)
            codes = session.scalars(select(Course.code).join(Offering, Offering.course_id == Course.id)
                                    .join(Enrollment, Enrollment.offering_id == Offering.id).where(Enrollment.registration_id == registration.id)).all()
            return as_dict(registration, student_name=student.name, student_no=student.student_no, term_name=term.name, courses=sorted(codes))

    @app.post(f"{p}/registrations/{{registration_id}}/enrollments", status_code=201, tags=["Registrations"])
    def add_enrollment(registration_id: str, payload: EnrollmentIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("academic:write")
        with scoped(actor) as session:
            record = enrollment.add_course(session, actor.tenant_id, fetch(session, Registration, registration_id, "Registration"), payload.offering_id)
            return as_dict(record)

    # ---------- Gradebook ----------
    @app.get(f"{p}/offerings/{{offering_id}}/gradebook", tags=["Gradebook"])
    def gradebook(offering_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            assessments = session.scalars(select(Assessment).where(Assessment.offering_id == offering_id).order_by(Assessment.held_on)).all()
            students = session.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id)
                                       .where(Enrollment.offering_id == offering_id, Enrollment.status == "enrolled").order_by(Student.name)).all()
            marks: dict[str, dict[str, float]] = {}
            ids = [item.id for item in assessments]
            for grade in session.scalars(select(Grade).where(Grade.assessment_id.in_(ids))).all() if ids else []:
                marks.setdefault(grade.student_id, {})[grade.assessment_id] = grade.score
            return {"offering": offering_views(session, [offering])[0], "assessments": [as_dict(item) for item in assessments],
                    "total_weight": sum(item.weight for item in assessments),
                    "students": [{"id": s.id, "name": s.name, "student_no": s.student_no, "scores": marks.get(s.id, {})} for s in students]}

    @app.post(f"{p}/offerings/{{offering_id}}/assessments", response_model=AssessmentOut, status_code=201, tags=["Gradebook"])
    def create_assessment(offering_id: str, payload: AssessmentIn, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            assessment = grading.add_assessment(session, actor.tenant_id, offering, payload.name, payload.weight, payload.held_on)
            session.flush()
            return as_dict(assessment)

    @app.put(f"{p}/assessments/{{assessment_id}}/grades", tags=["Gradebook"])
    def save_grades(assessment_id: str, payload: GradesIn, actor: Actor = Depends(current_actor)) -> dict[str, int]:
        with scoped(actor) as session:
            assessment = fetch(session, Assessment, assessment_id, "Assessment")
            own_offering(actor, fetch(session, Offering, assessment.offering_id, "Course offering"))
            saved = grading.record_grades(session, actor.tenant_id, actor.user_id, assessment,
                                          [(entry.student_id, entry.score) for entry in payload.entries])
            return {"saved": saved}

    @app.post(f"{p}/offerings/{{offering_id}}/results/publish", response_model=list[ResultOut], tags=["Results"])
    def publish(offering_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            results = grading.publish_results(session, actor.tenant_id, offering)
            session.flush()
            return result_views(session, results)

    @app.get(f"{p}/offerings/{{offering_id}}/results", response_model=list[ResultOut], tags=["Results"])
    def offering_results(offering_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            rows = session.scalars(select(Result).where(Result.offering_id == offering_id, Result.current.is_(True))).all()
            return sorted(result_views(session, rows), key=lambda item: item["student_name"])

    # ---------- Attendance ----------
    @app.get(f"{p}/offerings/{{offering_id}}/attendance", tags=["Attendance"])
    def offering_attendance(offering_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            lessons = session.scalars(select(AttendanceSession).where(AttendanceSession.offering_id == offering_id)
                                      .order_by(AttendanceSession.held_on.desc())).all()
            ids = [lesson.id for lesson in lessons]
            records: dict[str, dict[str, str]] = {}
            for row in session.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_(ids))).all() if ids else []:
                records.setdefault(row.session_id, {})[row.student_id] = row.status
            summary = reports.attendance_summary(session, offering)
            return {"sessions": [{**as_dict(lesson), "records": records.get(lesson.id, {})} for lesson in lessons], "summary": summary["rows"]}

    @app.post(f"{p}/offerings/{{offering_id}}/attendance", status_code=201, tags=["Attendance"])
    def save_attendance(offering_id: str, payload: AttendanceIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            if payload.held_on > local_now().date():
                raise DomainError("Attendance cannot be recorded for a future date.", 422)
            lesson = grading.record_attendance(session, actor.tenant_id, offering, payload.held_on, payload.topic,
                                               [(entry.student_id, entry.status) for entry in payload.records])
            session.flush()
            return as_dict(lesson)

    # ---------- Examinations ----------
    @app.get(f"{p}/exams", response_model=list[ExamOut], tags=["Examinations"])
    def list_exams(start: date | None = None, end: date | None = None, actor: Actor = Depends(current_actor)):
        actor.require(*ANY)
        with scoped(actor) as session:
            query = select(Exam).order_by(Exam.starts_at)
            if start:
                query = query.where(Exam.ends_at >= datetime.combine(start, datetime.min.time(), LOCAL_TZ))
            if end:
                query = query.where(Exam.starts_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), LOCAL_TZ))
            if not actor.can("academic:write", "academic:read", "academic:teach"):
                student = linked_student(session, actor)
                query = query.where(Exam.offering_id.in_(select(Enrollment.offering_id).where(Enrollment.student_id == student.id,
                                                                                              Enrollment.status == "enrolled")))
            return exam_views(session, session.scalars(query).all())

    def exam_arguments(session, actor: Actor, payload: ExamIn):
        offering = own_offering(actor, fetch(session, Offering, payload.offering_id, "Course offering"))
        return offering

    @app.post(f"{p}/exams/check", tags=["Examinations"])
    def check_exam(payload: ExamIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        """Preview conflicts without booking (room, invigilator, and shared students)."""
        with scoped(actor) as session:
            offering = exam_arguments(session, actor, payload)
            conflicts = exams.find_conflicts(session, offering.id, payload.room, payload.invigilator_user_id, payload.starts_at, payload.ends_at)
            return {"conflicts": conflicts, "ok": not conflicts}

    @app.post(f"{p}/exams", response_model=ExamOut, status_code=201, tags=["Examinations"])
    def create_exam(payload: ExamIn, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            offering = exam_arguments(session, actor, payload)
            exam = exams.schedule_exam(session, actor.tenant_id, offering, payload.title, payload.room, payload.invigilator_user_id,
                                       payload.invigilator_name, payload.starts_at, payload.ends_at)
            session.flush()
            return exam_views(session, [exam])[0]

    @app.delete(f"{p}/exams/{{exam_id}}", status_code=204, tags=["Examinations"])
    def delete_exam(exam_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            exam = fetch(session, Exam, exam_id, "Exam")
            own_offering(actor, fetch(session, Offering, exam.offering_id, "Course offering"))
            session.delete(exam)

    # ---------- Appeals ----------
    @app.get(f"{p}/appeals", response_model=list[AppealOut], tags=["Appeals"])
    def list_appeals(status: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*ANY)
        with scoped(actor) as session:
            query = select(Appeal).order_by(Appeal.created_at.desc())
            if status:
                query = query.where(Appeal.status == status)
            if actor.can("academic:write"):
                pass
            elif actor.can("academic:teach"):
                query = query.where(Appeal.offering_id.in_(select(Offering.id).where(Offering.instructor_user_id == actor.user_id)))
            else:
                query = query.where(Appeal.student_id == linked_student(session, actor).id)
            return appeal_views(session, session.scalars(query.limit(200)).all())

    @app.post(f"{p}/appeals", response_model=AppealOut, status_code=201, tags=["Appeals"])
    def create_appeal(payload: AppealIn, actor: Actor = Depends(current_actor)):
        actor.require("academic:self")
        with scoped(actor) as session:
            student = linked_student(session, actor)
            appeal = grading.submit_appeal(session, actor.tenant_id, student, payload.result_id, payload.reason, policy_of(session, actor.tenant_id))
            session.flush()
            return appeal_views(session, [appeal])[0]

    def appeal_for_staff(session, actor: Actor, appeal_id: str) -> Appeal:
        appeal = fetch(session, Appeal, appeal_id, "Appeal")
        own_offering(actor, fetch(session, Offering, appeal.offering_id, "Course offering"))
        return appeal

    @app.post(f"{p}/appeals/{{appeal_id}}/review", response_model=AppealOut, tags=["Appeals"])
    def review(appeal_id: str, payload: NoteIn, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            appeal = grading.review_appeal(appeal_for_staff(session, actor, appeal_id), actor.user_id, payload.note)
            return appeal_views(session, [appeal])[0]

    @app.post(f"{p}/appeals/{{appeal_id}}/decision", response_model=AppealOut, tags=["Appeals"])
    def decide(appeal_id: str, payload: DecisionIn, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            appeal = grading.decide_appeal(session, actor.tenant_id, appeal_for_staff(session, actor, appeal_id), actor.user_id,
                                           payload.decision, payload.note, payload.revised_score)
            session.flush()
            return appeal_views(session, [appeal])[0]

    # ---------- Risk and reports ----------
    @app.get(f"{p}/risk", tags=["Analytics"])
    def at_risk(offering_id: str = "", only_flagged: bool = False, actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        """Rule: attendance below the tenant threshold (75%) OR the latest two assessment scores below the failing mark (50)."""
        actor.require(*ANY)
        with scoped(actor) as session:
            policy = risk_policy(policy_of(session, actor.tenant_id))
            if actor.can("academic:write", "academic:teach"):
                query = select(Offering.id)
                if offering_id:
                    query = query.where(Offering.id == offering_id)
                else:
                    term = current_term(session)
                    query = query.where(Offering.term_id == (term.id if term else ""))
                if not actor.can("academic:write"):
                    query = query.where(Offering.instructor_user_id == actor.user_id)
                rows = risk_rows(session, policy, offering_ids=list(session.scalars(query).all()))
            else:
                rows = risk_rows(session, policy, student_id=linked_student(session, actor).id)
            return [row for row in rows if row["status"] == "at_risk"] if only_flagged else rows

    @app.get(f"{p}/reports/students/{{student_id}}/transcript.pdf", tags=["Reports"], response_class=Response)
    def transcript_pdf(student_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            student = fetch(session, Student, student_id, "Student")
            if not actor.can("academic:write") and student.user_id != actor.user_id:
                raise DomainError("Student not found.", 404)
            content = reports.transcript_pdf(actor.tenant_name or "Campus ERP", reports.transcript(session, student))
            return pdf_response(content, f"transcript-{student.student_no}.pdf")

    @app.get(f"{p}/reports/offerings/{{offering_id}}/attendance.pdf", tags=["Reports"], response_class=Response)
    def attendance_pdf(offering_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            offering = own_offering(actor, fetch(session, Offering, offering_id, "Course offering"))
            data = reports.attendance_summary(session, offering)
            content = reports.attendance_pdf(actor.tenant_name or "Campus ERP", data, policy_of(session, actor.tenant_id).attendance_threshold)
            return pdf_response(content, f"attendance-{data['course'].split()[0]}.pdf")

    # ---------- Student self-service ----------
    @app.get(f"{p}/me/courses", tags=["Self service"])
    def my_courses(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("academic:self")
        with scoped(actor) as session:
            student = linked_student(session, actor)
            program = session.get(Program, student.program_id)
            enrollments = session.scalars(select(Enrollment).where(Enrollment.student_id == student.id, Enrollment.status == "enrolled")).all()
            offerings = session.scalars(select(Offering).where(Offering.id.in_([row.offering_id for row in enrollments]))).all() if enrollments else []
            views = {view["id"]: view for view in offering_views(session, list(offerings))}
            risk = {row["offering_id"]: row for row in risk_rows(session, risk_policy(policy_of(session, actor.tenant_id)), student_id=student.id)}
            assessments = session.execute(select(Assessment, Grade).outerjoin(Grade, (Grade.assessment_id == Assessment.id) & (Grade.student_id == student.id))
                                          .where(Assessment.offering_id.in_(views)).order_by(Assessment.held_on)).all() if views else []
            marks: dict[str, list[dict]] = {}
            for assessment, grade in assessments:
                marks.setdefault(assessment.offering_id, []).append({"name": assessment.name, "weight": assessment.weight,
                                                                     "held_on": assessment.held_on, "score": grade.score if grade else None})
            courses = [{**view, "assessments": marks.get(view["id"], []), "risk": risk.get(view["id"])} for view in views.values()]
            return {"student": as_dict(student, program_code=program.code, program_name=program.name),
                    "courses": sorted(courses, key=lambda item: (item["term_name"], item["course_code"]), reverse=True)}

    @app.get(f"{p}/me/results", response_model=list[ResultOut], tags=["Self service"])
    def my_results(actor: Actor = Depends(current_actor)):
        actor.require("academic:self")
        with scoped(actor) as session:
            student = linked_student(session, actor)
            rows = session.scalars(select(Result).where(Result.student_id == student.id).order_by(Result.published_at.desc())).all()
            return result_views(session, rows)

    @app.get(f"{p}/me/transcript.pdf", tags=["Self service"], response_class=Response)
    def my_transcript(actor: Actor = Depends(current_actor)):
        actor.require("academic:self")
        with scoped(actor) as session:
            student = linked_student(session, actor)
            return pdf_response(reports.transcript_pdf(actor.tenant_name or "Campus ERP", reports.transcript(session, student)),
                                f"transcript-{student.student_no}.pdf")

    # ---------- Dashboards ----------
    @app.get(f"{p}/dashboard", tags=["Dashboard"])
    def dashboard(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*ANY)
        with scoped(actor) as session:
            policy = policy_of(session, actor.tenant_id)
            term = current_term(session)
            now = utcnow()
            upcoming = select(Exam).where(Exam.starts_at >= now).order_by(Exam.starts_at).limit(8)
            if actor.can("academic:write"):
                return admin_dashboard(session, term, policy, upcoming)
            if actor.can("academic:teach"):
                return instructor_dashboard(session, actor, term, policy, upcoming)
            return student_dashboard(session, actor, policy, upcoming)

    def admin_dashboard(session, term: Term | None, policy: Policy, upcoming) -> dict[str, Any]:
        count = lambda model, *where: session.scalar(select(func.count()).select_from(model).where(*where)) or 0  # noqa: E731
        term_offerings = list(session.scalars(select(Offering.id).where(Offering.term_id == (term.id if term else ""))).all())
        flagged = [row for row in risk_rows(session, risk_policy(policy), offering_ids=term_offerings) if row["status"] == "at_risk"]
        by_program = session.execute(select(Program.code, Program.name, func.count(Registration.id))
                                     .join(Registration, Registration.program_id == Program.id)
                                     .where(Registration.term_id == (term.id if term else "")).group_by(Program.code, Program.name)).all()
        grades = session.execute(select(Result.letter, func.count()).where(Result.current.is_(True)).group_by(Result.letter)).all()
        billing = dict(session.execute(select(Registration.billing_status, func.count()).where(Registration.term_id == (term.id if term else ""))
                                       .group_by(Registration.billing_status)).all())
        return {"role": "admin", "term": as_dict(term) if term else None,
                "totals": {"students": count(Student, Student.status == "active"), "programs": count(Program, Program.active.is_(True)),
                           "courses": count(Course, Course.active.is_(True)), "offerings": len(term_offerings),
                           "registrations": count(Registration, Registration.term_id == (term.id if term else "")),
                           "at_risk": len({row["student_id"] for row in flagged}),
                           "pending_appeals": count(Appeal, Appeal.status.in_(("open", "under_review")))},
                "enrollment_by_program": [{"code": code, "name": name, "registrations": total} for code, name, total in by_program],
                "grade_distribution": [{"letter": letter, "count": total} for letter, total in sorted(grades)],
                "billing": billing, "at_risk": flagged[:10], "upcoming_exams": exam_views(session, session.scalars(upcoming).all())}

    def instructor_dashboard(session, actor: Actor, term: Term | None, policy: Policy, upcoming) -> dict[str, Any]:
        offerings = session.scalars(select(Offering).where(Offering.instructor_user_id == actor.user_id,
                                                           Offering.term_id == (term.id if term else ""))).all()
        views = sorted(offering_views(session, list(offerings)), key=lambda item: item["course_code"])
        ids = [view["id"] for view in views]
        risk = risk_rows(session, risk_policy(policy), offering_ids=ids)
        summaries = []
        for view in views:
            rows = [row for row in risk if row["offering_id"] == view["id"]]
            rates = [row["attendance_rate"] for row in rows if row["attendance_rate"] is not None]
            scores = [score for row in rows for score in row["latest_scores"]]
            summaries.append({**view, "attendance_rate": round(sum(rates) / len(rates), 4) if rates else None,
                              "average_score": round(sum(scores) / len(scores), 1) if scores else None,
                              "at_risk": sum(row["status"] == "at_risk" for row in rows)})
        mine = select(Offering.id).where(Offering.instructor_user_id == actor.user_id)
        pending = session.scalar(select(func.count()).select_from(Appeal).where(Appeal.offering_id.in_(mine),
                                                                                Appeal.status.in_(("open", "under_review")))) or 0
        exams_list = session.scalars(upcoming.where(Exam.offering_id.in_(mine))).all()
        return {"role": "instructor", "term": as_dict(term) if term else None, "offerings": summaries, "pending_appeals": pending,
                "at_risk": [row for row in risk if row["status"] == "at_risk"][:12], "upcoming_exams": exam_views(session, exams_list)}

    def student_dashboard(session, actor: Actor, policy: Policy, upcoming) -> dict[str, Any]:
        student = linked_student(session, actor)
        program = session.get(Program, student.program_id)
        risk = risk_rows(session, risk_policy(policy), student_id=student.id)
        statuses = session.scalars(select(AttendanceRecord.status).where(AttendanceRecord.student_id == student.id)).all()
        data = reports.transcript(session, student)
        mine = select(Enrollment.offering_id).where(Enrollment.student_id == student.id, Enrollment.status == "enrolled")
        appeals = session.scalar(select(func.count()).select_from(Appeal).where(Appeal.student_id == student.id,
                                                                                Appeal.status.in_(("open", "under_review")))) or 0
        return {"role": "student", "student": as_dict(student, program_code=program.code, program_name=program.name),
                "attendance_rate": attendance_rate(list(statuses)), "courses": risk,
                "credits_earned": data["credits_earned"], "average": data["average"], "open_appeals": appeals,
                "upcoming_exams": exam_views(session, session.scalars(upcoming.where(Exam.offering_id.in_(mine))).all())}

    return app


def application():
    return create_app(load_settings("academic"))
