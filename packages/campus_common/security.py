import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from packages.campus_common.config import Settings

bearer = HTTPBearer(auto_error=False)
ISSUER = "campus-erp-identity"
AUDIENCE = "campus-erp-api"


@dataclass(frozen=True)
class Actor:
    user_id: str
    tenant_id: str
    session_id: str
    role: str
    permissions: frozenset[str]
    name: str = ""
    tenant_name: str = ""

    def can(self, *permissions: str) -> bool:
        return bool(self.permissions.intersection(permissions))

    def require(self, *permissions: str) -> None:
        if not self.can(*permissions):
            raise HTTPException(403, "You do not have permission to perform this action.")


def issue_access(settings: Settings, user_id: str, tenant_id: str, session_id: str, role: str, permissions: list[str],
                 name: str = "", tenant_name: str = "") -> str:
    current = int(time.time())
    return jwt.encode(
        {"sub": user_id, "tid": tenant_id, "sid": session_id, "role": role, "permissions": permissions,
         "name": name, "tenant_name": tenant_name,
         "iss": ISSUER, "aud": AUDIENCE, "iat": current, "nbf": current, "exp": current + 600},
        settings.private_key, algorithm="RS256",
    )


def decode_access(settings: Settings, token: str) -> Actor:
    try:
        claims = jwt.decode(token, settings.public_key, algorithms=["RS256"], issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["sub", "tid", "sid", "exp", "iat", "role", "permissions"]})
        if not all(isinstance(claims[name], str) and claims[name] for name in ("sub", "tid", "sid", "role")):
            raise ValueError("Invalid claims")
        if not isinstance(claims["permissions"], list) or not all(isinstance(value, str) for value in claims["permissions"]):
            raise ValueError("Invalid permissions")
        name, tenant_name = claims.get("name", ""), claims.get("tenant_name", "")
        return Actor(claims["sub"], claims["tid"], claims["sid"], claims["role"], frozenset(claims["permissions"]),
                     name if isinstance(name, str) else "", tenant_name if isinstance(tenant_name, str) else "")
    except (jwt.InvalidTokenError, ValueError, KeyError) as error:
        raise HTTPException(401, "Your session has expired. Please sign in again.") from error


def current_actor(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
    if credentials is None:
        raise HTTPException(401, "Please sign in to continue.")
    settings = request.app.state.settings
    actor = decode_access(settings, credentials.credentials)
    if settings.service != "identity" and settings.identity_url:
        try:
            response = httpx.get(f"{settings.identity_url}/api/v1/auth/validate",
                                headers={"Authorization": f"Bearer {credentials.credentials}"}, timeout=5)
        except httpx.HTTPError as error:
            raise HTTPException(503, "Session validation is temporarily unavailable.") from error
        if response.status_code != 200:
            raise HTTPException(401 if response.status_code == 401 else 503, "Your session is not available.")
    return actor