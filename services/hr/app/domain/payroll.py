from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from packages.campus_common.database import LOCAL_TZ, local_now, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.pdf import money, render_pdf
from services.hr.app.domain.notifications import notify
from services.hr.app.models import Employee, PayrollRun, Payslip, RuleSet

# Seeded as a DRAFT for HR to verify against the official DGI/CNPS publications before approval; never auto-approved.
DRAFT_RULES = {
    "currency": "XAF",
    "cnps": {"ceiling": 750_000, "employee_rate": "0.042", "employer_pension_rate": "0.042", "family_allowance_rate": "0.07",
             "work_injury_rate": "0.0175"},
    "irpp": {"professional_expense_rate": "0.30", "annual_abatement": 500_000, "exempt_monthly_gross": 62_000, "cac_rate": "0.10",
             "brackets": [[2_000_000, "0.10"], [3_000_000, "0.15"], [5_000_000, "0.25"], [None, "0.35"]]},
    "employee_other": [{"code": "CFC", "label": "Credit Foncier du Cameroun (employee)", "rate": "0.01"}],
    "employer_other": [{"code": "CFC_ER", "label": "Credit Foncier du Cameroun (employer)", "rate": "0.015"},
                       {"code": "FNE", "label": "Fonds National de l'Emploi", "rate": "0.01"}],
}
DRAFT_SOURCES = [
    {"title": "Code General des Impots (2026 edition) - IRPP on salaries: 30% professional-expense allowance, 500,000 FCFA annual "
              "abatement, progressive scale 10/15/25/35%, CAC 10%", "url": "https://www.impots.cm/fr/documentation"},
    {"title": "Circulaire portant instructions relatives a l'application de la Loi de Finances 2026",
     "url": "https://www.impots.cm/fr/actualites/circulaire-lf-2026"},
    {"title": "CNPS contribution schedule - pension (PVID) 4.2% employee / 4.2% employer, family allowances, work injury; ceiling 750,000 FCFA",
     "url": "https://www.cnps.cm/"},
]


def as_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate(value) -> Decimal:
    number = Decimal(str(value))
    if not Decimal(0) <= number <= Decimal(1):
        raise DomainError("Rates must be between 0 and 1.", 422)
    return number


def validate_rules(rules: dict) -> dict:
    try:
        cnps, irpp = rules["cnps"], rules["irpp"]
        for key in ("employee_rate", "employer_pension_rate", "family_allowance_rate", "work_injury_rate"):
            rate(cnps[key])
        for key in ("professional_expense_rate", "cac_rate"):
            rate(irpp[key])
        if int(cnps["ceiling"]) <= 0 or int(irpp["annual_abatement"]) < 0 or int(irpp["exempt_monthly_gross"]) < 0:
            raise DomainError("Ceilings and abatements must be positive.", 422)
        brackets = irpp["brackets"]
        uppers = [upper for upper, _ in brackets[:-1]]
        if not brackets or brackets[-1][0] is not None or uppers != sorted(uppers) or any(upper is None or upper <= 0 for upper in uppers):
            raise DomainError("Tax brackets must ascend and end with an open top bracket.", 422)
        for _, value in brackets:
            rate(value)
        for component in rules.get("employee_other", []) + rules.get("employer_other", []):
            rate(component["rate"])
            if not component.get("code") or not component.get("label"):
                raise DomainError("Every additional component needs a code and label.", 422)
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise DomainError(f"Rule set is incomplete or malformed: {error}", 422) from error
    return rules


def progressive_tax(annual_base: Decimal, brackets: list) -> Decimal:
    tax, lower = Decimal(0), Decimal(0)
    for upper, bracket_rate in brackets:
        if annual_base <= lower:
            break
        top = annual_base if upper is None else min(annual_base, Decimal(upper))
        tax += (top - lower) * Decimal(str(bracket_rate))
        if upper is None:
            break
        lower = Decimal(upper)
    return tax


