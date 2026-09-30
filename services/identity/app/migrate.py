import os

from packages.campus_common.migrate import run
from services.identity.app.models import Base
from services.identity.app.seed import seed

if __name__ == "__main__":
    # Identity is the membership authority and is queried across tenants during sign-in, so it is not tenant-RLS-scoped.
    run("identity", Base.metadata, lambda database: seed(database, os.getenv("CAMPUS_DEMO_PASSWORD", "CampusDemo!2026")), row_level_security=False)
