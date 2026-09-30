import logging
import os
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from packages.campus_common.config import app_role
from packages.campus_common.database import Database

INFRASTRUCTURE_TABLES = {"outbox_events", "processed_events", "known_tenants"}
log = logging.getLogger("campus.migrate")


def apply_schema(database: Database, metadata, runtime_role: str = "", row_level_security: bool = True) -> None:
    """Idempotent baseline migration: tables, row-level security, and least-privilege grants."""
    metadata.create_all(database.engine)
    if database.engine.dialect.name != "postgresql":
        return
    with database.engine.begin() as connection:
        for table in metadata.sorted_tables if row_level_security else []:
            if "tenant_id" not in table.c or table.name in INFRASTRUCTURE_TABLES:
                continue
            connection.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY'))
            exists = connection.execute(text("SELECT 1 FROM pg_policies WHERE tablename = :name AND policyname = 'tenant_isolation'"),
                                        {"name": table.name}).first()
            if not exists:
                connection.execute(text(
                    f'CREATE POLICY tenant_isolation ON "{table.name}" '
                    "USING (tenant_id = current_setting('app.tenant_id', true)) "
                    "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"))
        if runtime_role:
            connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{runtime_role}"'))


def run(service: str, metadata, seed=None, row_level_security: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = os.getenv(f"{service.upper()}_MIGRATION_URL") or os.getenv(f"{service.upper()}_DATABASE_URL")
    if not url:
        sys.exit(f"{service.upper()}_MIGRATION_URL is required.")
    database = Database(url)
    for attempt in range(30):
        try:
            database.ping()
            break
        except OperationalError:
            log.info("Waiting for database (%s/30)...", attempt + 1)
            time.sleep(2)
    apply_schema(database, metadata, app_role(), row_level_security)
    if seed and os.getenv("CAMPUS_DEMO") == "1":
        seed(database)
    log.info("%s schema ready", service)
