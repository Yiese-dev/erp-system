from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from packages.campus_common.config import Settings, load_settings
from packages.campus_common.database import Database
from packages.campus_common.http import create_application
from packages.campus_common.security import Actor, current_actor
from services.identity.app.domain import sessions
from services.identity.app.models import Base, LoginSession, Membership, Tenant, User
from services.identity.app.seed import seed

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
TenantRole = Literal["admin", "instructor", "finance", "hr", "employee", "student"]


class UserInput(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(max_length=254, pattern=EMAIL)
    role: TenantRole
    password: str = Field(min_length=12, max_length=128)


class UserPatch(BaseModel):
    role: TenantRole | None = None
    unlock: bool = False


class TenantInput(BaseModel):
    slug: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=3, max_length=200)
    admin_name: str = Field(min_length=3, max_length=160)
    admin_email: str = Field(max_length=254, pattern=EMAIL)
    admin_password: str = Field(min_length=12, max_length=128)


class TenantPatch(BaseModel):
    active: bool


class LoginInput(BaseModel):
    tenant: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class SwitchInput(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def create_app(settings: Settings):
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        if settings.create_schema:
            Base.metadata.create_all(database.engine)
            if settings.demo:
                seed(database, settings.demo_password)
        yield
        database.engine.dispose()

    app = create_application(settings, database, lifespan)
    prefix = "/api/v1/auth"

    def cookies(response: Response, refresh: str, csrf: str):
        response.set_cookie("campus_refresh", refresh, httponly=True, secure=settings.secure_cookies, samesite="strict", max_age=28800, path=prefix)
        response.set_cookie("campus_csrf", csrf, httponly=False, secure=settings.secure_cookies, samesite="strict", max_age=28800, path="/")

    def origin_guard(request: Request):
        if request.headers.get("origin") not in settings.allowed_origins:
            raise HTTPException(403, "This origin is not allowed.")

    def checked_actor(actor: Actor = Depends(current_actor)) -> Actor:
        sessions.validate(database, actor)
        return actor

    @app.post(f"{prefix}/login", tags=["Sessions"])
    def login(payload: LoginInput, request: Request, response: Response):
        origin_guard(request)
        body, refresh, csrf = sessions.login(database, settings, payload.email, payload.password, payload.tenant)
        cookies(response, refresh, csrf)
        return body

    @app.post(f"{prefix}/refresh", tags=["Sessions"])
    def refresh(request: Request, response: Response):
        origin_guard(request)
        body, token, csrf = sessions.rotate(database, settings, request.cookies.get("campus_refresh", ""), request.headers.get("x-csrf-token", ""))
        cookies(response, token, csrf)
        return body

    @app.get(f"{prefix}/validate", tags=["Sessions"])
    def validate(actor: Actor = Depends(checked_actor)):
        return {"user_id": actor.user_id, "tenant_id": actor.tenant_id, "role": actor.role}

    @app.get(f"{prefix}/me", tags=["Sessions"])
    def me(actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            return sessions.response_payload(db_session, settings, db_session.get(LoginSession, actor.session_id))

    @app.post(f"{prefix}/logout", status_code=204, tags=["Sessions"])
    def logout(response: Response, actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            db_session.get(LoginSession, actor.session_id).revoked = True
        response.delete_cookie("campus_refresh", path=prefix)
        response.delete_cookie("campus_csrf", path="/")

    @app.post(f"{prefix}/switch-tenant", tags=["Sessions"])
    def switch(payload: SwitchInput, response: Response, actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            membership = db_session.scalar(select(Membership).where(Membership.user_id == actor.user_id, Membership.tenant_id == payload.tenant_id))
            tenant = db_session.get(Tenant, payload.tenant_id)
            if not membership or not tenant or not tenant.active:
                raise HTTPException(404, "Institution membership not found.")
            db_session.get(LoginSession, actor.session_id).revoked = True
            session, refresh, csrf = sessions.new_session(db_session, db_session.get(User, actor.user_id), tenant)
            body = sessions.response_payload(db_session, settings, session)
        cookies(response, refresh, csrf)
        return body

    @app.get(f"{prefix}/sessions", tags=["Sessions"])
    def session_list(actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            records = db_session.scalars(select(LoginSession).where(LoginSession.user_id == actor.user_id, LoginSession.revoked.is_(False))).all()
            return [{"id": record.id, "created_at": record.created_at, "last_seen": record.last_seen,
                     "expires_at": record.expires_at, "current": record.id == actor.session_id} for record in records if sessions.valid_session(record)]

    @app.delete(f"{prefix}/sessions/{{session_id}}", status_code=204, tags=["Sessions"])
    def revoke(session_id: str, actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            record = db_session.get(LoginSession, session_id)
            if not record or record.user_id != actor.user_id:
                raise HTTPException(404, "Session not found.")
            record.revoked = True

    @app.post(f"{prefix}/password", status_code=204, tags=["Account"])
    def password(payload: PasswordInput, actor: Actor = Depends(checked_actor)):
        with database.session() as db_session:
            user = db_session.scalar(select(User).where(User.id == actor.user_id).with_for_update())
            if not sessions.verify_password(user.password_hash, payload.current_password):
                raise HTTPException(400, "The current password is incorrect.")
            user.password_hash = sessions.password_hasher.hash(payload.new_password)
            db_session.execute(update(LoginSession).where(LoginSession.user_id == user.id).values(revoked=True))

    # ---------- Institution user management (users:manage) ----------
    def member_view(user: User, membership: Membership) -> dict:
        return {"id": user.id, "name": user.name, "email": user.email, "role": membership.role, "active": user.active,
                "locked": user.locked_until > sessions.now(), "failed_attempts": user.failed_attempts}

    def manager(actor: Actor) -> Actor:
        actor.require("users:manage")
        return actor

    @app.get(f"{prefix}/users", tags=["Users"])
    def list_users(q: str = "", actor: Actor = Depends(checked_actor)) -> list[dict]:
        manager(actor)
        with database.session() as db_session:
            query = (select(User, Membership).join(Membership, Membership.user_id == User.id)
                     .where(Membership.tenant_id == actor.tenant_id).order_by(User.name))
            if q:
                query = query.where(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
            return [member_view(user, membership) for user, membership in db_session.execute(query.limit(200)).all()]

    @app.post(f"{prefix}/users", status_code=201, tags=["Users"])
    def create_user(payload: UserInput, actor: Actor = Depends(checked_actor)) -> dict:
        """Creates the account, or adds an existing account to this institution without changing its password."""
        manager(actor)
        with database.session() as db_session:
            email = payload.email.strip().lower()
            user = db_session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(id=f"usr_{uuid4().hex[:16]}", email=email, name=payload.name, active=True, failed_attempts=0, locked_until=0,
                            password_hash=sessions.password_hasher.hash(payload.password))
                db_session.add(user)
                db_session.flush()
            elif db_session.scalar(select(Membership.id).where(Membership.user_id == user.id, Membership.tenant_id == actor.tenant_id)):
                raise HTTPException(409, "This person already has an account in this institution.")
            membership = Membership(id=str(uuid4()), user_id=user.id, tenant_id=actor.tenant_id, role=payload.role)
            db_session.add(membership)
            return member_view(user, membership)

    @app.patch(f"{prefix}/users/{{user_id}}", tags=["Users"])
    def update_user(user_id: str, payload: UserPatch, actor: Actor = Depends(checked_actor)) -> dict:
        manager(actor)
        with database.session() as db_session:
            membership = db_session.scalar(select(Membership).where(Membership.user_id == user_id, Membership.tenant_id == actor.tenant_id))
            if membership is None:
                raise HTTPException(404, "User not found in this institution.")
            user = db_session.get(User, user_id)
            if payload.role and payload.role != membership.role:
                if user_id == actor.user_id:
                    raise HTTPException(409, "You cannot change your own role.")
                membership.role = payload.role
                db_session.execute(update(LoginSession).where(LoginSession.user_id == user_id, LoginSession.tenant_id == actor.tenant_id)
                                   .values(revoked=True))
            if payload.unlock:
                user.failed_attempts, user.locked_until = 0, 0
            return member_view(user, membership)

    @app.delete(f"{prefix}/users/{{user_id}}", status_code=204, tags=["Users"])
    def remove_user(user_id: str, actor: Actor = Depends(checked_actor)):
        manager(actor)
        if user_id == actor.user_id:
            raise HTTPException(409, "You cannot remove your own access.")
        with database.session() as db_session:
            membership = db_session.scalar(select(Membership).where(Membership.user_id == user_id, Membership.tenant_id == actor.tenant_id))
            if membership is None:
                raise HTTPException(404, "User not found in this institution.")
            db_session.delete(membership)
            db_session.execute(update(LoginSession).where(LoginSession.user_id == user_id, LoginSession.tenant_id == actor.tenant_id)
                               .values(revoked=True))

    # ---------- Platform administration (platform:manage) ----------
    @app.get("/api/v1/platform/tenants", tags=["Platform"])
    def list_tenants(actor: Actor = Depends(checked_actor)) -> list[dict]:
        actor.require("platform:manage")
        with database.session() as db_session:
            counts = dict(db_session.execute(select(Membership.tenant_id, func.count()).group_by(Membership.tenant_id)).all())
            return [{"id": row.id, "slug": row.slug, "name": row.name, "active": row.active, "members": counts.get(row.id, 0)}
                    for row in db_session.scalars(select(Tenant).order_by(Tenant.name)).all()]

    @app.post("/api/v1/platform/tenants", status_code=201, tags=["Platform"])
    def create_tenant(payload: TenantInput, actor: Actor = Depends(checked_actor)) -> dict:
        actor.require("platform:manage")
        with database.session() as db_session:
            if db_session.scalar(select(Tenant.id).where(Tenant.slug == payload.slug)):
                raise HTTPException(409, "That institution code is already in use.")
            tenant = Tenant(id=f"tn_{payload.slug.replace('-', '_')}", slug=payload.slug, name=payload.name, active=True)
            db_session.add(tenant)
            email = payload.admin_email.lower()
            admin = db_session.scalar(select(User).where(User.email == email))
            if admin is None:
                admin = User(id=f"usr_{uuid4().hex[:16]}", email=email, name=payload.admin_name, active=True, failed_attempts=0, locked_until=0,
                             password_hash=sessions.password_hasher.hash(payload.admin_password))
                db_session.add(admin)
            db_session.flush()
            db_session.add(Membership(id=str(uuid4()), user_id=admin.id, tenant_id=tenant.id, role="admin"))
            return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name, "active": True, "members": 1}

    @app.patch("/api/v1/platform/tenants/{tenant_id}", tags=["Platform"])
    def update_tenant(tenant_id: str, payload: TenantPatch, actor: Actor = Depends(checked_actor)) -> dict:
        actor.require("platform:manage")
        if tenant_id == actor.tenant_id and not payload.active:
            raise HTTPException(409, "You cannot suspend the institution you are signed in to.")
        with database.session() as db_session:
            tenant = db_session.get(Tenant, tenant_id)
            if tenant is None:
                raise HTTPException(404, "Institution not found.")
            tenant.active = payload.active
            if not payload.active:
                db_session.execute(update(LoginSession).where(LoginSession.tenant_id == tenant_id).values(revoked=True))
            return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name, "active": tenant.active}

    return app


def application():
    return create_app(load_settings("identity"))