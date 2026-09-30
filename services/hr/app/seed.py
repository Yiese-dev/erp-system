import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from packages.campus_common import demo
from packages.campus_common.database import LOCAL_TZ, Database, local_now, utcnow
from services.hr.app.domain import operations, payroll
from services.hr.app.domain.notifications import notify
from services.hr.app.models import (Applicant, Asset, AssetAssignment, AttendanceLog, Department, Employee, InventoryItem, KnownTenant,
                                    LeaveRequest, Review, RuleSet, StockMovement, Vacancy)

DEPARTMENTS = ["Academic Affairs", "Administration", "Finance", "Human Resources", "IT Services"]
ASSETS = [("LPT", "Dell Latitude 5440 laptop", "laptop", 685_000, 6), ("PRJ", "Epson EB-X49 projector", "projector", 420_000, 4),
          ("DSK", "HP ProDesk 400 desktop", "desktop", 510_000, 5), ("PRN", "Canon imageRUNNER 2425 printer", "printer", 1_250_000, 2),
          ("NET", "Cisco Catalyst 1000 switch", "network", 780_000, 2), ("VEH", "Toyota Hilux double cabin", "vehicle", 24_500_000, 1)]
ITEMS = [("PAP-A4", "A4 paper (ream, 80g)", "reams", 140, 60), ("TON-2425", "Canon C-EXV 42 toner", "cartridges", 3, 4),
         ("MRK-WB", "Whiteboard markers (box of 10)", "boxes", 22, 10), ("CAB-C6", "Cat6 patch cable 3m", "cables", 45, 20),
         ("DSL-GEN", "Diesel for standby generator", "litres", 180, 200), ("SAN-GEL", "Hand sanitiser 5L", "cans", 9, 5)]


def seed(database: Database) -> None:
    for tenant_id, slug, _ in demo.TENANTS:
        with database.session(tenant_id) as session:
            if session.get(KnownTenant, tenant_id) is None:
                session.add(KnownTenant(id=tenant_id))
            if session.scalar(select(Department.id).limit(1)):
                continue
            seed_tenant(session, tenant_id, slug)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)