def calculate(base_salary: int, allowances: int, rules: dict) -> dict:
    """Monthly payslip. PAYE (IRPP) base = gross - professional allowance - employee pension - monthly share of the annual abatement."""
    gross = Decimal(base_salary + allowances)
    cnps, irpp_rules = rules["cnps"], rules["irpp"]
    capped = min(gross, Decimal(cnps["ceiling"]))
    pension = as_int(capped * rate(cnps["employee_rate"]))
    if gross <= Decimal(irpp_rules["exempt_monthly_gross"]):
        taxable, irpp = Decimal(0), 0
    else:
        taxable = max(Decimal(0), gross * (1 - rate(irpp_rules["professional_expense_rate"])) - pension
                      - Decimal(irpp_rules["annual_abatement"]) / 12)
        irpp = as_int(progressive_tax(taxable * 12, irpp_rules["brackets"]) / 12)
    cac = as_int(Decimal(irpp) * rate(irpp_rules["cac_rate"]))
    employee = [{"code": "CNPS_PVID", "label": "CNPS pension (employee)", "base": as_int(capped), "amount": pension},
                {"code": "IRPP", "label": "IRPP / PAYE", "base": as_int(taxable), "amount": irpp},
                {"code": "CAC", "label": "Additional council tax (CAC)", "base": irpp, "amount": cac}]
    employee += [{"code": item["code"], "label": item["label"], "base": as_int(gross), "amount": as_int(gross * rate(item["rate"]))}
                 for item in rules.get("employee_other", [])]
    employer = [{"code": "CNPS_PVID_ER", "label": "CNPS pension (employer)", "base": as_int(capped), "amount": as_int(capped * rate(cnps["employer_pension_rate"]))},
                {"code": "CNPS_PF", "label": "CNPS family allowances", "base": as_int(capped), "amount": as_int(capped * rate(cnps["family_allowance_rate"]))},
                {"code": "CNPS_AT", "label": "CNPS work injury", "base": as_int(gross), "amount": as_int(gross * rate(cnps["work_injury_rate"]))}]
    employer += [{"code": item["code"], "label": item["label"], "base": as_int(gross), "amount": as_int(gross * rate(item["rate"]))}
                 for item in rules.get("employer_other", [])]
    deductions = sum(line["amount"] for line in employee)
    contributions = sum(line["amount"] for line in employer)
    return {"earnings": [{"code": "BASE", "label": "Base salary", "amount": base_salary},
                         {"code": "ALLOW", "label": "Taxable allowances", "amount": allowances}],
            "gross": as_int(gross), "employee": employee, "employer": employer, "employee_total": deductions,
            "employer_total": contributions, "net": as_int(gross) - deductions, "taxable_monthly": as_int(taxable)}


def approve_rule_set(session, rule_set: RuleSet, user_id: str, note: str) -> RuleSet:
    if rule_set.status != "draft":
        raise DomainError("Only draft rule sets can be approved.", 409)
    if len(note.strip()) < 15:
        raise DomainError("Record which official publication you verified the rates against (at least 15 characters).", 422)
    validate_rules(rule_set.rules)
    for other in session.scalars(select(RuleSet).where(RuleSet.status == "approved", RuleSet.effective_from == rule_set.effective_from)).all():
        other.status = "retired"
    rule_set.status, rule_set.approved_by, rule_set.approval_note, rule_set.approved_at = "approved", user_id, note.strip(), utcnow()
    return rule_set


def period_bounds(period: str) -> tuple[date, date]:
    year, month = map(int, period.split("-"))
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1)
    return first, last


def applicable_rules(session, period: str) -> RuleSet:
    first, _ = period_bounds(period)
    rule_set = session.scalar(select(RuleSet).where(RuleSet.status == "approved", RuleSet.effective_from <= first)
                              .order_by(RuleSet.effective_from.desc()))
    if rule_set is None:
        raise DomainError(f"No approved statutory rule set covers {period}. Review and approve the payroll rules first.", 409)
    return rule_set


