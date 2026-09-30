from datetime import date, datetime, timedelta

from sqlalchemy import select

from packages.campus_common.database import fetch, new_id, utcnow
from packages.campus_common.errors import DomainError
from services.academic.app.models import (Appeal, Assessment, AttendanceRecord, AttendanceSession, Enrollment, Grade,
                                          Offering, Policy, Result, Student)

SCALE = ((80, "A"), (70, "B"), (60, "C"), (50, "D"), (0, "F"))
PASS_MARK = 50


def letter_for(score: float) -> str:
    return next(letter for floor, letter in SCALE if score >= floor)


def weighted_score(weights: dict[str, int], scores: dict[str, float]) -> float:
    return round(sum(scores[assessment_id] * weight / 100 for assessment_id, weight in weights.items()), 2)


def enrolled_students(session, offering_id: str) -> set[str]:
    return set(session.scalars(select(Enrollment.student_id).where(Enrollment.offering_id == offering_id,
                                                                    Enrollment.status == "enrolled")).all())


def ensure_open(offering: Offering) -> None:
    if offering.results_status == "published":
        raise DomainError("Results are already published; changes now go through the grade-appeal workflow.", 409)


def add_assessment(session, tenant_id: str, offering: Offering, name: str, weight: int, held_on: date) -> Assessment:
    ensure_open(offering)
    existing = sum(session.scalars(select(Assessment.weight).where(Assessment.offering_id == offering.id)).all())
    if existing + weight > 100:
        raise DomainError(f"Assessment weights would total {existing + weight}%; the maximum is 100%.", 422)
    assessment = Assessment(id=new_id("asm"), tenant_id=tenant_id, offering_id=offering.id, name=name, weight=weight, held_on=held_on)
    session.add(assessment)
    return assessment


def record_grades(session, tenant_id: str, actor_user_id: str, assessment: Assessment, entries: list[tuple[str, float]]) -> int:
    offering = fetch(session, Offering, assessment.offering_id, "Course offering")
    ensure_open(offering)
    enrolled = enrolled_students(session, offering.id)
    unknown = [student_id for student_id, _ in entries if student_id not in enrolled]
    if unknown:
        raise DomainError("Grades can only be recorded for enrolled students.", 422, details={"students": unknown})
    existing = {grade.student_id: grade for grade in session.scalars(select(Grade).where(Grade.assessment_id == assessment.id)).all()}
    for student_id, score in entries:
        if not 0 <= score <= 100:
            raise DomainError("Scores must be between 0 and 100.", 422)
        grade = existing.get(student_id)
        if grade is None:
            session.add(Grade(id=new_id("grd"), tenant_id=tenant_id, assessment_id=assessment.id, student_id=student_id,
                              score=round(score, 2), recorded_by=actor_user_id, recorded_at=utcnow()))
        else:
            grade.score, grade.recorded_by, grade.recorded_at = round(score, 2), actor_user_id, utcnow()
    return len(entries)


def record_attendance(session, tenant_id: str, offering: Offering, held_on: date, topic: str,
                      records: list[tuple[str, str]]) -> AttendanceSession:
    enrolled = enrolled_students(session, offering.id)
    unknown = [student_id for student_id, _ in records if student_id not in enrolled]
    if unknown:
        raise DomainError("Attendance can only be recorded for enrolled students.", 422, details={"students": unknown})
    lesson = session.scalar(select(AttendanceSession).where(AttendanceSession.offering_id == offering.id,
                                                            AttendanceSession.held_on == held_on))
    if lesson is None:
        lesson = AttendanceSession(id=new_id("att"), tenant_id=tenant_id, offering_id=offering.id, held_on=held_on, topic=topic)
        session.add(lesson)
        session.flush()
    else:
        lesson.topic = topic or lesson.topic
    existing = {row.student_id: row for row in session.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == lesson.id)).all()}
    for student_id, status in records:
        if student_id in existing:
            existing[student_id].status = status
        else:
            session.add(AttendanceRecord(tenant_id=tenant_id, session_id=lesson.id, student_id=student_id, status=status))
    return lesson


