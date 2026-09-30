"""Seed local SQLite databases for a quick non-Docker smoke run (no PostgreSQL/RabbitMQ required).

Usage: .venv\\Scripts\\python.exe scripts\\seed_local.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CAMPUS_LOCAL"] = "1"
os.environ["CAMPUS_DEMO"] = "1"
os.environ["CAMPUS_DATA_DIR"] = str(ROOT / ".local")

from packages.campus_common.database import Database  # noqa: E402

data_dir = Path(os.environ["CAMPUS_DATA_DIR"])
data_dir.mkdir(parents=True, exist_ok=True)


def seed_service(name: str, base_module: str, seed_call) -> None:
    database = Database(f"sqlite:///{(data_dir / (name + '.sqlite')).as_posix()}")
    base = __import__(f"{base_module}.models", fromlist=["Base"]).Base
    base.metadata.create_all(database.engine)
    seed_call(database)
    print(f"seeded {name}")


from services.identity.app.seed import seed as identity_seed  # noqa: E402
seed_service("identity", "services.identity.app", lambda db: identity_seed(db, "CampusDemo!2026"))

from services.academic.app.seed import seed as academic_seed  # noqa: E402
seed_service("academic", "services.academic.app", academic_seed)

from services.finance.app.seed import seed as finance_seed  # noqa: E402
seed_service("finance", "services.finance.app", finance_seed)

from services.hr.app.seed import seed as hr_seed  # noqa: E402
seed_service("hr", "services.hr.app", hr_seed)

print("Local SQLite seed complete.")
