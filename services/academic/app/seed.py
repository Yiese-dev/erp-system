import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from packages.campus_common import demo
from packages.campus_common.database import LOCAL_TZ, Database, utcnow
from services.academic.app.domain import enrollment, exams, grading
from services.academic.app.models import (Assessment, Course, Offering, Policy, Prerequisite, Program, Registration, Result,
                                          Student, Term)

INSTRUCTORS = {"usr_instructor": "Dr. Samuel Fonkou", "usr_instructor2": "Dr. Grace Tabi"}
TEACHES = {"sen101": "usr_instructor", "sen201": "usr_instructor", "sen301": "usr_instructor", "sen102": "usr_instructor2",
           "sen202": "usr_instructor2", "bus101": "usr_instructor2", "bus102": "usr_instructor", "bus201": "usr_instructor2",
           "bus202": "usr_instructor", "sen150": "usr_instructor"}
SPRING = ["sen101", "sen102", "bus101", "bus102"]
FALL = ["sen101", "sen102", "sen201", "sen202", "bus101", "bus201", "bus202"]
FAILS_SEN101 = {5, 11}
LOW_ATTENDANCE = {3, 9, 19}
FAILING_FALL = {7, 21}
UNREGISTERED = demo.FALL_UNREGISTERED


def at(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=LOCAL_TZ)


def seed(database: Database) -> None:
    for tenant_id, slug, name in demo.TENANTS:
        with database.session(tenant_id) as session:
            if session.scalar(select(Program.id).limit(1)):
                continue
            seed_tenant(session, tenant_id, slug)