def create_run(session, tenant_id: str, period: str, user_id: str) -> PayrollRun:
    if period > local_now().strftime("%Y-%m"):
        raise DomainError("Payroll cannot be run for a future month.", 422)
    if session.scalar(select(PayrollRun.id).where(PayrollRun.period == period)):
        raise DomainError(f"A payroll run for {period} already exists.", 409)
    rule_set = applicable_rules(session, period)
    _, next_month = period_bounds(period)
    employees = session.scalars(select(Employee).where(Employee.status == "active", Employee.hired_on < next_month).order_by(Employee.name)).all()
    if not employees:
        raise DomainError("There are no active employees to pay for this period.", 409)
    run = PayrollRun(id=new_id("prn"), tenant_id=tenant_id, period=period, status="draft", rule_set_id=rule_set.id, created_by=user_id,
                     created_at=utcnow(), totals={})
    session.add(run)
    session.flush()
    totals = {"headcount": 0, "gross": 0, "net": 0, "employee_deductions": 0, "employer_contributions": 0, "irpp": 0, "cnps": 0}
    for employee in employees:
        slip = calculate(employee.base_salary, employee.allowances, rule_set.rules)
        session.add(Payslip(id=new_id("psl"), tenant_id=tenant_id, run_id=run.id, employee_id=employee.id, employee_name=employee.name,
                            period=period, gross=slip["gross"], employee_deductions=slip["employee_total"], net=slip["net"],
                            employer_contributions=slip["employer_total"], lines=slip))
        codes = {line["code"]: line["amount"] for line in slip["employee"] + slip["employer"]}
        totals["headcount"] += 1
        totals["gross"] += slip["gross"]
        totals["net"] += slip["net"]
        totals["employee_deductions"] += slip["employee_total"]
        totals["employer_contributions"] += slip["employer_total"]
        totals["irpp"] += codes["IRPP"] + codes["CAC"]
        totals["cnps"] += codes["CNPS_PVID"] + codes["CNPS_PVID_ER"] + codes["CNPS_PF"] + codes["CNPS_AT"]
    run.totals = {**totals, "employer_cost": totals["gross"] + totals["employer_contributions"], "rule_set": rule_set.name}
    return run


def discard_run(session, run: PayrollRun) -> None:
    if run.status != "draft":
        raise DomainError("Finalized payroll runs are immutable.", 409)
    for slip in session.scalars(select(Payslip).where(Payslip.run_id == run.id)).all():
        session.delete(slip)
    session.flush()
    session.delete(run)


def finalize_run(session, tenant_id: str, run: PayrollRun, user_id: str) -> PayrollRun:
    if run.status != "draft":
        raise DomainError("This payroll run is already finalized.", 409)
    run.status, run.finalized_by, run.finalized_at = "finalized", user_id, utcnow()
    for slip, employee in session.execute(select(Payslip, Employee).join(Employee, Employee.id == Payslip.employee_id)
                                          .where(Payslip.run_id == run.id)).all():
        if employee.user_id:
            notify(session, tenant_id, f"payslip:{run.id}:{employee.id}", f"Payslip for {run.period} is available",
                   f"Your net pay for {run.period} is {money(slip.net)}.", "payroll", user_id=employee.user_id,
                   email=employee.email, link="/hr/me")
    return run


def payslip_pdf(institution: str, slip: Payslip, employee: Employee, rule_set: RuleSet) -> bytes:
    lines = slip.lines
    blocks = [("kv", [("Employee", f"{employee.name} ({employee.employee_no})"), ("Position", employee.position), ("Period", slip.period),
                      ("Statutory rule set", f"{rule_set.name} (effective {rule_set.effective_from.isoformat()})"),
                      ("Rules approved", f"{rule_set.approved_at.astimezone(LOCAL_TZ):%d %b %Y}" if rule_set.approved_at else "-")]),
              ("heading", "Earnings"),
              ("table", ["Item", "Amount"], [[item["label"], money(item["amount"])] for item in lines["earnings"]] + [["Gross pay", money(slip.gross)]]),
              ("heading", "Employee deductions"),
              ("table", ["Item", "Base", "Amount"], [[item["label"], money(item["base"]), money(item["amount"])] for item in lines["employee"]]
               + [["Total deductions", "", money(slip.employee_deductions)]]),
              ("kv", [("Net pay", money(slip.net))]),
              ("heading", "Employer contributions (not deducted from pay)"),
              ("table", ["Item", "Base", "Amount"], [[item["label"], money(item["base"]), money(item["amount"])] for item in lines["employer"]]
               + [["Total employer contributions", "", money(slip.employer_contributions)]])]
    return render_pdf("Payslip", institution, f"{employee.name} - {datetime.strptime(slip.period, '%Y-%m'):%B %Y}", blocks, utcnow())
