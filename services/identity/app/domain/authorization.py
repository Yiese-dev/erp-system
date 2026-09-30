from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    INSTRUCTOR = "instructor"
    FINANCE = "finance"
    HR = "hr"
    EMPLOYEE = "employee"
    STUDENT = "student"


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.SUPER_ADMIN: frozenset({"platform:manage"}),
    Role.ADMIN: frozenset({"academic:read", "academic:write", "finance:read", "finance:write", "hr:read", "hr:write", "hr:self", "users:manage"}),
    Role.INSTRUCTOR: frozenset({"academic:read", "academic:teach", "hr:self"}),
    Role.FINANCE: frozenset({"finance:read", "finance:write", "catalog:read", "hr:self"}),
    Role.HR: frozenset({"hr:read", "hr:write", "hr:self"}),
    Role.EMPLOYEE: frozenset({"hr:self"}),
    Role.STUDENT: frozenset({"academic:self", "finance:self"}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: Role
    session_id: str

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS[self.role]

    def allows(self, permission: str, tenant_id: str) -> bool:
        return self.tenant_id == tenant_id and permission in self.permissions

    def owns(self, owner_id: str, tenant_id: str) -> bool:
        return self.tenant_id == tenant_id and self.user_id == owner_id