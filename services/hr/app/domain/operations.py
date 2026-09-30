from datetime import date, timedelta

from sqlalchemy import func, select

from packages.campus_common.database import fetch, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from services.hr.app.domain.notifications import notify
from services.hr.app.models import (Applicant, Asset, AssetAssignment, Department, Employee, InventoryItem, LeaveBalance, LeaveRequest,
                                    StockMovement, Vacancy)

ENTITLEMENTS = {"annual": 18, "sick": 12, "compassionate": 5}
# Fixed-date Cameroonian public holidays; movable feasts are added by HR as needed.
FIXED_HOLIDAYS = {(1, 1), (2, 11), (5, 1), (5, 20), (8, 15), (12, 25)}
TRANSITIONS = {"applied": {"screened", "rejected"}, "screened": {"interview", "rejected"}, "interview": {"offered", "rejected"},
               "offered": {"hired", "rejected"}, "hired": set(), "rejected": set()}
ASSET_STATES = {"available": {"maintenance", "retired"}, "maintenance": {"available", "retired"}, "assigned": set(), "retired": set()}


def working_days(start: date, end: date) -> int:
    days, current = 0, start
    while current <= end:
        if current.weekday() < 5 and (current.month, current.day) not in FIXED_HOLIDAYS:
            days += 1
        current += timedelta(days=1)
    return days


def balance_for(session, tenant_id: str, employee_id: str, year: int, kind: str, lock: bool = False) -> LeaveBalance:
    query = select(LeaveBalance).where(LeaveBalance.employee_id == employee_id, LeaveBalance.year == year, LeaveBalance.kind == kind)
    balance = session.scalar(query.with_for_update() if lock else query)
    if balance is None:
        balance = LeaveBalance(id=new_id("lvb"), tenant_id=tenant_id, employee_id=employee_id, year=year, kind=kind,
                               entitled=ENTITLEMENTS[kind], used=0)
        session.add(balance)
        session.flush()
    return balance


def pending_days(session, employee_id: str, kind: str, year: int, exclude: str | None = None) -> int:
    rows = session.scalars(select(LeaveRequest).where(LeaveRequest.employee_id == employee_id, LeaveRequest.kind == kind,
                                                      LeaveRequest.status == "pending")).all()
    return sum(row.days for row in rows if row.starts_on.year == year and row.id != exclude)


def request_leave(session, tenant_id: str, employee: Employee, kind: str, starts_on: date, ends_on: date, reason: str,
                  hr_mailbox: str) -> LeaveRequest:
    if kind not in ENTITLEMENTS:
        raise DomainError("Unknown leave type.", 422)
    if ends_on < starts_on:
        raise DomainError("The leave must end on or after its start date.", 422)
    if starts_on.year != ends_on.year:
        raise DomainError("Split leave that crosses a calendar year into two requests.", 422)
    if kind == "annual" and starts_on < local_now().date():
        raise DomainError("Annual leave must be requested in advance.", 422)
    days = working_days(starts_on, ends_on)
    if days == 0:
        raise DomainError("The selected dates contain no working days.", 422)
    overlap = session.scalar(select(LeaveRequest.id).where(LeaveRequest.employee_id == employee.id,
                                                           LeaveRequest.status.in_(("pending", "approved")),
                                                           LeaveRequest.starts_on <= ends_on, LeaveRequest.ends_on >= starts_on))
    if overlap:
        raise DomainError("You already have leave booked or pending on these dates.", 409)
    balance = balance_for(session, tenant_id, employee.id, starts_on.year, kind)
    available = balance.entitled - balance.used - pending_days(session, employee.id, kind, starts_on.year)
    if days > available:
        raise DomainError(f"Only {available} {kind} day(s) remain (including pending requests); this request needs {days}.", 409)
    request = LeaveRequest(id=new_id("lvr"), tenant_id=tenant_id, employee_id=employee.id, kind=kind, starts_on=starts_on, ends_on=ends_on,
                           days=days, reason=reason, status="pending", created_at=utcnow())
    session.add(request)
    session.flush()
    notify(session, tenant_id, f"leave-requested:{request.id}", f"Leave request from {employee.name}",
           f"{employee.name} requested {days} day(s) of {kind} leave from {starts_on:%d %b} to {ends_on:%d %b %Y}. Approval is required.",
           "leave", role="hr", email=hr_mailbox, link="/hr/leave")
    return request


def decide_leave(session, tenant_id: str, request: LeaveRequest, actor_user_id: str, decision: str, note: str) -> LeaveRequest:
    """Balance row is locked so two concurrent approvals cannot overdraw the entitlement."""
    if request.status != "pending":
        raise DomainError(f"This request is already {request.status}.", 409)
    employee = fetch(session, Employee, request.employee_id, "Employee")
    if employee.user_id == actor_user_id:
        raise DomainError("You cannot approve or reject your own leave request.", 403)
    if decision == "approved":
        balance = balance_for(session, tenant_id, employee.id, request.starts_on.year, request.kind, lock=True)
        if balance.used + request.days > balance.entitled:
            raise DomainError(f"Approving would exceed the {balance.entitled}-day {request.kind} entitlement.", 409)
        balance.used += request.days
    elif decision != "rejected":
        raise DomainError("Decision must be approved or rejected.", 422)
    request.status, request.decided_by, request.decision_note, request.decided_at = decision, actor_user_id, note, utcnow()
    notify(session, tenant_id, f"leave-decided:{request.id}", f"Leave request {decision}",
           f"Your {request.kind} leave from {request.starts_on:%d %b} to {request.ends_on:%d %b %Y} was {decision}. {note}".strip(),
           "leave", user_id=employee.user_id, email=employee.email, link="/hr/me")
    return request


