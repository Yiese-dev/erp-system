from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from packages.campus_common.config import Settings, load_settings
from packages.campus_common.database import LOCAL_TZ, Database, fetch, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.http import create_application
from packages.campus_common.schemas import Page, as_dict, out_schema, paginate_rows
from packages.campus_common.security import Actor, current_actor
from services.hr.app.domain import attendance, operations, payroll
from services.hr.app.domain.notifications import notify, visible
from services.hr.app.models import (Applicant, Asset, AssetAssignment, AttendanceLog, Base, Department, Employee, InventoryItem,
                                    LeaveBalance, LeaveRequest, Notification, PayrollRun, Payslip, Review, RuleSet, StockMovement, Vacancy)

READ = ("hr:read", "hr:write")
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class EmployeeIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(max_length=254, pattern=EMAIL)
    phone: str = Field("", max_length=20)
    department_id: str = Field(max_length=64)
    position: str = Field(min_length=2, max_length=120)
    base_salary: int = Field(gt=0, le=20_000_000)
    allowances: int = Field(0, ge=0, le=20_000_000)
    hired_on: date
    user_id: str | None = Field(None, max_length=64)


class EmployeePatch(BaseModel):
    department_id: str | None = Field(None, max_length=64)
    position: str | None = Field(None, min_length=2, max_length=120)
    base_salary: int | None = Field(None, gt=0, le=20_000_000)
    allowances: int | None = Field(None, ge=0, le=20_000_000)
    status: Literal["active", "suspended", "terminated"] | None = None
    user_id: str | None = Field(None, max_length=64)


class VacancyIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    department_id: str = Field(max_length=64)
    openings: int = Field(1, ge=1, le=50)
    description: str = Field("", max_length=4000)


class ApplicantIn(BaseModel):
    vacancy_id: str = Field(max_length=64)
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(max_length=254, pattern=EMAIL)
    phone: str = Field("", max_length=20)


class StageIn(BaseModel):
    stage: Literal["screened", "interview", "offered", "hired", "rejected"]
    offered_salary: int | None = Field(None, gt=0, le=20_000_000)
    start_date: date | None = None


class RuleSetIn(BaseModel):
    name: str = Field(min_length=5, max_length=160)
    effective_from: date
    rules: dict[str, Any]
    sources: list[dict[str, str]] = Field(min_length=1, max_length=10)


class ApproveIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class RunIn(BaseModel):
    period: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")


class PreviewIn(BaseModel):
    base_salary: int = Field(gt=0, le=20_000_000)
    allowances: int = Field(0, ge=0, le=20_000_000)
    rule_set_id: str | None = Field(None, max_length=64)


class KioskIn(BaseModel):
    kiosk: str = Field("Main entrance", min_length=2, max_length=80)


class CheckInIn(BaseModel):
    token: str | None = Field(None, max_length=200)
    code: str | None = Field(None, min_length=6, max_length=6)


class LeaveIn(BaseModel):
    kind: Literal["annual", "sick", "compassionate"]
    starts_on: date
    ends_on: date
    reason: str = Field("", max_length=1000)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field("", max_length=500)


class ReviewIn(BaseModel):
    employee_id: str = Field(max_length=64)
    period: str = Field(pattern=r"^20\d{2}-(H1|H2|Q[1-4])$")
    goals: str = Field(min_length=5, max_length=4000)


class ReviewPatch(BaseModel):
    goals: str | None = Field(None, min_length=5, max_length=4000)
    rating: int | None = Field(None, ge=1, le=5)
    comments: str | None = Field(None, max_length=4000)
    status: Literal["draft", "completed"] | None = None


class AssetIn(BaseModel):
    tag: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=160)
    category: Literal["laptop", "desktop", "projector", "printer", "vehicle", "furniture", "network", "other"]
    serial: str = Field("", max_length=80)
    location: str = Field(min_length=2, max_length=80)
    purchased_on: date
    value: int = Field(ge=0, le=500_000_000)


class AssignIn(BaseModel):
    employee_id: str = Field(max_length=64)
    note: str = Field("", max_length=300)


class ReturnIn(BaseModel):
    condition: Literal["good", "fair", "poor"]


class AssetStatusIn(BaseModel):
    status: Literal["available", "maintenance", "retired"]


