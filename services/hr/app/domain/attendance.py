import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from io import BytesIO

import qrcode
from sqlalchemy import select

from packages.campus_common.database import LOCAL_TZ, new_id, utcnow
from packages.campus_common.errors import DomainError
from services.hr.app.models import AttendanceChallenge, AttendanceLog, Employee

CHALLENGE_SECONDS = 60
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIN_SHIFT = timedelta(minutes=1)


def signature(secret: str, tenant_id: str, challenge_id: str, expires: int) -> str:
    return hmac.new(secret.encode(), f"{tenant_id}|{challenge_id}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def issue_challenge(session, tenant_id: str, kiosk: str, user_id: str, secret: str, now: datetime | None = None) -> tuple[AttendanceChallenge, str]:
    """A kiosk displays a short-lived signed QR; employees scan it, so a photographed code stops working within a minute."""
    moment = now or utcnow()
    challenge = AttendanceChallenge(id=new_id("chl"), tenant_id=tenant_id, code="".join(secrets.choice(ALPHABET) for _ in range(6)),
                                    kiosk=kiosk, expires_at=moment + timedelta(seconds=CHALLENGE_SECONDS), created_by=user_id, created_at=moment)
    session.add(challenge)
    expires = int(challenge.expires_at.timestamp())
    return challenge, f"CERP1.{challenge.id}.{expires}.{signature(secret, tenant_id, challenge.id, expires)}"


def qr_data_url(content: str) -> str:
    image = qrcode.make(content, box_size=8, border=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def resolve(session, tenant_id: str, secret: str, now: datetime, token: str | None, code: str | None) -> AttendanceChallenge:
    invalid = DomainError("This attendance code is invalid or has expired. Scan the kiosk again.", 422)
    if token:
        parts = token.strip().split(".")
        if len(parts) != 4 or parts[0] != "CERP1" or not parts[2].isdigit():
            raise invalid
        _, challenge_id, expires, signed = parts
        if not hmac.compare_digest(signature(secret, tenant_id, challenge_id, int(expires)), signed) or int(expires) < now.timestamp():
            raise invalid
        challenge = session.get(AttendanceChallenge, challenge_id)
    elif code:
        challenge = session.scalar(select(AttendanceChallenge).where(AttendanceChallenge.code == code.strip().upper(),
                                                                    AttendanceChallenge.expires_at >= now)
                                   .order_by(AttendanceChallenge.created_at.desc()))
    else:
        raise DomainError("Scan the kiosk QR code or type the code shown under it.", 422)
    if challenge is None or challenge.expires_at < now:
        raise invalid
    return challenge


def check_in(session, tenant_id: str, employee: Employee, secret: str, token: str | None = None, code: str | None = None,
             now: datetime | None = None) -> tuple[str, AttendanceLog]:
    moment = now or utcnow()
    if employee.status != "active":
        raise DomainError("Only active employees can record attendance.", 409)
    challenge = resolve(session, tenant_id, secret, moment, token, code)
    work_date = moment.astimezone(LOCAL_TZ).date()
    log = session.scalar(select(AttendanceLog).where(AttendanceLog.employee_id == employee.id, AttendanceLog.work_date == work_date)
                         .with_for_update())
    if log is None:
        log = AttendanceLog(id=new_id("atl"), tenant_id=tenant_id, employee_id=employee.id, work_date=work_date, check_in_at=moment,
                            method="qr" if token else "code", kiosk=challenge.kiosk)
        session.add(log)
        session.flush()
        return "check_in", log
    if log.check_out_at is not None:
        raise DomainError("You have already checked out today.", 409)
    if moment - log.check_in_at < MIN_SHIFT:
        raise DomainError("You checked in less than a minute ago.", 409)
    log.check_out_at = moment
    return "check_out", log
