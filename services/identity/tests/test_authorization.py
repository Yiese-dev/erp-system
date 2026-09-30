import unittest

from services.identity.app.domain.authorization import Principal, Role


class AuthorizationTests(unittest.TestCase):
    def test_admin_cannot_cross_tenant_boundary(self):
        principal = Principal("user-a", "tenant-a", Role.ADMIN, "session-a")
        self.assertTrue(principal.allows("academic:write", "tenant-a"))
        self.assertFalse(principal.allows("academic:write", "tenant-b"))

    def test_student_permissions_do_not_allow_publishing(self):
        principal = Principal("student-a", "tenant-a", Role.STUDENT, "session-a")
        self.assertTrue(principal.allows("academic:self", "tenant-a"))
        self.assertFalse(principal.allows("academic:write", "tenant-a"))
        self.assertTrue(principal.owns("student-a", "tenant-a"))
        self.assertFalse(principal.owns("student-b", "tenant-a"))
        self.assertFalse(principal.owns("student-a", "tenant-b"))

    def test_platform_role_does_not_bypass_business_permissions(self):
        principal = Principal("operator", "tenant-a", Role.SUPER_ADMIN, "session-a")
        self.assertTrue(principal.allows("platform:manage", "tenant-a"))
        self.assertFalse(principal.allows("finance:read", "tenant-a"))

    def test_finance_staff_cannot_read_payroll(self):
        principal = Principal("clerk", "tenant-a", Role.FINANCE, "session-a")
        self.assertTrue(principal.allows("finance:write", "tenant-a"))
        self.assertFalse(principal.allows("hr:read", "tenant-a"))