def seed_tenant(session, tenant: str, slug: str) -> None:
    rng = random.Random(f"hr-{slug}")
    today = local_now().date()
    departments = {}
    for name in DEPARTMENTS:
        departments[name] = Department(id=f"dep_{slug}_{name.split()[0].lower()}", tenant_id=tenant, name=name)
        session.add(departments[name])
    session.flush()
    employees = []
    for index, (user_id, name, department, position, salary, allowance) in enumerate(demo.EMPLOYEES):
        employee = Employee(id=f"emp_{slug}_{index:02d}", tenant_id=tenant, user_id=user_id, employee_no=f"EMP{index + 1:03d}", name=name,
                            email=demo.email_for(name, slug), phone=f"6{rng.choice([7, 9, 5])}{rng.randint(1000000, 9999999)}",
                            department_id=departments[department].id, position=position,
                            hired_on=date(2018 + index % 7, 1 + index % 12, 1 + index % 27), base_salary=salary, allowances=allowance,
                            status="active")
        employees.append(employee)
    session.add_all(employees)
    session.flush()
    for employee in employees:
        for kind in operations.ENTITLEMENTS:
            operations.balance_for(session, tenant, employee.id, today.year, kind)

    session.add(RuleSet(id=f"rul_{slug}_2026", tenant_id=tenant, name="Cameroon statutory payroll 2026 (CNPS + IRPP/PAYE)",
                        effective_from=date(2026, 1, 1), status="draft", rules=payroll.DRAFT_RULES, sources=payroll.DRAFT_SOURCES,
                        created_at=utcnow()))

    def working_days_back(count: int) -> list[date]:
        days, current = [], today
        while len(days) < count:
            if current.weekday() < 5:
                days.append(current)
            current -= timedelta(days=1)
        return days[::-1]

    for day in working_days_back(15):
        for employee in employees:
            if rng.random() < 0.08:
                continue
            if day == today:
                if rng.random() < 0.3:
                    continue
                session.add(AttendanceLog(id=f"atl_{employee.id}_{day:%Y%m%d}", tenant_id=tenant, employee_id=employee.id, work_date=day,
                                          check_in_at=at(day, 7, rng.randint(30, 59)), check_out_at=None, method="qr", kiosk="Main entrance"))
                continue
            session.add(AttendanceLog(id=f"atl_{employee.id}_{day:%Y%m%d}", tenant_id=tenant, employee_id=employee.id, work_date=day,
                                      check_in_at=at(day, 7 + rng.randint(0, 1), rng.randint(0, 59)),
                                      check_out_at=at(day, 16 + rng.randint(0, 1), rng.randint(0, 59)),
                                      method=rng.choice(["qr", "qr", "qr", "code"]), kiosk=rng.choice(["Main entrance", "Staff room"])))

    history = [(3, "annual", date(today.year, 8, 3), date(today.year, 8, 14)), (5, "annual", date(today.year, 7, 20), date(today.year, 7, 31)),
               (8, "sick", date(today.year, 9, 2), date(today.year, 9, 4)), (1, "annual", date(today.year, 4, 6), date(today.year, 4, 10)),
               (10, "compassionate", date(today.year, 6, 15), date(today.year, 6, 17))]
    for index, kind, start, end in history:
        days = operations.working_days(start, end)
        session.add(LeaveRequest(id=f"lvr_{slug}_hist_{index}", tenant_id=tenant, employee_id=employees[index].id, kind=kind, starts_on=start,
                                 ends_on=end, days=days, reason="Planned leave", status="approved", decided_by="usr_hr",
                                 decision_note="Approved", decided_at=at(start - timedelta(days=10), 10, 0), created_at=at(start - timedelta(days=14), 9, 0)))
        operations.balance_for(session, tenant, employees[index].id, start.year, kind).used += days
    rejected_start = date(today.year, 9, 14)
    session.add(LeaveRequest(id=f"lvr_{slug}_rej", tenant_id=tenant, employee_id=employees[7].id, kind="annual", starts_on=rejected_start,
                             ends_on=rejected_start + timedelta(days=4), days=5, reason="Family visit", status="rejected", decided_by="usr_hr",
                             decision_note="Network upgrade scheduled that week", decided_at=at(rejected_start - timedelta(days=12), 11, 0),
                             created_at=at(rejected_start - timedelta(days=15), 9, 0)))
    session.flush()
    for index, kind, offset, length, reason in [(6, "annual", 12, 5, "Wedding in Bamenda"), (9, "annual", 20, 3, "Family matters"),
                                                (11, "annual", 30, 10, "Research conference in Yaounde")]:
        start = today + timedelta(days=offset)
        while start.weekday() >= 5:
            start += timedelta(days=1)
        operations.request_leave(session, tenant, employees[index], kind, start, start + timedelta(days=length), reason, "hr-office@campus.test")

    reviewer = next(employee for employee in employees if employee.user_id == "usr_hr")
    for employee in employees:
        if employee.id == reviewer.id:
            reviewer_id, reviewer_name = "usr_admin", demo.USERS["admin"][2]
        else:
            reviewer_id, reviewer_name = "usr_hr", reviewer.name
        session.add(Review(id=f"rev_{employee.id}_h1", tenant_id=tenant, employee_id=employee.id, period=f"{today.year}-H1",
                           goals="Deliver departmental objectives; complete mandatory training; improve service turnaround.",
                           rating=rng.choices([2, 3, 4, 5], weights=[1, 4, 5, 2])[0], comments="Solid semester with clear progress on objectives.",
                           reviewer_user_id=reviewer_id, reviewer_name=reviewer_name, status="completed", created_at=at(date(today.year, 6, 20), 9, 0),
                           completed_at=at(date(today.year, 7, 3), 15, 0)))
    for employee in employees[:4]:
        if employee.id != reviewer.id:
            session.add(Review(id=f"rev_{employee.id}_h2", tenant_id=tenant, employee_id=employee.id, period=f"{today.year}-H2",
                               goals="Support the Fall 2026 intake and digital services roll-out.", rating=None, comments="",
                               reviewer_user_id="usr_hr", reviewer_name=reviewer.name, status="draft", created_at=utcnow()))

    lecturer = Vacancy(id=f"vac_{slug}_lecturer", tenant_id=tenant, title="Lecturer in Computer Science", department_id=departments["Academic Affairs"].id,
                       openings=2, description="PhD or MSc with teaching experience in software engineering.", status="open", created_at=at(date(today.year, 8, 18), 9, 0))
    accountant = Vacancy(id=f"vac_{slug}_accountant", tenant_id=tenant, title="Assistant Accountant", department_id=departments["Finance"].id,
                         openings=1, description="Licence in accounting; SYSCOHADA experience required.", status="open", created_at=at(date(today.year, 9, 1), 9, 0))
    session.add_all([lecturer, accountant])
    session.flush()
    candidates = [(lecturer, "Ines Nkwenti", "interview"), (lecturer, "Martin Eyong", "screened"), (lecturer, "Beatrice Afanda", "offered"),
                  (lecturer, "Pascal Mbah", "applied"), (lecturer, "Therese Ngum", "rejected"), (accountant, "Victor Essama", "applied"),
                  (accountant, "Ornella Bissek", "screened"), (accountant, "Samuel Djeukam", "interview")]
    for number, (vacancy, name, stage) in enumerate(candidates):
        applied = at(vacancy.created_at.astimezone(LOCAL_TZ).date() + timedelta(days=number + 1), 10, 0)
        session.add(Applicant(id=f"apl_{slug}_{number:02d}", tenant_id=tenant, vacancy_id=vacancy.id, name=name,
                              email=f"{name.lower().replace(' ', '.')}@mail.example", phone=f"6{rng.randint(70000000, 99999999)}",
                              stage=stage, offered_salary=780_000 if stage == "offered" else None, applied_at=applied, updated_at=applied,
                              history=[{"stage": "applied", "by": "usr_hr", "at": applied.isoformat()}] +
                                      ([{"stage": stage, "by": "usr_hr", "at": applied.isoformat()}] if stage != "applied" else [])))

    tag_number = 1
    holders = [employee for employee in employees if employee.user_id] + employees[6:9]
    for prefix, name, category, value, count in ASSETS:
        for copy in range(count):
            asset = Asset(id=f"ast_{slug}_{prefix}{copy}", tenant_id=tenant, tag=f"{slug[:3].upper()}-{prefix}-{tag_number:03d}", name=name,
                          category=category, serial=f"{prefix}{rng.randint(10000000, 99999999)}",
                          location=rng.choice(["Main building", "Block B", "Library", "Lab 1", "Lab 2"]),
                          condition=rng.choice(["good", "good", "fair"]), status="available", employee_id=None,
                          purchased_on=date(2022 + copy % 4, 1 + copy * 2 % 12, 10), value=value)
            session.add(asset)
            tag_number += 1
            session.flush()
            if category == "laptop" and holders:
                holder = holders.pop(0)
                asset.status, asset.employee_id = "assigned", holder.id
                session.add(AssetAssignment(id=f"asg_{asset.id}", tenant_id=tenant, asset_id=asset.id, employee_id=holder.id,
                                            assigned_at=at(date(today.year, 1, 15), 10, 0), note="Staff laptop"))
            elif category == "projector" and copy == 3:
                asset.status = "maintenance"
    for sku, name, unit, quantity, reorder in ITEMS:
        item = InventoryItem(id=f"itm_{slug}_{sku.lower()}", tenant_id=tenant, sku=sku, name=name, unit=unit, quantity=quantity, reorder_level=reorder)
        session.add(item)
        session.flush()
        session.add(StockMovement(id=f"stk_{item.id}_open", tenant_id=tenant, item_id=item.id, delta=quantity, reason="Opening balance",
                                  balance_after=quantity, created_by="usr_hr", created_at=at(date(today.year, 1, 5), 9, 0)))
        if quantity <= reorder:
            notify(session, tenant, f"low-stock:{item.id}:seed", f"Low stock: {name}", f"{name} is at {quantity} {unit} (reorder level {reorder}).",
                   "inventory", role="hr", link="/hr/assets")