def seed_tenant(session, tenant: str, slug: str) -> None:
    rng = random.Random(f"academic-{slug}")
    session.add(Policy(id=f"pol_{slug}", tenant_id=tenant, attendance_threshold=0.75, failing_score=50, consecutive_failures=2,
                       appeal_window_days=14, updated_at=utcnow()))
    programs = {}
    for key, (code, title, _) in demo.PROGRAMS.items():
        programs[key] = Program(id=f"prg_{slug}_{key}", tenant_id=tenant, code=code, name=title, level="Bachelor", duration_terms=6, active=True)
        session.add(programs[key])
    session.flush()
    courses = {}
    catalogue = {**demo.COURSES, "sen150": ("se", "SEN150", "Technical Writing for Engineers", 2, [])}
    for key, (program, code, title, credits, _) in catalogue.items():
        courses[key] = Course(id=f"crs_{slug}_{key}", tenant_id=tenant, program_id=programs[program].id, code=code, title=title,
                              credits=credits, active=True)
        session.add(courses[key])
    session.flush()
    for key, (*_, requires) in catalogue.items():
        for prerequisite in requires:
            enrollment.add_prerequisite(session, tenant, courses[key].id, courses[prerequisite].id)
    terms = {}
    for key, (label, starts, ends) in {**demo.TERMS, "2026u": ("2026 Summer School", "2026-07-13", "2026-09-18")}.items():
        terms[key] = Term(id=f"trm_{slug}_{key}", tenant_id=tenant, name=label, starts_on=date.fromisoformat(starts),
                          ends_on=date.fromisoformat(ends), status="active" if key == "2026f" else "closed")
        session.add(terms[key])
    session.flush()

    def offer(course: str, term: str, room: str) -> Offering:
        teacher = TEACHES[course]
        row = Offering(id=f"off_{slug}_{term}_{course}", tenant_id=tenant, course_id=courses[course].id, term_id=terms[term].id,
                       instructor_user_id=teacher, instructor_name=INSTRUCTORS[teacher], room=room, capacity=40, results_status="draft")
        session.add(row)
        return row

    rooms = ["Hall A", "Hall B", "Lab 1", "Lab 2", "Room 204", "Room 108", "Hall C"]
    spring = {course: offer(course, "2026s", rooms[index]) for index, course in enumerate(SPRING)}
    summer = {"sen150": offer("sen150", "2026u", "Room 108")}
    fall = {course: offer(course, "2026f", rooms[index]) for index, course in enumerate(FALL)}
    session.flush()

    students = []
    for index, full_name in enumerate(demo.STUDENT_NAMES):
        program = "se" if index < 16 else "ba"
        students.append(Student(id=f"stu_{slug}_{index:02d}", tenant_id=tenant, user_id="usr_student" if index == 0 else None,
                                student_no=f"{slug[:3].upper()}25{index + 1:04d}", name=full_name,
                                email=demo.email_for(full_name, slug), program_id=programs[program].id, status="active",
                                admitted_on=date(2025, 10, 6)))
    session.add_all(students)
    session.flush()
    ability = {index: 38 if index in FAILS_SEN101 else (76 if index == 0 else rng.randint(52, 88)) for index in range(len(students))}

    def score(index: int, spread: float = 8) -> float:
        return round(min(98, max(12, ability[index] + rng.gauss(0, spread))), 1)

    def register(index: int, term: str, keys: list[str], offerings: dict[str, Offering], emit: bool) -> Registration:
        student = students[index]
        if emit:
            return enrollment.register_student(session, tenant, student.id, terms[term].id, [offerings[key].id for key in keys],
                                               registration_id=f"reg_{slug}_{term}_{index:02d}")
        registration = Registration(id=f"reg_{slug}_{term}_{index:02d}", tenant_id=tenant, student_id=student.id,
                                    program_id=student.program_id, term_id=terms[term].id, status="confirmed",
                                    billing_status="paid", invoice_number=None,
                                    created_at=datetime.combine(terms[term].starts_on, datetime.min.time(), LOCAL_TZ))
        session.add(registration)
        session.flush()
        for key in keys:
            enrollment.enroll(session, tenant, registration, offerings[key].id)
        return registration

    for index in range(len(students)):
        register(index, "2026s", ["sen101", "sen102"] if index < 16 else ["bus101", "bus102"], spring, emit=False)
    summer_students = demo.SUMMER_STUDENTS
    for index in summer_students:
        register(index, "2026u", ["sen150"], summer, emit=False)

    spring_dates = [date(2026, 2, 10) + timedelta(days=7 * week) for week in range(12)]
    for offering in spring.values():
        plan = [("Continuous assessment", 30, date(2026, 3, 20)), ("Midterm exam", 30, date(2026, 4, 17)), ("Final exam", 40, date(2026, 6, 19))]
        enrolled = sorted(grading.enrolled_students(session, offering.id))
        for label, weight, held in plan:
            assessment = grading.add_assessment(session, tenant, offering, label, weight, held)
            session.flush()
            grading.record_grades(session, tenant, offering.instructor_user_id, assessment,
                                  [(sid, score(int(sid[-2:]))) for sid in enrolled])
        for day in spring_dates:
            grading.record_attendance(session, tenant, offering, day, "Lecture", [
                (sid, "present" if rng.random() > 0.1 else rng.choice(["late", "absent", "excused"])) for sid in enrolled])
        grading.publish_results(session, tenant, offering)
        offering.published_at = at("2026-06-30", 10)
    for offering in summer.values():
        enrolled = sorted(grading.enrolled_students(session, offering.id))
        for label, weight, held in [("Portfolio", 60, date(2026, 8, 21)), ("Final report", 40, date(2026, 9, 11))]:
            assessment = grading.add_assessment(session, tenant, offering, label, weight, held)
            session.flush()
            grading.record_grades(session, tenant, offering.instructor_user_id, assessment, [(sid, score(int(sid[-2:]), 6)) for sid in enrolled])
        grading.publish_results(session, tenant, offering)
        offering.published_at = utcnow() - timedelta(days=3)
    session.flush()
    for result in session.scalars(select(Result)).all():
        offering = session.get(Offering, result.offering_id)
        result.published_at = offering.published_at
    session.flush()

    for index in range(len(students)):
        if index in UNREGISTERED:
            continue
        track = "ba" if index >= 16 else "se"
        passed = enrollment.passed_courses(session, students[index].id)
        wanted = ["bus201", "bus202"] if track == "ba" else ["sen201", "sen202"]
        keys = [key for key in wanted if all(courses[need].id in passed for need in catalogue[key][4])]
        keys += [key for key in ("sen101", "sen102", "bus101") if catalogue[key][0] == track and courses[key].id not in passed]
        register(index, "2026f", keys, fall, emit=True)
    fall_dates = [date(2026, 9, day) for day in (8, 10, 15, 17, 22, 24, 29)]
    for key, offering in fall.items():
        enrolled = sorted(grading.enrolled_students(session, offering.id))
        if not enrolled:
            continue
        plan = [("CA 1", 15, date(2026, 9, 21)), ("CA 2", 15, date(2026, 9, 28)), ("Midterm exam", 30, date(2026, 10, 20)),
                ("Final exam", 40, date(2027, 1, 15))]
        for label, weight, held in plan:
            assessment = grading.add_assessment(session, tenant, offering, label, weight, held)
            session.flush()
            if held <= date(2026, 9, 29):
                grading.record_grades(session, tenant, offering.instructor_user_id, assessment, [
                    (sid, round(rng.uniform(30, 46), 1) if int(sid[-2:]) in FAILING_FALL else score(int(sid[-2:])))
                    for sid in enrolled])
        for day in fall_dates:
            records = []
            for sid in enrolled:
                index = int(sid[-2:])
                if index in LOW_ATTENDANCE:
                    status = "absent" if rng.random() < 0.45 else "present"
                else:
                    status = "present" if rng.random() > 0.08 else rng.choice(["late", "excused"])
                records.append((sid, status))
            grading.record_attendance(session, tenant, offering, day, "Lecture", records)
    session.flush()

    slots = [("sen201", "2026-10-19", 9, "Hall A", "usr_instructor"), ("sen202", "2026-10-20", 9, "Hall A", "usr_instructor2"),
             ("sen101", "2026-10-21", 9, "Hall B", "usr_instructor"), ("sen102", "2026-10-21", 14, "Hall B", "usr_instructor2"),
             ("bus201", "2026-10-22", 9, "Hall C", "usr_instructor2"), ("bus202", "2026-10-23", 9, "Hall C", "usr_instructor"),
             ("bus101", "2026-10-23", 14, "Room 204", "usr_instructor2")]
    for key, day, hour, room, invigilator in slots:
        exams.schedule_exam(session, tenant, fall[key], f"{courses[key].code} Midterm", room, invigilator, INSTRUCTORS[invigilator],
                            at(day, hour), at(day, hour + 2))
    session.flush()

    first = session.scalar(select(Result).where(Result.student_id == students[2].id, Result.offering_id == summer["sen150"].id))
    appeal = grading.submit_appeal(session, tenant, students[2], first.id,
                                   "My final report grade does not reflect the rubric feedback I received on sections 3 and 4.",
                                   session.scalar(select(Policy)))
    session.flush()
    grading.review_appeal(appeal, "usr_instructor", "Second marker assigned")
    assert session.scalar(select(Prerequisite).limit(1)) is not None
    assert session.scalar(select(Assessment).limit(1)) is not None
