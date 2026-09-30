import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from packages.campus_common.config import Settings
from services.identity.app.main import create_app


@pytest.fixture
def client(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(service="identity", database_url=f"sqlite:///{tmp_path / 'identity.db'}", demo=True,
                        secure_cookies=False, allowed_origins=("http://testserver",), create_schema=True,
                        private_key=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
                        public_key=key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def sign_in(client, password="CampusDemo!2026", tenant="ictu", email="admin@campus.test"):
    return client.post("/api/v1/auth/login", json={"tenant": tenant, "email": email, "password": password}, headers={"Origin": "http://testserver"})


def test_login_and_session_validation(client):
    response = sign_in(client)
    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == "tn_ictu"
    assert "hr:write" in response.json()["user"]["permissions"]
    token = response.json()["access_token"]
    assert client.get("/api/v1/auth/validate", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert "HttpOnly" in response.headers.get_list("set-cookie")[0]


def test_refresh_rotation_and_reuse_revokes_family(client):
    first = sign_in(client)
    old_refresh = client.cookies.get("campus_refresh")
    csrf = client.cookies.get("campus_csrf")
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    rotated = client.post("/api/v1/auth/refresh", headers=headers)
    assert rotated.status_code == 200
    assert client.cookies.get("campus_refresh") != old_refresh
    replay = client.post("/api/v1/auth/refresh", headers={**headers, "Cookie": f"campus_refresh={old_refresh}"})
    assert replay.status_code == 401
    assert client.get("/api/v1/auth/validate", headers={"Authorization": f"Bearer {first.json()['access_token']}"}).status_code == 401


def test_refresh_needs_csrf_and_trusted_origin(client):
    sign_in(client)
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "http://testserver"}).status_code == 403
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "https://attacker.test", "X-CSRF-Token": client.cookies.get("campus_csrf")}).status_code == 403


def test_lockout_is_persisted_after_failed_requests(client):
    for attempt in range(5):
        assert sign_in(client, password="wrong").status_code == 401
    assert sign_in(client).status_code == 429


def test_switching_tenant_invalidates_old_session(client):
    token = sign_in(client).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/auth/switch-tenant", json={"tenant_id": "unknown"}, headers=headers).status_code == 404
    switched = client.post("/api/v1/auth/switch-tenant", json={"tenant_id": "tn_atlantic"}, headers=headers)
    assert switched.status_code == 200
    assert switched.json()["tenant"]["id"] == "tn_atlantic"
    assert client.get("/api/v1/auth/validate", headers=headers).status_code == 401


def test_idle_session_expires(client, monkeypatch):
    from services.identity.app.domain import sessions
    token = sign_in(client).json()["access_token"]
    future = sessions.now() + 1801
    monkeypatch.setattr(sessions, "now", lambda: future)
    assert client.get("/api/v1/auth/validate", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_change_revokes_session(client):
    token = sign_in(client).json()["access_token"]
    response = client.post("/api/v1/auth/password", headers={"Authorization": f"Bearer {token}"},
                           json={"current_password": "CampusDemo!2026", "new_password": "ChangedSecret!2026"})
    assert response.status_code == 204
    assert client.get("/api/v1/auth/validate", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert sign_in(client, password="ChangedSecret!2026").status_code == 200


def test_student_cannot_gain_staff_permissions(client):
    response = sign_in(client, email="student@campus.test")
    assert response.json()["user"]["permissions"] == ["academic:self", "finance:self"]
    assert sign_in(client, tenant="unknown").status_code == 401