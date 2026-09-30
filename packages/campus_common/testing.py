from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from packages.campus_common.config import Settings
from packages.campus_common.security import issue_access

ROLE_PERMISSIONS = {
    "admin": ["academic:read", "academic:write", "finance:read", "finance:write", "hr:read", "hr:write", "hr:self", "users:manage"],
    "instructor": ["academic:read", "academic:teach", "hr:self"],
    "finance": ["finance:read", "finance:write", "catalog:read", "hr:self"],
    "hr": ["hr:read", "hr:write", "hr:self"],
    "employee": ["hr:self"],
    "student": ["academic:self", "finance:self"],
}


def key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


def settings_for(service: str, database_url: str, **overrides) -> Settings:
    private, public = key_pair()
    return Settings(service=service, database_url=database_url, public_key=public, private_key=private, create_schema=True,
                    secure_cookies=False, **overrides)


def bearer(settings: Settings, role: str, tenant_id: str = "tn_a", user_id: str | None = None) -> dict[str, str]:
    token = issue_access(settings, user_id or f"usr_{role}", tenant_id, f"ses_{role}", role, ROLE_PERMISSIONS[role],
                         f"Test {role}", f"Tenant {tenant_id}")
    return {"Authorization": f"Bearer {token}"}
