import hashlib
import hmac
import secrets
import time
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import select

from packages.campus_common.config import Settings
from packages.campus_common.database import Database
from packages.campus_common.security import Actor, issue_access
from services.identity.app.domain.authorization import ROLE_PERMISSIONS, Role
from services.identity.app.models import LoginSession, Membership, RefreshToken, Tenant, User

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = password_hasher.hash(secrets.token_hex(16))


def now() -> int:
    return int(time.time())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def valid_session(session: LoginSession | None) -> bool:
    return session is not None and not session.revoked and session.expires_at > now() and session.last_seen + 1800 > now()


def response_payload(db_session, settings: Settings, session: LoginSession) -> dict:
    user = db_session.get(User, session.user_id)
    tenant = db_session.get(Tenant, session.tenant_id)
    membership = db_session.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant.id))
    if not user.active or not tenant.active or membership is None:
        raise HTTPException(401, "This account is no longer available.")
    permissions = sorted(ROLE_PERMISSIONS[Role(membership.role)])
    tenants = db_session.execute(select(Tenant, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
                                 .where(Membership.user_id == user.id, Tenant.active.is_(True))).all()
    return {
        "access_token": issue_access(settings, user.id, tenant.id, session.id, membership.role, permissions, user.name, tenant.name),
        "token_type": "bearer", "expires_in": 600,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": membership.role, "permissions": permissions},
        "tenant": {"id": tenant.id, "slug": tenant.slug, "name": tenant.name},
        "tenants": [{"id": item.id, "slug": item.slug, "name": item.name, "role": role} for item, role in tenants],
    }


def new_session(db_session, user: User, tenant: Tenant) -> tuple[LoginSession, str, str]:
    refresh = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    current = now()
    session = LoginSession(id=str(uuid4()), user_id=user.id, tenant_id=tenant.id,
                           created_at=current, expires_at=current + 28800, last_seen=current, csrf_hash=digest(csrf), revoked=False)
    db_session.add(session)
    db_session.flush()
    db_session.add(RefreshToken(token_hash=digest(refresh), session_id=session.id, expires_at=session.expires_at, used=False))
    return session, refresh, csrf


def login(database: Database, settings: Settings, email: str, password: str, tenant_slug: str) -> tuple[dict, str, str]:
    with database.session() as db_session:
        user = db_session.scalar(select(User).where(User.email == email.strip().lower()).with_for_update())
        tenant = db_session.scalar(select(Tenant).where(Tenant.slug == tenant_slug.strip().lower(), Tenant.active.is_(True)))
        membership = None
        if user and tenant:
            membership = db_session.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant.id))
        verified = verify_password(user.password_hash if user else DUMMY_HASH, password)
        if not user or not user.active or not tenant or not membership:
            raise HTTPException(401, "Invalid institution, email, or password.")
        if user.locked_until > now():
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        if not verified:
            user.failed_attempts = (0 if user.locked_until else user.failed_attempts) + 1
            user.locked_until = now() + 900 if user.failed_attempts >= 5 else 0
            db_session.commit()
            raise HTTPException(401, "Invalid institution, email, or password.")
        user.failed_attempts = 0
        user.locked_until = 0
        session, refresh, csrf = new_session(db_session, user, tenant)
        return response_payload(db_session, settings, session), refresh, csrf


def rotate(database: Database, settings: Settings, raw_token: str, csrf: str) -> tuple[dict, str, str]:
    with database.session() as db_session:
        token = db_session.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest(raw_token)).with_for_update())
        session = db_session.scalar(select(LoginSession).where(LoginSession.id == token.session_id).with_for_update()) if token else None
        if not token or not session:
            raise HTTPException(401, "Your session has expired. Please sign in again.")
        if token.used:
            session.revoked = True
            db_session.commit()
            raise HTTPException(401, "Session reuse detected. Please sign in again.")
        if not valid_session(session) or token.expires_at <= now():
            raise HTTPException(401, "Your session has expired. Please sign in again.")
        if not csrf or not hmac.compare_digest(digest(csrf), session.csrf_hash):
            raise HTTPException(403, "Invalid session verification.")
        token.used = True
        session.last_seen = now()
        refresh = secrets.token_urlsafe(48)
        db_session.add(RefreshToken(token_hash=digest(refresh), session_id=session.id, expires_at=session.expires_at, used=False))
        return response_payload(db_session, settings, session), refresh, csrf


def validate(database: Database, actor: Actor) -> None:
    with database.session() as db_session:
        session = db_session.get(LoginSession, actor.session_id)
        user = db_session.get(User, actor.user_id)
        tenant = db_session.get(Tenant, actor.tenant_id)
        membership = db_session.scalar(select(Membership).where(Membership.user_id == actor.user_id, Membership.tenant_id == actor.tenant_id))
        if (not valid_session(session) or not user or not user.active or not tenant or not tenant.active
                or session.user_id != actor.user_id or session.tenant_id != actor.tenant_id
                or not membership or membership.role != actor.role):
            raise HTTPException(401, "Your session has expired. Please sign in again.")
        if now() - session.last_seen > 60:
            session.last_seen = now()