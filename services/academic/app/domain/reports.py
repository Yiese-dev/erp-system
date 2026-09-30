from collections import Counter

from sqlalchemy import select

from packages.campus_common.database import utcnow
from packages.campus_common.pdf import render_pdf
from services.academic.app.models import (AttendanceRecord, AttendanceSession, Course, Enrollment, Offering, Program, Result,
                                          Student, Term)


def transcript(session, student: Student) -> dict:
    rows = session.execute(
        select(Result, Offering, Course, Term).join(Offering, Offering.id == Result.offering_id)
        .join(Course, Course.id == Offering.course_id).join(Term, Term.id == Offering.term_id)
        .where(Result.student_id == student.id, Result.current.is_(True)).order_by(Term.starts_on, Course.code)).all()
    terms: dict[str, dict] = {}
    attempted = earned = weighted = 0
    for result, offering, course, term in rows:
        bucket = terms.setdefault(term.id, {"term": term.name, "courses": []})
        bucket["courses"].append({"code": course.code, "title": course.title, "credits": course.credits,
                                  "score": result.score, "letter": result.letter, "passed": result.passed,
                                  "revision": result.revision})
        attempted += course.credits
        weighted += result.score * course.credits
        earned += course.credits if result.passed else 0
    program = session.get(Program, student.program_id)
    return {"student": {"id": student.id, "name": student.name, "student_no": student.student_no, "program": program.name},
            "terms": list(terms.values()), "credits_attempted": attempted, "credits_earned": earned,
            "average": round(weighted / attempted, 2) if attempted else None}


def transcript_pdf(institution: str, data: dict) -> bytes:
    student = data["student"]
    blocks = [("kv", [("Student", student["name"]), ("Student number", student["student_no"]), ("Programme", student["program"]),
                      ("Credits earned", f"{data['credits_earned']} of {data['credits_attempted']}"),
                      ("Credit-weighted average", "-" if data["average"] is None else f"{data['average']:.2f} / 100")])]
    for term in data["terms"]:
        blocks.append(("heading", term["term"]))
        blocks.append(("table", ["Code", "Course", "Credits", "Score", "Grade", "Status"],
                       [[c["code"], c["title"], c["credits"], f"{c['score']:.2f}", c["letter"],
                         ("Passed" if c["passed"] else "Failed") + (f" (rev. {c['revision']})" if c["revision"] > 1 else "")]
                        for c in term["courses"]]))
    if not data["terms"]:
        blocks.append(("text", "No results have been published for this student yet."))
    blocks.append(("text", "Grades: A 80-100, B 70-79, C 60-69, D 50-59, F below 50. Only published results appear on this transcript."))
    return render_pdf("Academic Transcript", institution, f"Official record for {student['name']}", blocks, utcnow())


def attendance_summary(session, offering: Offering) -> dict:
    course = session.get(Course, offering.course_id)
    term = session.get(Term, offering.term_id)
    sessions = session.scalars(select(AttendanceSession).where(AttendanceSession.offering_id == offering.id)).all()
    ids = [item.id for item in sessions]
    counts: dict[str, Counter] = {}
    for record in session.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_(ids))).all() if ids else []:
        counts.setdefault(record.student_id, Counter())[record.status] += 1
    students = session.execute(select(Student).join(Enrollment, Enrollment.student_id == Student.id)
                               .where(Enrollment.offering_id == offering.id, Enrollment.status == "enrolled").order_by(Student.name)).scalars().all()
    rows = []
    for student in students:
        tally = counts.get(student.id, Counter())
        countable = tally["present"] + tally["late"] + tally["absent"]
        rate = (tally["present"] + tally["late"]) / countable if countable else None
        rows.append({"student_no": student.student_no, "name": student.name, "present": tally["present"], "late": tally["late"],
                     "absent": tally["absent"], "excused": tally["excused"], "rate": rate})
    return {"course": f"{course.code} {course.title}", "term": term.name, "instructor": offering.instructor_name,
            "sessions": len(sessions), "rows": rows}


def attendance_pdf(institution: str, data: dict, threshold: float) -> bytes:
    flagged = sum(1 for row in data["rows"] if row["rate"] is not None and row["rate"] < threshold)
    blocks = [("kv", [("Course", data["course"]), ("Term", data["term"]), ("Instructor", data["instructor"]),
                      ("Sessions recorded", data["sessions"]), (f"Below {threshold:.0%} attendance", flagged)]),
              ("table", ["Student no.", "Name", "Present", "Late", "Absent", "Excused", "Rate"],
               [[row["student_no"], row["name"], row["present"], row["late"], row["absent"], row["excused"],
                 "n/a" if row["rate"] is None else f"{row['rate']:.0%}" + (" (below threshold)" if row["rate"] < threshold else "")]
                for row in data["rows"]]),
              ("text", "Late arrivals count as attended. Excused absences are excluded from the rate.")]
    return render_pdf("Attendance Summary", institution, f"{data['course']} | {data['term']}", blocks, utcnow())