def cancel_leave(session, tenant_id: str, request: LeaveRequest, employee: Employee) -> LeaveRequest:
    if request.employee_id != employee.id:
        raise DomainError("Leave request not found.", 404)
    if request.status == "approved":
        if request.starts_on <= local_now().date():
            raise DomainError("Leave that has already started cannot be cancelled.", 409)
        balance = balance_for(session, tenant_id, employee.id, request.starts_on.year, request.kind, lock=True)
        balance.used -= request.days
    elif request.status != "pending":
        raise DomainError(f"This request is already {request.status}.", 409)
    request.status, request.decided_at = "cancelled", utcnow()
    return request


def next_employee_number(session) -> str:
    count = session.scalar(select(func.count()).select_from(Employee)) or 0
    return f"EMP{count + 1:03d}"


def hire(session, tenant_id: str, name: str, email: str, phone: str, department_id: str, position: str, base_salary: int,
         allowances: int, hired_on: date, user_id: str | None = None) -> Employee:
    fetch(session, Department, department_id, "Department")
    employee = Employee(id=new_id("emp"), tenant_id=tenant_id, user_id=user_id, employee_no=next_employee_number(session), name=name,
                        email=email.lower(), phone=phone, department_id=department_id, position=position, hired_on=hired_on,
                        base_salary=base_salary, allowances=allowances, status="active")
    session.add(employee)
    session.flush()
    for kind in ENTITLEMENTS:
        balance_for(session, tenant_id, employee.id, hired_on.year, kind)
    return employee


def advance_applicant(session, tenant_id: str, applicant: Applicant, stage: str, actor_user_id: str, offered_salary: int | None = None,
                      start_date: date | None = None) -> Applicant:
    if stage not in TRANSITIONS.get(applicant.stage, set()):
        raise DomainError(f"An applicant cannot move from {applicant.stage} to {stage}.", 409)
    if stage == "offered":
        if not offered_salary or offered_salary <= 0:
            raise DomainError("An offer needs a monthly salary.", 422)
        applicant.offered_salary = offered_salary
    if stage == "hired":
        vacancy = session.scalar(select(Vacancy).where(Vacancy.id == applicant.vacancy_id).with_for_update())
        if vacancy.status != "open" or vacancy.openings < 1:
            raise DomainError("This vacancy has no remaining openings.", 409)
        employee = hire(session, tenant_id, applicant.name, applicant.email, applicant.phone, vacancy.department_id, vacancy.title,
                        applicant.offered_salary or 0, 0, start_date or local_now().date())
        applicant.employee_id = employee.id
        vacancy.openings -= 1
        if vacancy.openings == 0:
            vacancy.status = "filled"
    applicant.stage, applicant.updated_at = stage, utcnow()
    applicant.history = [*(applicant.history or []), {"stage": stage, "by": actor_user_id, "at": utcnow().isoformat()}]
    return applicant


def record_movement(session, tenant_id: str, item_id: str, delta: int, reason: str, user_id: str) -> StockMovement:
    item = session.scalar(select(InventoryItem).where(InventoryItem.id == item_id).with_for_update())
    if item is None:
        raise DomainError("Inventory item not found.", 404)
    if delta == 0:
        raise DomainError("Enter a quantity to add or remove.", 422)
    if item.quantity + delta < 0:
        raise DomainError(f"Only {item.quantity} {item.unit} of {item.name} are in stock.", 409)
    before = item.quantity
    item.quantity += delta
    movement = StockMovement(id=new_id("stk"), tenant_id=tenant_id, item_id=item.id, delta=delta, reason=reason, balance_after=item.quantity,
                             created_by=user_id, created_at=utcnow())
    session.add(movement)
    if before > item.reorder_level >= item.quantity:
        notify(session, tenant_id, f"low-stock:{item.id}:{movement.id}", f"Low stock: {item.name}",
               f"{item.name} is down to {item.quantity} {item.unit} (reorder level {item.reorder_level}).", "inventory", role="hr",
               link="/hr/assets")
    return movement


def assign_asset(session, tenant_id: str, asset_id: str, employee_id: str, note: str) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise DomainError("Asset not found.", 404)
    employee = fetch(session, Employee, employee_id, "Employee")
    if asset.status != "available":
        raise DomainError(f"{asset.tag} is {asset.status} and cannot be assigned.", 409)
    asset.status, asset.employee_id = "assigned", employee.id
    session.add(AssetAssignment(id=new_id("asg"), tenant_id=tenant_id, asset_id=asset.id, employee_id=employee.id, assigned_at=utcnow(), note=note))
    return asset


def return_asset(session, asset_id: str, condition: str) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise DomainError("Asset not found.", 404)
    if asset.status != "assigned":
        raise DomainError(f"{asset.tag} is not currently assigned.", 409)
    assignment = session.scalar(select(AssetAssignment).where(AssetAssignment.asset_id == asset.id, AssetAssignment.returned_at.is_(None)))
    if assignment is not None:
        assignment.returned_at = utcnow()
    asset.condition = condition
    asset.status, asset.employee_id = ("maintenance" if condition == "poor" else "available"), None
    return asset


def change_asset_status(asset: Asset, status: str) -> Asset:
    if status not in ASSET_STATES.get(asset.status, set()):
        raise DomainError(f"An asset cannot move from {asset.status} to {status}.", 409)
    asset.status = status
    return asset
