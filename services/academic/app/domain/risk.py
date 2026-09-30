from dataclasses import dataclass

from sqlalchemy import select

from services.academic.app.models import (Assessment, AttendanceRecord, AttendanceSession, Course, Enrollment, Grade, Offering,
                                          Student)

ATTENDED = {"present", "late"}


@dataclass(frozen=True)
class RiskPolicy:
    attendance_threshold: float = 0.75
    failing_score: float = 50
    consecutive_failures: int = 2


def attendance_rate(statuses: list[str]) -> float | None:
    """Excused sessions are excluded; with no countable sessions the rate is unknown rather than 0%."""
    counted = [status for status in statuses if status != "excused"]
    if not counted:
        return None
    return sum(status in ATTENDED for status in counted) / len(counted)


def evaluate(statuses: list[str], ordered_scores: list[float], policy: RiskPolicy) -> dict:
    """Documented rule: at risk when attendance < threshold OR the latest N assessment scores are all failing."""
    rate = attendance_rate(statuses)
    reasons = []
    if rate is not None and rate < policy.attendance_threshold:
        reasons.append({"code": "low_attendance",
                        "message": f"Attendance {rate:.0%} is below the {policy.attendance_threshold:.0%} threshold"})
    recent = ordered_scores[-policy.consecutive_failures:]
    if len(recent) == policy.consecutive_failures and all(score < policy.failing_score for score in recent):
        reasons.append({"code": "consecutive_failures",
                        "message": f"Last {policy.consecutive_failures} assessment scores are below {policy.failing_score:g}"})
    if reasons:
        status = "at_risk"
    elif rate is None and not ordered_scores:
        status = "unknown"
    else:
        status = "on_track"
    return {"attendance_rate": None if rate is None else round(rate, 4), "status": status, "reasons": reasons,
            "latest_scores": ordered_scores[-3:]}


def risk_rows(session, policy: RiskPolicy, offering_ids: list[str] | None = None, student_id: str | None = None) -> list[dict]:
    query = select(Enrollment).where(Enrollment.status == "enrolled")
    if offering_ids is not None:
        query = query.where(Enrollment.offering_id.in_(offering_ids))
    if student_id is not None:
        query = query.where(Enrollment.student_id == student_id)
    enrollments = session.scalars(query).all()
    if not enrollments:
        return []
    offerings = {row.offering_id for row in enrollments}
    students = {row.student_id for row in enrollments}
    statuses: dict[tuple[str, str], list[str]] = {}
    for offering_id, student, status in session.execute(
            select(AttendanceSession.offering_id, AttendanceRecord.student_id, AttendanceRecord.status)
            .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
            .where(AttendanceSession.offering_id.in_(offerings), AttendanceRecord.student_id.in_(students))).all():
        statuses.setdefault((offering_id, student), []).append(status)
    scores: dict[tuple[str, str], list[float]] = {}
    for offering_id, student, score in session.execute(
            select(Assessment.offering_id, Grade.student_id, Grade.score)
            .join(Grade, Grade.assessment_id == Assessment.id)
            .where(Assessment.offering_id.in_(offerings), Grade.student_id.in_(students))
            .order_by(Assessment.held_on, Assessment.id)).all():
        scores.setdefault((offering_id, student), []).append(score)
    names = {row.id: row for row in session.scalars(select(Student).where(Student.id.in_(students))).all()}
    courses = {offering.id: course for offering, course in session.execute(
        select(Offering, Course).join(Course, Course.id == Offering.course_id).where(Offering.id.in_(offerings))).all()}
    rows = []
    for row in enrollments:
        key = (row.offering_id, row.student_id)
        verdict = evaluate(statuses.get(key, []), scores.get(key, []), policy)
        student = names[row.student_id]
        course = courses[row.offering_id]
        rows.append({"student_id": student.id, "student_name": student.name, "student_no": student.student_no,
                     "offering_id": row.offering_id, "course_code": course.code, "course_title": course.title, **verdict})
    return sorted(rows, key=lambda item: (item["status"] != "at_risk", item["student_name"]))