class ItemIn(BaseModel):
    sku: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=160)
    unit: str = Field(min_length=1, max_length=20)
    quantity: int = Field(0, ge=0, le=1_000_000)
    reorder_level: int = Field(0, ge=0, le=1_000_000)


class MovementIn(BaseModel):
    delta: int = Field(ge=-100_000, le=100_000)
    reason: str = Field(min_length=3, max_length=200)


EmployeeOut = out_schema(Employee, department=(str, ""))
VacancyOut = out_schema(Vacancy, department=(str, ""), applicants=(int, 0))
ApplicantOut = out_schema(Applicant)
RuleSetOut = out_schema(RuleSet)
RunOut = out_schema(PayrollRun)
PayslipOut = out_schema(Payslip)
LeaveOut = out_schema(LeaveRequest, employee_name=(str, ""), department=(str, ""))
ReviewOut = out_schema(Review, employee_name=(str, ""), department=(str, ""))
AssetOut = out_schema(Asset, assignee=(str | None, None))
ItemOut = out_schema(InventoryItem, low=(bool, False))
NotificationOut = out_schema(Notification, exclude=("dedupe_key", "recipient_email"))


def employee_names(session, ids: set[str]) -> dict[str, tuple[str, str]]:
    if not ids:
        return {}
    rows = session.execute(select(Employee.id, Employee.name, Department.name).join(Department, Department.id == Employee.department_id)
                           .where(Employee.id.in_(ids))).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def leave_views(session, rows: list[LeaveRequest]) -> list[dict]:
    names = employee_names(session, {row.employee_id for row in rows})
    return [as_dict(row, employee_name=names.get(row.employee_id, ("", ""))[0], department=names.get(row.employee_id, ("", ""))[1]) for row in rows]


def review_views(session, rows: list[Review]) -> list[dict]:
    names = employee_names(session, {row.employee_id for row in rows})
    return [as_dict(row, employee_name=names.get(row.employee_id, ("", ""))[0], department=names.get(row.employee_id, ("", ""))[1]) for row in rows]


def asset_views(session, rows: list[Asset]) -> list[dict]:
    names = employee_names(session, {row.employee_id for row in rows if row.employee_id})
    return [as_dict(row, assignee=names[row.employee_id][0] if row.employee_id in names else None) for row in rows]


