import os
import re
from dataclasses import dataclass
from pathlib import Path

LOCAL_SECRET = "local-development-only-secret"


@dataclass(frozen=True)
class Settings:
    service: str
    database_url: str
    public_key: str
    private_key: str = ""
    demo: bool = False
    secure_cookies: bool = True
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:8080")
    identity_url: str = ""
    demo_password: str = "CampusDemo!2026"
    create_schema: bool = False
    broker_url: str = ""
    webhook_secret: str = LOCAL_SECRET
    qr_secret: str = LOCAL_SECRET
    simulator_key: str = LOCAL_SECRET
    simulator_url: str = ""
    callback_base_url: str = "http://gateway"
    smtp_host: str = ""
    smtp_port: int = 1025
    mail_from: str = "Campus ERP <no-reply@campus.test>"
    hr_mailbox: str = "hr-office@campus.test"
    log_host: str = ""


def _read(path: str) -> str:
    file = Path(path)
    return file.read_text(encoding="utf-8") if file.is_file() else ""


def app_role() -> str:
    role = os.getenv("DATABASE_APP_ROLE", "")
    if role and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise RuntimeError("DATABASE_APP_ROLE is invalid.")
    return role


def load_settings(service: str) -> Settings:
    data_dir = Path(os.getenv("CAMPUS_DATA_DIR", ".local"))
    public_key = _read(os.getenv("JWT_PUBLIC_KEY_FILE", str(data_dir / "keys" / "public.pem")))
    private_key = _read(os.getenv("JWT_PRIVATE_KEY_FILE", str(data_dir / "keys" / "private.pem"))) if service == "identity" else ""
    if not public_key or (service == "identity" and not private_key):
        raise RuntimeError("JWT signing keys are missing. Run python scripts/bootstrap.py or docker compose up.")
    demo = os.getenv("CAMPUS_DEMO", "0") == "1"
    local = os.getenv("CAMPUS_LOCAL", "0") == "1"
    database_url = os.getenv(f"{service.upper()}_DATABASE_URL", "")
    if not database_url and not local:
        raise RuntimeError(f"{service.upper()}_DATABASE_URL is required.")
    if not database_url:
        data_dir.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(data_dir / (service + '.sqlite')).as_posix()}"
    secrets = {name: os.getenv(name.upper(), LOCAL_SECRET) for name in ("webhook_secret", "qr_secret", "simulator_key")}
    if not demo and not local and LOCAL_SECRET in secrets.values():
        raise RuntimeError("Refusing to start with development secrets outside demo mode.")
    return Settings(
        service=service,
        database_url=database_url,
        public_key=public_key,
        private_key=private_key,
        demo=demo,
        secure_cookies=not local,
        allowed_origins=tuple(filter(None, os.getenv("CAMPUS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(","))),
        identity_url=os.getenv("IDENTITY_URL", ""),
        demo_password=os.getenv("CAMPUS_DEMO_PASSWORD", "CampusDemo!2026"),
        create_schema=local,
        broker_url=os.getenv("BROKER_URL", ""),
        simulator_url=os.getenv("SIMULATOR_URL", ""),
        callback_base_url=os.getenv("CALLBACK_BASE_URL", "http://gateway"),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "1025")),
        mail_from=os.getenv("MAIL_FROM", "Campus ERP <no-reply@campus.test>"),
        hr_mailbox=os.getenv("HR_MAILBOX", "hr-office@campus.test"),
        log_host=os.getenv("LOG_HOST", ""),
        **secrets,
    )