from services.identity.tests.test_sessions import client, sign_in  # noqa: F401 - reuse the seeded Identity fixture

P = "/api/v1/auth"


def auth(client, email="admin@campus.test", tenant="ictu", password="CampusDemo!2026"):
    return {"Authorization": f"Bearer {sign_in(client, password=password, email=email, tenant=tenant).json()['access_token']}"}


def test_admin_manages_users_within_own_tenant_only(client):
    admin = auth(client)
    created = client.post(f"{P}/users", headers=admin, json={"name": "New Lecturer", "email": "new.lecturer@campus.test",
                                                              "role": "instructor", "password": "Lecturer!2026x"})
    assert created.status_code == 201 and created.json()["role"] == "instructor"
    assert client.post(f"{P}/users", headers=admin, json={"name": "New Lecturer", "email": "new.lecturer@campus.test",
                                                          "role": "instructor", "password": "Lecturer!2026x"}).status_code == 409
    assert sign_in(client, email="new.lecturer@campus.test", password="Lecturer!2026x").status_code == 200
    assert sign_in(client, email="new.lecturer@campus.test", password="Lecturer!2026x", tenant="atlantic").status_code == 401
    lecturer_token = auth(client, "new.lecturer@campus.test", password="Lecturer!2026x")
    promoted = client.patch(f"{P}/users/{created.json()['id']}", headers=admin, json={"role": "hr"})
    assert promoted.json()["role"] == "hr"
    assert client.get(f"{P}/validate", headers=lecturer_token).status_code == 401
    assert client.patch(f"{P}/users/usr_admin", headers=admin, json={"role": "student"}).status_code == 409
    assert client.get(f"{P}/users", headers=auth(client, "student@campus.test")).status_code == 403
    atlantic_admin = auth(client, tenant="atlantic")
    assert client.patch(f"{P}/users/{created.json()['id']}", headers=atlantic_admin, json={"unlock": True}).status_code == 404
    assert client.delete(f"{P}/users/{created.json()['id']}", headers=admin).status_code == 204
    assert sign_in(client, email="new.lecturer@campus.test", password="Lecturer!2026x").status_code == 401


def test_admin_can_unlock_a_locked_account(client):
    for _ in range(5):
        sign_in(client, email="student@campus.test", password="wrong-password")
    assert sign_in(client, email="student@campus.test").status_code == 429
    listed = {row["id"]: row for row in client.get(f"{P}/users", headers=auth(client)).json()}
    assert listed["usr_student"]["locked"] is True
    client.patch(f"{P}/users/usr_student", headers=auth(client), json={"unlock": True})
    assert sign_in(client, email="student@campus.test").status_code == 200


def test_platform_operator_provisions_tenants(client):
    operator = auth(client, "superadmin@campus.test")
    assert client.get(f"{P}/users", headers=operator).status_code == 403
    created = client.post("/api/v1/platform/tenants", headers=operator, json={
        "slug": "coastal", "name": "Coastal Polytechnic", "admin_name": "Rita Ekwe", "admin_email": "rita@coastal.test",
        "admin_password": "CoastalAdmin!2026"})
    assert created.status_code == 201
    assert sign_in(client, email="rita@coastal.test", password="CoastalAdmin!2026", tenant="coastal").status_code == 200
    assert client.post("/api/v1/platform/tenants", headers=auth(client), json={
        "slug": "rogue", "name": "Rogue", "admin_name": "Rogue Admin", "admin_email": "r@r.test", "admin_password": "RogueAdmin!2026"}).status_code == 403
    suspended = client.patch(f"/api/v1/platform/tenants/{created.json()['id']}", headers=operator, json={"active": False})
    assert suspended.json()["active"] is False
    assert sign_in(client, email="rita@coastal.test", password="CoastalAdmin!2026", tenant="coastal").status_code == 401
