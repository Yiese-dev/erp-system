from datetime import datetime

from sqlalchemy import select, text

from packages.campus_common.database import new_id
from packages.campus_common.errors import DomainError
from services.academic.app.models import Course, Enrollment, Exam, Offering


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intervals: an exam ending at 10:00 does not clash with one starting at 10:00."""
    return a_start < b_end and b_start < a_end


def find_conflicts(session, offering_id: str, room: str, invigilator_user_id: str, starts_at: datetime, ends_at: datetime,
                   exclude_id: str | None = None) -> list[dict]:
    candidates = [exam for exam in session.scalars(select(Exam).where(Exam.starts_at < ends_at, Exam.ends_at > starts_at)).all()
                  if exam.id != exclude_id]
    if not candidates:
        return []
    offering_ids = {offering_id, *(exam.offering_id for exam in candidates)}
    roster: dict[str, set[str]] = {key: set() for key in offering_ids}
    for enrolled_offering, student_id in session.execute(select(Enrollment.offering_id, Enrollment.student_id)
                                                         .where(Enrollment.offering_id.in_(offering_ids), Enrollment.status == "enrolled")).all():
        roster[enrolled_offering].add(student_id)
    conflicts = []
    for exam in candidates:
        reasons = []
        if exam.room.strip().casefold() == room.strip().casefold():
            reasons.append(f"Room {exam.room} is already booked")
        if exam.invigilator_user_id == invigilator_user_id:
            reasons.append(f"{exam.invigilator_name} is already invigilating")
        shared = roster[offering_id] & roster[exam.offering_id]
        if shared:
            reasons.append(f"{len(shared)} student(s) sit both exams")
        if reasons:
            course = session.get(Course, session.get(Offering, exam.offering_id).course_id)
            conflicts.append({"exam_id": exam.id, "course": course.code, "title": exam.title, "room": exam.room,
                              "starts_at": exam.starts_at.isoformat(), "ends_at": exam.ends_at.isoformat(), "reasons": reasons})
    return conflicts


def schedule_exam(session, tenant_id: str, offering: Offering, title: str, room: str, invigilator_user_id: str,
                  invigilator_name: str, starts_at: datetime, ends_at: datetime) -> Exam:
    if ends_at <= starts_at:
        raise DomainError("The exam must end after it starts.", 422)
    if session.get_bind().dialect.name == "postgresql":
        # Serialises scheduling per tenant so two concurrent bookings cannot both pass the conflict check.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"{tenant_id}:exam-schedule"})
    conflicts = find_conflicts(session, offering.id, room, invigilator_user_id, starts_at, ends_at)
    if conflicts:
        raise DomainError("This exam conflicts with existing bookings.", 409, details=conflicts)
    exam = Exam(id=new_id("exm"), tenant_id=tenant_id, offering_id=offering.id, title=title, room=room.strip(),
                invigilator_user_id=invigilator_user_id, invigilator_name=invigilator_name, starts_at=starts_at, ends_at=ends_at)
    session.add(exam)
    return exam