def publish_results(session, tenant_id: str, offering: Offering) -> list[Result]:
    ensure_open(offering)
    assessments = session.scalars(select(Assessment).where(Assessment.offering_id == offering.id)).all()
    weights = {item.id: item.weight for item in assessments}
    if sum(weights.values()) != 100:
        raise DomainError(f"Assessment weights total {sum(weights.values())}%; they must total exactly 100% before publication.", 422)
    students = enrolled_students(session, offering.id)
    if not students:
        raise DomainError("There are no enrolled students to publish results for.", 409)
    scores: dict[str, dict[str, float]] = {student_id: {} for student_id in students}
    for grade in session.scalars(select(Grade).where(Grade.assessment_id.in_(weights))).all():
        if grade.student_id in scores:
            scores[grade.student_id][grade.assessment_id] = grade.score
    names = {item.id: item.name for item in assessments}
    missing = [{"student": session.get(Student, student_id).name, "assessment": names[assessment_id]}
               for student_id, marks in scores.items() for assessment_id in weights if assessment_id not in marks]
    if missing:
        raise DomainError(f"{len(missing)} grade(s) are still missing.", 422, details=missing[:25])
    published_at = utcnow()
    results = []
    for student_id, marks in scores.items():
        score = weighted_score(weights, marks)
        results.append(Result(id=new_id("res"), tenant_id=tenant_id, offering_id=offering.id, student_id=student_id,
                              score=score, letter=letter_for(score), passed=score >= PASS_MARK, revision=1, current=True,
                              reason="Initial publication", published_at=published_at))
    session.add_all(results)
    offering.results_status, offering.published_at = "published", published_at
    return results


def _history(appeal: Appeal, status: str, actor_user_id: str, note: str = "") -> None:
    appeal.history = [*(appeal.history or []), {"status": status, "by": actor_user_id, "note": note, "at": utcnow().isoformat()}]


def submit_appeal(session, tenant_id: str, student: Student, result_id: str, reason: str, policy: Policy,
                  now: datetime | None = None) -> Appeal:
    result = session.get(Result, result_id)
    if result is None or result.student_id != student.id:
        raise DomainError("Published result not found.", 404)
    if not result.current:
        raise DomainError("This result has been superseded by a later revision.", 409)
    deadline = result.published_at + timedelta(days=policy.appeal_window_days)
    if (now or utcnow()) > deadline:
        raise DomainError(f"The appeal window closed on {deadline.date().isoformat()}.", 409)
    if session.scalar(select(Appeal.id).where(Appeal.result_id == result_id, Appeal.status.in_(("open", "under_review")))):
        raise DomainError("An appeal for this result is already in progress.", 409)
    appeal = Appeal(id=new_id("apl"), tenant_id=tenant_id, result_id=result.id, student_id=student.id, offering_id=result.offering_id,
                    reason=reason, status="open", original_score=result.score, created_at=utcnow(), history=[])
    _history(appeal, "open", student.user_id or student.id, "Appeal submitted")
    session.add(appeal)
    return appeal


def review_appeal(appeal: Appeal, actor_user_id: str, note: str) -> Appeal:
    if appeal.status != "open":
        raise DomainError("Only open appeals can be moved to review.", 409)
    appeal.status, appeal.reviewer_user_id = "under_review", actor_user_id
    _history(appeal, "under_review", actor_user_id, note)
    return appeal


def decide_appeal(session, tenant_id: str, appeal: Appeal, actor_user_id: str, decision: str, note: str,
                  revised_score: float | None) -> Appeal:
    """Approval appends a new result revision; the original mark is kept for audit."""
    if appeal.status not in ("open", "under_review"):
        raise DomainError("This appeal has already been decided.", 409)
    if decision == "approved":
        if revised_score is None or not 0 <= revised_score <= 100:
            raise DomainError("A revised score between 0 and 100 is required to approve an appeal.", 422)
        current = fetch(session, Result, appeal.result_id, "Result")
        current.current = False
        session.flush()
        session.add(Result(id=new_id("res"), tenant_id=tenant_id, offering_id=current.offering_id, student_id=current.student_id,
                           score=round(revised_score, 2), letter=letter_for(revised_score), passed=revised_score >= PASS_MARK,
                           revision=current.revision + 1, current=True, reason=f"Grade appeal approved: {note}"[:160],
                           published_at=utcnow()))
        appeal.revised_score = round(revised_score, 2)
    elif decision != "rejected":
        raise DomainError("Decision must be approved or rejected.", 422)
    appeal.status, appeal.decision_note, appeal.reviewer_user_id, appeal.decided_at = decision, note, actor_user_id, utcnow()
    _history(appeal, decision, actor_user_id, note)
    return appeal
