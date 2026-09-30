import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, String, TypeDecorator, UniqueConstraint, create_engine, event, text
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria
from sqlalchemy.pool import StaticPool

from packages.campus_common.errors import DomainError

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


# Africa/Douala observes West Africa Time (UTC+1) with no daylight saving.
LOCAL_TZ = timezone(timedelta(hours=1), "WAT")


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self):
        return datetime

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware.")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def tenant_args(*extra, refs: dict[str, str] | None = None, keyed: bool = True) -> tuple:
    """Composite (tenant_id, id) keys make the database reject cross-tenant parent references."""
    items: list = [UniqueConstraint("tenant_id", "id")] if keyed else []
    for column, target in (refs or {}).items():
        items.append(ForeignKeyConstraint(["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"]))
    return (*items, *extra)


def fetch(session: Session, model, record_id: str, label: str = "Record"):
    record = session.get(model, record_id)
    if record is None:
        raise DomainError(f"{label} not found.", 404)
    return record


class TenantRow:
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)


@event.listens_for(Session, "do_orm_execute")
def scope_tenant_queries(state):
    tenant_id = state.session.info.get("tenant_id")
    if tenant_id and (state.is_select or state.is_update or state.is_delete):
        state.statement = state.statement.options(
            with_loader_criteria(TenantRow, lambda row: row.tenant_id == tenant_id, include_aliases=True)
        )


@event.listens_for(Session, "before_flush")
def guard_tenant_writes(session, flush_context, instances):
    tenant_id = session.info.get("tenant_id")
    for record in session.new.union(session.dirty).union(session.deleted):
        if isinstance(record, TenantRow) and record.tenant_id != tenant_id:
            raise ValueError("A tenant-scoped transaction cannot write another tenant's record.")


class Database:
    def __init__(self, url: str):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        else:
            options.update(pool_size=int(os.getenv("DB_POOL_SIZE", "10")), max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
                           pool_recycle=1800)
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._sqlite_foreign_keys)

    @staticmethod
    def _sqlite_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    def create_all(self, metadata) -> None:
        metadata.create_all(self.engine)

    @contextmanager
    def session(self, tenant_id: str | None = None) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False, info={"tenant_id": tenant_id}) as session:
            with session.begin():
                if tenant_id and self.engine.dialect.name == "postgresql":
                    session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id})
                yield session

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))