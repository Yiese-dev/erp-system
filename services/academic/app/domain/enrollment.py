from sqlalchemy import func, select

from packages.campus_common.database import fetch, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.events import record_event
from services.academic.app.models import (Course, Enrollment, Offering, OutboxEvent, Prerequisite, Program, Registration,
                                          Result, Student, Term)

ENROLLMENT_CONFIRMED = "academic.enrollment.confirmed.v1"


def creates_cycle(edges: dict[str, set[str]], course_id: str, prerequisite_id: str) -> bool:
    """Adding course -> prerequisite is circular when the course is already reachable from the prerequisite."""
    stack, seen = [prerequisite_id], set()
    while stack:
        node = stack.pop()
        if node == course_id:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return False


def add_prerequisite(session, tenant_id: str, course_id: str, prerequisite_id: str) -> Prerequisite:
    if course_id == prerequisite_id:
        raise DomainError("A course cannot be its own prerequisite.", 422)
    fetch(session, Course, course_id, "Course")
    fetch(session, Course, prerequisite_id, "Prerequisite course")
    edges: dict[str, set[str]] = {}
    for row in session.scalars(select(Prerequisite)).all():
        edges.setdefault(row.course_id, set()).add(row.prerequisite_id)
    if prerequisite_id in edges.get(course_id, set()):
        raise DomainError("This prerequisite is already defined.", 409)
    if creates_cycle(edges, course_id, prerequisite_id):
        raise DomainError("This prerequisite would create a circular requirement.", 409)
    link = Prerequisite(tenant_id=tenant_id, course_id=course_id, prerequisite_id=prerequisite_id)
    session.add(link)
    return link


def passed_courses(session, student_id: str) -> set[str]:
    rows = session.execute(select(Offering.course_id).join(Result, Result.offering_id == Offering.id)
                           .where(Result.student_id == student_id, Result.current.is_(True), Result.passed.is_(True))).all()
    return {course_id for (course_id,) in rows}


def missing_prerequisites(session, student_id: str, course_ids: list[str]) -> dict[str, list[str]]:
    """Only passing results that have been published count; draft marks never satisfy a prerequisite."""
    passed = passed_courses(session, student_id)
    missing: dict[str, list[str]] = {}
    for link in session.scalars(select(Prerequisite).where(Prerequisite.course_id.in_(course_ids))).all():
        if link.prerequisite_id not in passed:
            missing.setdefault(link.course_id, []).append(link.prerequisite_id)
    return missing


def enroll(session, tenant_id: str, registration: Registration, offering_id: str) -> Enrollment:
    offering = session.scalar(select(Offering).where(Offering.id == offering_id).with_for_update())
    if offering is None:
        raise DomainError("Course offering not found.", 404)
    if offering.term_id != registration.term_id:
        raise DomainError("The course offering belongs to a different term.", 422)
    course = session.get(Course, offering.course_id)
    missing = missing_prerequisites(session, registration.student_id, [offering.course_id])
    if missing:
        codes = [session.get(Course, course_id).code for course_id in missing[offering.course_id]]
        raise DomainError(f"Prerequisites not satisfied for {course.code}: {', '.join(codes)}.", 409,
                          details=[{"course": course.code, "missing": codes}])
    if session.scalar(select(Enrollment.id).where(Enrollment.offering_id == offering_id,
                                                  Enrollment.student_id == registration.student_id)):
        raise DomainError(f"The student is already enrolled in {course.code}.", 409)
    enrolled = session.scalar(select(func.count()).select_from(Enrollment)
                              .where(Enrollment.offering_id == offering_id, Enrollment.status == "enrolled")) or 0
    if enrolled >= offering.capacity:
        raise DomainError(f"{course.code} is full ({offering.capacity} seats).", 409)
    record = Enrollment(id=new_id("enr"), tenant_id=tenant_id, registration_id=registration.id, offering_id=offering_id,
                        student_id=registration.student_id, status="enrolled")
    session.add(record)
    session.flush()
    return record


def register_student(session, tenant_id: str, student_id: str, term_id: str, offering_ids: list[str],
                     correlation_id: str | None = None, registration_id: str | None = None) -> Registration:
    """Registration, enrollments and the billing event commit atomically (transactional outbox)."""
    student = fetch(session, Student, student_id, "Student")
    if student.status != "active":
        raise DomainError("Only active students can be registered.", 409)
    term = fetch(session, Term, term_id, "Term")
    if term.status == "closed":
        raise DomainError(f"Registration for {term.name} is closed.", 409)
    unique_ids = list(dict.fromkeys(offering_ids))
    if not unique_ids:
        raise DomainError("Select at least one course offering.", 422)
    if session.scalar(select(Registration.id).where(Registration.student_id == student_id, Registration.term_id == term_id)):
        raise DomainError(f"{student.name} is already registered for {term.name}.", 409)
    registration = Registration(id=registration_id or new_id("reg"), tenant_id=tenant_id, student_id=student_id, program_id=student.program_id,
                                term_id=term_id, status="confirmed", billing_status="pending", created_at=utcnow())
    session.add(registration)
    session.flush()
    codes = []
    for offering_id in unique_ids:
        record = enroll(session, tenant_id, registration, offering_id)
        codes.append(session.get(Course, session.get(Offering, record.offering_id).course_id).code)
    program = session.get(Program, student.program_id)
    record_event(session, OutboxEvent, tenant_id, ENROLLMENT_CONFIRMED, {
        "registration_id": registration.id, "student_id": student.id, "student_user_id": student.user_id,
        "student_name": student.name, "student_no": student.student_no, "program_id": program.id,
        "program_code": program.code, "program_name": program.name, "term_id": term.id, "term_name": term.name,
        "courses": codes,
    }, correlation_id)
    return registration


def add_course(session, tenant_id: str, registration: Registration, offering_id: str) -> Enrollment:
    if registration.status != "confirmed":
        raise DomainError("The registration is not active.", 409)
    return enroll(session, tenant_id, registration, offering_id)
