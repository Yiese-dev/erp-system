from sqlalchemy import select

from packages.campus_common import demo
from packages.campus_common.database import Database
from services.identity.app.domain.sessions import password_hasher
from services.identity.app.models import Membership, Tenant, User


def seed(database: Database, password: str) -> None:
    with database.session() as db_session:
        if db_session.scalar(select(Tenant.id).limit(1)):
            return
        for tenant_id, slug, name in demo.TENANTS:
            db_session.add(Tenant(id=tenant_id, slug=slug, name=name, active=True))
        encoded = password_hasher.hash(password)
        for user_id, email, name, _ in demo.USERS.values():
            db_session.add(User(id=user_id, email=email, name=name, password_hash=encoded, active=True, failed_attempts=0, locked_until=0))
        db_session.flush()
        for tenant_id, _, _ in demo.TENANTS:
            for user_id, _, _, role in demo.USERS.values():
                if role == "super_admin" and tenant_id != demo.TENANTS[0][0]:
                    continue
                db_session.add(Membership(id=f"{tenant_id}_{user_id}", tenant_id=tenant_id, user_id=user_id, role=role))