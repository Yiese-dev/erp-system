from datetime import date

from sqlalchemy import func, select

from packages.campus_common.database import new_id, utcnow
from packages.campus_common.errors import DomainError
from services.finance.app.models import JournalEntry, JournalLine

ACCOUNTS = {
    "1010": ("Bank - operating account", "asset"),
    "1020": ("Mobile money clearing", "asset"),
    "1200": ("Tuition receivable", "asset"),
    "4000": ("Tuition revenue", "revenue"),
    "5100": ("Marketing and recruitment", "expense"),
    "5200": ("Supplies and maintenance", "expense"),
    "5300": ("Utilities and connectivity", "expense"),
    "5400": ("IT services", "expense"),
    "5500": ("Travel and events", "expense"),
    "5900": ("Other operating expenses", "expense"),
}
EXPENSE_ACCOUNTS = {"marketing": "5100", "supplies": "5200", "maintenance": "5200", "utilities": "5300",
                    "it_services": "5400", "travel": "5500", "other": "5900"}
SETTLEMENT_ACCOUNTS = {"mtn_momo": "1020", "orange_money": "1020", "bank_transfer": "1010", "cash": "1010"}


def post_entry(session, tenant_id: str, entry_date: date, memo: str, source_type: str, source_id: str,
               lines: list[tuple[str, int, int]]) -> JournalEntry:
    """Double-entry invariant: every line is one-sided and total debits equal total credits."""
    if len(lines) < 2:
        raise DomainError("A journal entry needs at least two lines.", 422)
    debits = credits = 0
    for account, debit, credit in lines:
        if account not in ACCOUNTS:
            raise DomainError(f"Unknown ledger account {account}.", 422)
        if debit < 0 or credit < 0 or (debit and credit) or not (debit or credit):
            raise DomainError("Each journal line must be a single positive debit or credit.", 422)
        debits, credits = debits + debit, credits + credit
    if debits != credits:
        raise DomainError(f"Journal entry is unbalanced (debits {debits} vs credits {credits}).", 422)
    entry = JournalEntry(id=new_id("jnl"), tenant_id=tenant_id, entry_date=entry_date, memo=memo[:200], source_type=source_type,
                         source_id=source_id, created_at=utcnow())
    session.add(entry)
    session.flush()
    session.add_all([JournalLine(id=new_id("jln"), tenant_id=tenant_id, entry_id=entry.id, account_code=account, debit=debit, credit=credit)
                     for account, debit, credit in lines])
    return entry


def trial_balance(session) -> dict:
    rows = session.execute(select(JournalLine.account_code, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                           .group_by(JournalLine.account_code)).all()
    accounts = [{"code": code, "name": ACCOUNTS[code][0], "type": ACCOUNTS[code][1], "debit": int(debit or 0), "credit": int(credit or 0),
                 "balance": int((debit or 0) - (credit or 0))} for code, debit, credit in sorted(rows)]
    total_debit, total_credit = sum(row["debit"] for row in accounts), sum(row["credit"] for row in accounts)
    return {"accounts": accounts, "total_debit": total_debit, "total_credit": total_credit, "balanced": total_debit == total_credit}
