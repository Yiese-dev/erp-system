import json
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import or_, select

from packages.campus_common.database import new_id, utcnow
from services.hr.app.models import KnownTenant, Notification

MAX_EMAIL_ATTEMPTS = 5
log = logging.getLogger("campus.hr.notifications")


def notify(session, tenant_id: str, dedupe_key: str, title: str, body: str, kind: str, user_id: str | None = None,
           role: str | None = None, email: str | None = None, link: str = "") -> Notification:
    """Persisted in the same transaction as the business change; a dedupe key prevents duplicate alerts on retries."""
    existing = session.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    if session.get(KnownTenant, tenant_id) is None:
        session.add(KnownTenant(id=tenant_id))
    record = Notification(id=new_id("ntf"), tenant_id=tenant_id, recipient_user_id=user_id, recipient_role=role, recipient_email=email,
                          title=title[:160], body=body, kind=kind, link=link, dedupe_key=dedupe_key, created_at=utcnow(),
                          email_status="pending" if email else "none", email_attempts=0)
    session.add(record)
    return record


def visible(user_id: str, is_hr: bool):
    condition = Notification.recipient_user_id == user_id
    return or_(condition, Notification.recipient_role == "hr") if is_hr else condition


def send_pending(database, host: str, port: int, sender: str, batch: int = 25) -> int:
    """Email delivery is decoupled from approvals: failures are retried and never roll back the business decision."""
    if not host:
        return 0
    with database.session() as session:
        tenants = session.scalars(select(KnownTenant.id)).all()
    sent = 0
    for tenant_id in tenants:
        with database.session(tenant_id) as session:
            pending = session.scalars(select(Notification).where(Notification.email_status == "pending",
                                                                 Notification.email_attempts < MAX_EMAIL_ATTEMPTS)
                                      .order_by(Notification.created_at).limit(batch).with_for_update(skip_locked=True)).all()
            for note in pending:
                message = EmailMessage()
                message["From"], message["To"], message["Subject"] = sender, note.recipient_email, f"[Campus ERP] {note.title}"
                message.set_content(f"{note.body}\n\nOpen Campus ERP to review: {note.link or '/'}\n")
                note.email_attempts += 1
                try:
                    with smtplib.SMTP(host, port, timeout=10) as client:
                        client.send_message(message)
                    note.email_status = "sent"
                    sent += 1
                except (OSError, smtplib.SMTPException) as error:
                    note.email_status = "failed" if note.email_attempts >= MAX_EMAIL_ATTEMPTS else "pending"
                    log.warning(json.dumps({"service": "hr-worker", "event": "email_failed", "notification": note.id, "reason": repr(error)}))
    return sent