def create_app(settings: Settings):
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        if settings.create_schema:
            database.create_all(Base.metadata)
        yield
        database.engine.dispose()

    app = create_application(settings, database, lifespan)
    p = "/api/v1/hr"

    def scoped(actor: Actor):
        return database.session(actor.tenant_id)

    def me(session, actor: Actor) -> Employee:
        employee = session.scalar(select(Employee).where(Employee.user_id == actor.user_id))
        if employee is None:
            raise DomainError("No employee record is linked to your account in this institution.", 404)
        return employee

    # ---------- Organisation ----------
    @app.get(f"{p}/departments", tags=["Organisation"])
    def departments(actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        actor.require(*READ)
        with scoped(actor) as session:
            counts = dict(session.execute(select(Employee.department_id, func.count()).where(Employee.status == "active")
                                          .group_by(Employee.department_id)).all())
            return [{**as_dict(row), "headcount": counts.get(row.id, 0)} for row in session.scalars(select(Department).order_by(Department.name)).all()]

    @app.post(f"{p}/departments", status_code=201, tags=["Organisation"])
    def create_department(payload: DepartmentIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("hr:write")
        with scoped(actor) as session:
            department = Department(id=new_id("dep"), tenant_id=actor.tenant_id, name=payload.name)
            session.add(department)
            session.flush()
            return as_dict(department)

    @app.get(f"{p}/employees", response_model=Page[EmployeeOut], tags=["Employees"])
    def list_employees(q: str = "", department_id: str = "", status: str = "active", page: int = 1, size: int = 25,
                       actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Employee, Department).join(Department, Department.id == Employee.department_id).order_by(Employee.name)
            if q:
                query = query.where(or_(Employee.name.ilike(f"%{q}%"), Employee.employee_no.ilike(f"%{q}%"), Employee.position.ilike(f"%{q}%")))
            if department_id:
                query = query.where(Employee.department_id == department_id)
            if status:
                query = query.where(Employee.status == status)
            return paginate_rows(session, query, page, size, lambda employee, department: as_dict(employee, department=department.name))

    @app.post(f"{p}/employees", response_model=EmployeeOut, status_code=201, tags=["Employees"])
    def create_employee(payload: EmployeeIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            employee = operations.hire(session, actor.tenant_id, **payload.model_dump())
            return as_dict(employee, department=session.get(Department, employee.department_id).name)

    @app.get(f"{p}/employees/{{employee_id}}", tags=["Employees"])
    def employee_detail(employee_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            return profile(session, fetch(session, Employee, employee_id, "Employee"), include_drafts=True)

    @app.patch(f"{p}/employees/{{employee_id}}", response_model=EmployeeOut, tags=["Employees"])
    def update_employee(employee_id: str, payload: EmployeePatch, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            employee = fetch(session, Employee, employee_id, "Employee")
            changes = payload.model_dump(exclude_unset=True)
            if "department_id" in changes:
                fetch(session, Department, changes["department_id"], "Department")
            for key, value in changes.items():
                setattr(employee, key, value)
            return as_dict(employee, department=session.get(Department, employee.department_id).name)

    def profile(session, employee: Employee, include_drafts: bool) -> dict[str, Any]:
        year = local_now().year
        for kind in operations.ENTITLEMENTS:
            operations.balance_for(session, employee.tenant_id, employee.id, year, kind)
        balances = session.scalars(select(LeaveBalance).where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == year)).all()
        requests = session.scalars(select(LeaveRequest).where(LeaveRequest.employee_id == employee.id).order_by(LeaveRequest.starts_on.desc()).limit(20)).all()
        slips = select(Payslip, PayrollRun).join(PayrollRun, PayrollRun.id == Payslip.run_id).where(Payslip.employee_id == employee.id)
        if not include_drafts:
            slips = slips.where(PayrollRun.status == "finalized")
        payslips = [{**as_dict(slip), "run_status": run.status} for slip, run in session.execute(slips.order_by(Payslip.period.desc()).limit(12)).all()]
        since = local_now().date() - timedelta(days=30)
        logs = session.scalars(select(AttendanceLog).where(AttendanceLog.employee_id == employee.id, AttendanceLog.work_date >= since)
                               .order_by(AttendanceLog.work_date.desc())).all()
        reviews = session.scalars(select(Review).where(Review.employee_id == employee.id).order_by(Review.period.desc())).all()
        if not include_drafts:
            reviews = [review for review in reviews if review.status == "completed"]
        assets = session.scalars(select(Asset).where(Asset.employee_id == employee.id)).all()
        today = local_now().date()
        return {"employee": as_dict(employee, department=session.get(Department, employee.department_id).name),
                "balances": [{**as_dict(row), "pending": operations.pending_days(session, employee.id, row.kind, year),
                              "available": row.entitled - row.used} for row in balances],
                "leave": leave_views(session, list(requests)), "payslips": payslips,
                "attendance": [as_dict(row) for row in logs], "today": next((as_dict(row) for row in logs if row.work_date == today), None),
                "reviews": review_views(session, list(reviews)), "assets": asset_views(session, list(assets))}

    @app.get(f"{p}/me", tags=["Self service"])
    def my_profile(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("hr:self")
        with scoped(actor) as session:
            return profile(session, me(session, actor), include_drafts=False)

    # ---------- Recruitment ----------
    @app.get(f"{p}/recruitment/vacancies", response_model=list[VacancyOut], tags=["Recruitment"])
    def vacancies(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            counts = dict(session.execute(select(Applicant.vacancy_id, func.count()).group_by(Applicant.vacancy_id)).all())
            departments = dict(session.execute(select(Department.id, Department.name)).all())
            return [as_dict(row, department=departments.get(row.department_id, ""), applicants=counts.get(row.id, 0))
                    for row in session.scalars(select(Vacancy).order_by(Vacancy.created_at.desc())).all()]

    @app.post(f"{p}/recruitment/vacancies", response_model=VacancyOut, status_code=201, tags=["Recruitment"])
    def create_vacancy(payload: VacancyIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            department = fetch(session, Department, payload.department_id, "Department")
            vacancy = Vacancy(id=new_id("vac"), tenant_id=actor.tenant_id, status="open", created_at=utcnow(), **payload.model_dump())
            session.add(vacancy)
            session.flush()
            return as_dict(vacancy, department=department.name, applicants=0)

    @app.get(f"{p}/recruitment/applicants", response_model=list[ApplicantOut], tags=["Recruitment"])
    def applicants(vacancy_id: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Applicant).order_by(Applicant.updated_at.desc())
            if vacancy_id:
                query = query.where(Applicant.vacancy_id == vacancy_id)
            return [as_dict(row) for row in session.scalars(query).all()]

    @app.post(f"{p}/recruitment/applicants", response_model=ApplicantOut, status_code=201, tags=["Recruitment"])
    def create_applicant(payload: ApplicantIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            if fetch(session, Vacancy, payload.vacancy_id, "Vacancy").status != "open":
                raise DomainError("This vacancy is no longer open.", 409)
            now = utcnow()
            applicant = Applicant(id=new_id("apl"), tenant_id=actor.tenant_id, stage="applied", applied_at=now, updated_at=now,
                                  history=[{"stage": "applied", "by": actor.user_id, "at": now.isoformat()}],
                                  **{**payload.model_dump(), "email": payload.email.lower()})
            session.add(applicant)
            session.flush()
            return as_dict(applicant)

    @app.post(f"{p}/recruitment/applicants/{{applicant_id}}/stage", response_model=ApplicantOut, tags=["Recruitment"])
    def advance(applicant_id: str, payload: StageIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            applicant = operations.advance_applicant(session, actor.tenant_id, fetch(session, Applicant, applicant_id, "Applicant"),
                                                     payload.stage, actor.user_id, payload.offered_salary, payload.start_date)
            return as_dict(applicant)

    # ---------- Payroll ----------
    @app.get(f"{p}/payroll/rule-sets", response_model=list[RuleSetOut], tags=["Payroll"])
    def rule_sets(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            return [as_dict(row) for row in session.scalars(select(RuleSet).order_by(RuleSet.effective_from.desc(), RuleSet.created_at.desc())).all()]

    @app.post(f"{p}/payroll/rule-sets", response_model=RuleSetOut, status_code=201, tags=["Payroll"])
    def create_rule_set(payload: RuleSetIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            rule_set = RuleSet(id=new_id("rul"), tenant_id=actor.tenant_id, name=payload.name, effective_from=payload.effective_from,
                               status="draft", rules=payroll.validate_rules(payload.rules), sources=payload.sources, created_at=utcnow())
            session.add(rule_set)
            session.flush()
            return as_dict(rule_set)

    @app.post(f"{p}/payroll/rule-sets/{{rule_set_id}}/approve", response_model=RuleSetOut, tags=["Payroll"])
    def approve_rules(rule_set_id: str, payload: ApproveIn, actor: Actor = Depends(current_actor)):
        """Approval records who verified the statutory rates against which official publication."""
        actor.require("hr:write")
        with scoped(actor) as session:
            return as_dict(payroll.approve_rule_set(session, fetch(session, RuleSet, rule_set_id, "Rule set"), actor.user_id, payload.note))

    @app.post(f"{p}/payroll/preview", tags=["Payroll"])
    def preview(payload: PreviewIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            if payload.rule_set_id:
                rule_set = fetch(session, RuleSet, payload.rule_set_id, "Rule set")
            else:
                rule_set = session.scalar(select(RuleSet).where(RuleSet.status.in_(("approved", "draft"))).order_by(RuleSet.status, RuleSet.effective_from.desc()))
                if rule_set is None:
                    raise DomainError("No payroll rule set exists yet.", 409)
            return {"rule_set": {"id": rule_set.id, "name": rule_set.name, "status": rule_set.status},
                    **payroll.calculate(payload.base_salary, payload.allowances, rule_set.rules)}

    @app.get(f"{p}/payroll/runs", response_model=list[RunOut], tags=["Payroll"])
    def runs(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            return [as_dict(row) for row in session.scalars(select(PayrollRun).order_by(PayrollRun.period.desc())).all()]

    @app.post(f"{p}/payroll/runs", response_model=RunOut, status_code=201, tags=["Payroll"])
    def create_run(payload: RunIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            return as_dict(payroll.create_run(session, actor.tenant_id, payload.period, actor.user_id))

    @app.get(f"{p}/payroll/runs/{{run_id}}", tags=["Payroll"])
    def run_detail(run_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            run = fetch(session, PayrollRun, run_id, "Payroll run")
            slips = session.scalars(select(Payslip).where(Payslip.run_id == run.id).order_by(Payslip.employee_name)).all()
            return {"run": as_dict(run), "rule_set": as_dict(session.get(RuleSet, run.rule_set_id)), "payslips": [as_dict(row) for row in slips]}

    @app.post(f"{p}/payroll/runs/{{run_id}}/finalize", response_model=RunOut, tags=["Payroll"])
    def finalize(run_id: str, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            return as_dict(payroll.finalize_run(session, actor.tenant_id, fetch(session, PayrollRun, run_id, "Payroll run"), actor.user_id))

    @app.delete(f"{p}/payroll/runs/{{run_id}}", status_code=204, tags=["Payroll"])
    def discard(run_id: str, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            payroll.discard_run(session, fetch(session, PayrollRun, run_id, "Payroll run"))

    @app.get(f"{p}/payslips/{{payslip_id}}.pdf", tags=["Payroll"], response_class=Response)
    def payslip_pdf(payslip_id: str, actor: Actor = Depends(current_actor)):
        with scoped(actor) as session:
            slip = fetch(session, Payslip, payslip_id, "Payslip")
            run = session.get(PayrollRun, slip.run_id)
            employee = session.get(Employee, slip.employee_id)
            if not actor.can(*READ) and (employee.user_id != actor.user_id or run.status != "finalized"):
                raise DomainError("Payslip not found.", 404)
            content = payroll.payslip_pdf(actor.tenant_name or "Campus ERP", slip, employee, session.get(RuleSet, run.rule_set_id))
            return Response(content, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="payslip-{employee.employee_no}-{slip.period}.pdf"'})

    # ---------- Attendance ----------
    @app.post(f"{p}/attendance/challenges", status_code=201, tags=["Attendance"])
    def challenge(payload: KioskIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        """Kiosk mode: rotating signed QR challenge valid for 60 seconds."""
        actor.require("hr:write")
        with scoped(actor) as session:
            record, token = attendance.issue_challenge(session, actor.tenant_id, payload.kiosk, actor.user_id, settings.qr_secret)
            return {"id": record.id, "code": record.code, "kiosk": record.kiosk, "expires_at": record.expires_at.isoformat(),
                    "seconds": attendance.CHALLENGE_SECONDS, "token": token, "qr": attendance.qr_data_url(token)}

    @app.post(f"{p}/attendance/check-in", tags=["Attendance"])
    def check_in(payload: CheckInIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("hr:self")
        with scoped(actor) as session:
            action, log = attendance.check_in(session, actor.tenant_id, me(session, actor), settings.qr_secret, payload.token, payload.code)
            return {"action": action, "log": as_dict(log)}

    @app.get(f"{p}/attendance", tags=["Attendance"])
    def attendance_log(day: date | None = None, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            target = day or local_now().date()
            employees = session.execute(select(Employee, Department).join(Department, Department.id == Employee.department_id)
                                        .where(Employee.status == "active").order_by(Employee.name)).all()
            logs = {row.employee_id: row for row in session.scalars(select(AttendanceLog).where(AttendanceLog.work_date == target)).all()}
            leave = {row.employee_id for row in session.scalars(select(LeaveRequest).where(LeaveRequest.status == "approved",
                                                                                          LeaveRequest.starts_on <= target,
                                                                                          LeaveRequest.ends_on >= target)).all()}
            rows = []
            for employee, department in employees:
                log = logs.get(employee.id)
                state = "on_leave" if employee.id in leave else ("present" if log else "absent")
                rows.append({"employee_id": employee.id, "name": employee.name, "department": department.name, "status": state,
                             "check_in_at": log.check_in_at.isoformat() if log else None,
                             "check_out_at": log.check_out_at.isoformat() if log and log.check_out_at else None,
                             "method": log.method if log else None})
            return {"date": target.isoformat(), "rows": rows, "present": sum(row["status"] == "present" for row in rows),
                    "on_leave": len(leave), "headcount": len(rows)}

    # ---------- Leave ----------
    @app.get(f"{p}/leave", response_model=list[LeaveOut], tags=["Leave"])
    def list_leave(status: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*READ, "hr:self")
        with scoped(actor) as session:
            query = select(LeaveRequest).order_by(LeaveRequest.created_at.desc()).limit(200)
            if status:
                query = query.where(LeaveRequest.status == status)
            if not actor.can(*READ):
                query = query.where(LeaveRequest.employee_id == me(session, actor).id)
            return leave_views(session, list(session.scalars(query).all()))

    @app.post(f"{p}/leave", response_model=LeaveOut, status_code=201, tags=["Leave"])
    def request_leave(payload: LeaveIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:self")
        with scoped(actor) as session:
            request = operations.request_leave(session, actor.tenant_id, me(session, actor), payload.kind, payload.starts_on, payload.ends_on,
                                               payload.reason, settings.hr_mailbox)
            return leave_views(session, [request])[0]

    @app.post(f"{p}/leave/{{request_id}}/decision", response_model=LeaveOut, tags=["Leave"])
    def decide(request_id: str, payload: DecisionIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            request = operations.decide_leave(session, actor.tenant_id, fetch(session, LeaveRequest, request_id, "Leave request"),
                                              actor.user_id, payload.decision, payload.note)
            return leave_views(session, [request])[0]

    @app.post(f"{p}/leave/{{request_id}}/cancel", response_model=LeaveOut, tags=["Leave"])
    def cancel(request_id: str, actor: Actor = Depends(current_actor)):
        actor.require("hr:self")
        with scoped(actor) as session:
            request = operations.cancel_leave(session, actor.tenant_id, fetch(session, LeaveRequest, request_id, "Leave request"), me(session, actor))
            return leave_views(session, [request])[0]

    # ---------- Performance ----------
    @app.get(f"{p}/reviews", response_model=list[ReviewOut], tags=["Performance"])
    def reviews(period: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Review).order_by(Review.period.desc(), Review.created_at.desc())
            if period:
                query = query.where(Review.period == period)
            return review_views(session, list(session.scalars(query).all()))

    @app.post(f"{p}/reviews", response_model=ReviewOut, status_code=201, tags=["Performance"])
    def create_review(payload: ReviewIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            employee = fetch(session, Employee, payload.employee_id, "Employee")
            if employee.user_id == actor.user_id:
                raise DomainError("You cannot review yourself.", 403)
            review = Review(id=new_id("rev"), tenant_id=actor.tenant_id, employee_id=employee.id, period=payload.period, goals=payload.goals,
                            comments="", reviewer_user_id=actor.user_id, reviewer_name=actor.name or actor.user_id, status="draft", created_at=utcnow())
            session.add(review)
            session.flush()
            return review_views(session, [review])[0]

    @app.patch(f"{p}/reviews/{{review_id}}", response_model=ReviewOut, tags=["Performance"])
    def update_review(review_id: str, payload: ReviewPatch, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            review = fetch(session, Review, review_id, "Review")
            if review.status == "completed":
                raise DomainError("Completed reviews are locked.", 409)
            for key, value in payload.model_dump(exclude_unset=True, exclude={"status"}).items():
                setattr(review, key, value)
            if payload.status == "completed":
                if review.rating is None:
                    raise DomainError("Add a rating from 1 to 5 before completing the review.", 422)
                review.status, review.completed_at = "completed", utcnow()
                employee = session.get(Employee, review.employee_id)
                if employee.user_id:
                    notify(session, actor.tenant_id, f"review-completed:{review.id}", f"Performance review {review.period} completed",
                           f"Your {review.period} review has been completed with a rating of {review.rating}/5.", "performance",
                           user_id=employee.user_id, email=employee.email, link="/hr/me")
            return review_views(session, [review])[0]

    # ---------- Assets and inventory ----------
    @app.get(f"{p}/assets", response_model=list[AssetOut], tags=["Assets"])
    def assets(status: str = "", q: str = "", actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            query = select(Asset).order_by(Asset.tag)
            if status:
                query = query.where(Asset.status == status)
            if q:
                query = query.where(or_(Asset.tag.ilike(f"%{q}%"), Asset.name.ilike(f"%{q}%"), Asset.serial.ilike(f"%{q}%")))
            return asset_views(session, list(session.scalars(query).all()))

    @app.post(f"{p}/assets", response_model=AssetOut, status_code=201, tags=["Assets"])
    def create_asset(payload: AssetIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            asset = Asset(id=new_id("ast"), tenant_id=actor.tenant_id, condition="good", status="available",
                          **{**payload.model_dump(), "tag": payload.tag.upper()})
            session.add(asset)
            session.flush()
            return asset_views(session, [asset])[0]

    @app.post(f"{p}/assets/{{asset_id}}/assign", response_model=AssetOut, tags=["Assets"])
    def assign(asset_id: str, payload: AssignIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            return asset_views(session, [operations.assign_asset(session, actor.tenant_id, asset_id, payload.employee_id, payload.note)])[0]

    @app.post(f"{p}/assets/{{asset_id}}/return", response_model=AssetOut, tags=["Assets"])
    def give_back(asset_id: str, payload: ReturnIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            return asset_views(session, [operations.return_asset(session, asset_id, payload.condition)])[0]

    @app.post(f"{p}/assets/{{asset_id}}/status", response_model=AssetOut, tags=["Assets"])
    def asset_status(asset_id: str, payload: AssetStatusIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            return asset_views(session, [operations.change_asset_status(fetch(session, Asset, asset_id, "Asset"), payload.status)])[0]

    @app.get(f"{p}/assets/{{asset_id}}/history", tags=["Assets"])
    def asset_history(asset_id: str, actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        actor.require(*READ)
        with scoped(actor) as session:
            fetch(session, Asset, asset_id, "Asset")
            rows = session.scalars(select(AssetAssignment).where(AssetAssignment.asset_id == asset_id).order_by(AssetAssignment.assigned_at.desc())).all()
            names = employee_names(session, {row.employee_id for row in rows})
            return [{**as_dict(row), "employee_name": names.get(row.employee_id, ("", ""))[0]} for row in rows]

    @app.get(f"{p}/inventory", response_model=list[ItemOut], tags=["Inventory"])
    def inventory(actor: Actor = Depends(current_actor)):
        actor.require(*READ)
        with scoped(actor) as session:
            return [as_dict(row, low=row.quantity <= row.reorder_level) for row in session.scalars(select(InventoryItem).order_by(InventoryItem.name)).all()]

    @app.post(f"{p}/inventory", response_model=ItemOut, status_code=201, tags=["Inventory"])
    def create_item(payload: ItemIn, actor: Actor = Depends(current_actor)):
        actor.require("hr:write")
        with scoped(actor) as session:
            item = InventoryItem(id=new_id("itm"), tenant_id=actor.tenant_id, **{**payload.model_dump(), "sku": payload.sku.upper(), "quantity": 0})
            session.add(item)
            session.flush()
            if payload.quantity:
                operations.record_movement(session, actor.tenant_id, item.id, payload.quantity, "Opening stock", actor.user_id)
            return as_dict(item, low=item.quantity <= item.reorder_level)

    @app.post(f"{p}/inventory/{{item_id}}/movements", status_code=201, tags=["Inventory"])
    def move_stock(item_id: str, payload: MovementIn, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require("hr:write")
        with scoped(actor) as session:
            movement = operations.record_movement(session, actor.tenant_id, item_id, payload.delta, payload.reason, actor.user_id)
            item = session.get(InventoryItem, item_id)
            return {"movement": as_dict(movement), "item": as_dict(item, low=item.quantity <= item.reorder_level)}

    @app.get(f"{p}/inventory/{{item_id}}/movements", tags=["Inventory"])
    def movements(item_id: str, actor: Actor = Depends(current_actor)) -> list[dict[str, Any]]:
        actor.require(*READ)
        with scoped(actor) as session:
            fetch(session, InventoryItem, item_id, "Inventory item")
            return [as_dict(row) for row in session.scalars(select(StockMovement).where(StockMovement.item_id == item_id)
                                                           .order_by(StockMovement.created_at.desc()).limit(50)).all()]

    # ---------- Notifications ----------
    @app.get(f"{p}/notifications", response_model=list[NotificationOut], tags=["Notifications"])
    def notifications(unread: bool = False, actor: Actor = Depends(current_actor)):
        actor.require(*READ, "hr:self")
        with scoped(actor) as session:
            query = select(Notification).where(visible(actor.user_id, actor.can("hr:write"))).order_by(Notification.created_at.desc()).limit(50)
            if unread:
                query = query.where(Notification.read_at.is_(None))
            return [as_dict(row) for row in session.scalars(query).all()]

    @app.post(f"{p}/notifications/read", status_code=204, tags=["Notifications"])
    def mark_read(actor: Actor = Depends(current_actor)):
        actor.require(*READ, "hr:self")
        with scoped(actor) as session:
            for row in session.scalars(select(Notification).where(visible(actor.user_id, actor.can("hr:write")), Notification.read_at.is_(None))).all():
                row.read_at = utcnow()

    # ---------- Dashboard ----------
    @app.get(f"{p}/dashboard", tags=["Dashboard"])
    def dashboard(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
        actor.require(*READ)
        with scoped(actor) as session:
            today = local_now().date()
            active = select(Employee.id).where(Employee.status == "active")
            headcount = session.scalar(select(func.count()).select_from(Employee).where(Employee.status == "active")) or 0
            by_department = session.execute(select(Department.name, func.count(Employee.id)).join(Employee, Employee.department_id == Department.id)
                                            .where(Employee.status == "active").group_by(Department.name).order_by(Department.name)).all()
            present = session.scalar(select(func.count()).select_from(AttendanceLog).where(AttendanceLog.work_date == today)) or 0
            on_leave = session.scalar(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "approved",
                                                                                          LeaveRequest.starts_on <= today, LeaveRequest.ends_on >= today)) or 0
            leave_status = dict(session.execute(select(LeaveRequest.status, func.count()).where(LeaveRequest.starts_on >= date(today.year, 1, 1))
                                                .group_by(LeaveRequest.status)).all())
            leave_kind = dict(session.execute(select(LeaveRequest.kind, func.sum(LeaveRequest.days)).where(LeaveRequest.status == "approved",
                                                                                                        LeaveRequest.starts_on >= date(today.year, 1, 1))
                                              .group_by(LeaveRequest.kind)).all())
            start = today - timedelta(days=20)
            trend = dict(session.execute(select(AttendanceLog.work_date, func.count()).where(AttendanceLog.work_date >= start)
                                         .group_by(AttendanceLog.work_date)).all())
            days = [start + timedelta(days=offset) for offset in range(21)]
            performance = session.execute(select(Department.name, func.avg(Review.rating), func.count(Review.id))
                                          .join(Employee, Employee.id == Review.employee_id).join(Department, Department.id == Employee.department_id)
                                          .where(Review.status == "completed").group_by(Department.name).order_by(Department.name)).all()
            latest_period = session.scalar(select(func.max(Review.period)))
            reviews_done = session.scalar(select(func.count()).select_from(Review).where(Review.period == latest_period, Review.status == "completed")) or 0
            distribution = dict(session.execute(select(Review.rating, func.count()).where(Review.status == "completed", Review.period == latest_period)
                                                .group_by(Review.rating)).all())
            run = session.scalar(select(PayrollRun).order_by(PayrollRun.period.desc()))
            low_stock = session.scalars(select(InventoryItem).where(InventoryItem.quantity <= InventoryItem.reorder_level).order_by(InventoryItem.name)).all()
            asset_status = dict(session.execute(select(Asset.status, func.count()).group_by(Asset.status)).all())
            pending = session.scalars(select(LeaveRequest).where(LeaveRequest.status == "pending").order_by(LeaveRequest.starts_on).limit(6)).all()
            approved_rules = session.scalar(select(func.count()).select_from(RuleSet).where(RuleSet.status == "approved")) or 0
            return {"headcount": headcount, "present_today": present, "on_leave_today": on_leave,
                    "attendance_rate_today": round(present / max(headcount - on_leave, 1), 4) if headcount else None,
                    "pending_leave": leave_status.get("pending", 0), "leave_by_status": leave_status,
                    "leave_days_by_kind": {key: int(value or 0) for key, value in leave_kind.items()},
                    "by_department": [{"department": name, "headcount": count} for name, count in by_department],
                    "attendance_trend": [{"date": day.isoformat(), "present": trend.get(day, 0)} for day in days if day.weekday() < 5],
                    "performance_by_department": [{"department": name, "average": round(float(avg), 2), "reviews": count} for name, avg, count in performance],
                    "rating_distribution": [{"rating": rating, "count": distribution.get(rating, 0)} for rating in range(1, 6)],
                    "review_period": latest_period, "reviews_completed": reviews_done,
                    "review_completion": round(reviews_done / headcount, 4) if headcount else None,
                    "latest_payroll": as_dict(run) if run else None, "rules_approved": approved_rules > 0,
                    "low_stock": [as_dict(item) for item in low_stock], "assets_by_status": asset_status,
                    "pending_requests": leave_views(session, list(pending)), "active_employees": session.scalar(select(func.count()).select_from(active.subquery()))}

    return app


def application():
    return create_app(load_settings("hr"))
