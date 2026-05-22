from fastapi import Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status

from src.config import settings

_ALL_SCOPES = [
    "prompt:read",
    "prompt:read:restricted",
    "prompt:create",
    "prompt:write",
    "prompt:publish",
    "prompt:rate",
    "prompt:image",
    "admin:manage_taxonomy",
    "admin:manage_keys",
    "admin:manage_users",
]

_bearer_scheme = HTTPBearer(auto_error=False)


class StubUser:
    def __init__(self, external_id: str, name: str, email: str, scope: list[str]):
        self.id = 1  # fixed dev user id
        self.external_id = external_id
        self.name = name
        self.email = email
        self.scope = scope

    def has_scope(self, permission: str) -> bool:
        return permission in self.scope


_DEV_USER = StubUser(
    external_id="dev-user-001",
    name="Dev User",
    email="dev@example.com",
    scope=_ALL_SCOPES,
)


async def get_current_user_stub(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> StubUser:
    if credentials is None or credentials.credentials != settings.DEV_STUB_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Missing or invalid auth token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _DEV_USER


async def get_optional_user_stub(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> StubUser | None:
    if credentials is None:
        return None
    if credentials.credentials != settings.DEV_STUB_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid auth token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _DEV_USER
