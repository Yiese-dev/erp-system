"""Generate local-only secrets so `docker compose up` works on a clean machine.

Writes .env (if missing) with random database/broker/HMAC secrets and an .env-derived JWT key
pair / self-signed TLS certificate under .local/. Re-running is safe: existing secrets are kept.
"""
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"
GENERATE = {
    "POSTGRES_PASSWORD", "REPLICATION_PASSWORD", "IDENTITY_OWNER_PASSWORD", "IDENTITY_APP_PASSWORD",
    "ACADEMIC_OWNER_PASSWORD", "ACADEMIC_APP_PASSWORD", "FINANCE_OWNER_PASSWORD", "FINANCE_APP_PASSWORD",
    "HR_OWNER_PASSWORD", "HR_APP_PASSWORD", "RABBITMQ_PASSWORD", "GRAFANA_PASSWORD",
}
DEMO_SECRETS = {"WEBHOOK_SECRET", "QR_SECRET", "SIMULATOR_KEY"}


def write_env() -> None:
    if ENV_PATH.exists():
        print(".env already exists; leaving it unchanged.")
        return
    lines = []
    for line in EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            if key in GENERATE:
                value = secrets.token_urlsafe(24)
            elif key in DEMO_SECRETS:
                value = secrets.token_urlsafe(32)
            line = f"{key}={value}"
        lines.append(line)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote .env with randomly generated secrets. Review it (especially CAMPUS_DEMO) before a shared deployment.")


def generate_keys() -> None:
    data_dir = ROOT / ".local"
    subprocess.run([sys.executable, "-m", "packages.campus_common.keys", str(data_dir / "keys"), str(data_dir / "keys"), str(data_dir / "tls")],
                    check=True, cwd=ROOT)


if __name__ == "__main__":
    write_env()
    generate_keys()
    print("Bootstrap complete. Next: docker compose up --build")
"""One-command local bootstrap: generates .env (if missing) and the JWT/TLS key material used by docker compose up.

Usage: python scripts/bootstrap.py
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.campus_common.keys import jwt_keys, tls_certificate  # noqa: E402

ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def write_env() -> None:
    if ENV_PATH.exists():
        print(".env already exists; leaving it untouched")
        return
    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    for placeholder in ("change-me-postgres-superuser", "change-me-identity-owner", "change-me-identity-app",
                        "change-me-academic-owner", "change-me-academic-app", "change-me-finance-owner",
                        "change-me-finance-app", "change-me-hr-owner", "change-me-hr-app", "change-me-replication",
                        "change-me-rabbitmq", "change-me-grafana"):
        text = text.replace(placeholder, secrets.token_urlsafe(24), 1)
    ENV_PATH.write_text(text, encoding="utf-8")
    print("Wrote .env with randomly generated local secrets (CAMPUS_DEMO=1, demo webhook/QR secrets kept for the simulator).")


if __name__ == "__main__":
    write_env()
    data_dir = ROOT / ".local"
    jwt_keys(data_dir / "keys", data_dir / "keys")
    tls_certificate(data_dir / "tls")
    print("Bootstrap complete. Run: docker compose up --build")
