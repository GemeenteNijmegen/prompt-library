import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.user import User
from src.utils.jwt_utils import JWTExpiredError, JWTInvalidError, decode_and_verify

_log = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser:
    def __init__(self, db_user: User, scope: list[str], org_id: str = "", azp: str = ""):
        self.id = db_user.id
        self.external_id = db_user.external_id
        self.org_id = org_id
        self.name = db_user.name
        self.email = db_user.email
        self.avatar_url = db_user.avatar_url
        self.last_seen_at = db_user.last_seen_at
        self.scope = scope
        self.azp = azp

    def has_scope(self, permission: str) -> bool:
        return permission in self.scope

    @property
    def is_org_admin(self) -> bool:
        return "admin:manage_users" in self.scope


def _upsert_user(db: Session, claims: dict) -> User:
    external_id = claims["sub"]
    org_id = claims.get("org_id", "")
    user = db.query(User).filter(User.external_id == external_id).first()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            external_id=external_id,
            org_id=org_id,
            name=claims.get("name"),
            email=claims.get("email"),
            avatar_url=claims.get("avatar_url"),
            last_seen_at=now,
        )
        db.add(user)
    else:
        user.org_id = org_id
        user.name = claims.get("name", user.name)
        user.email = claims.get("email", user.email)
        user.avatar_url = claims.get("avatar_url", user.avatar_url)
        user.last_seen_at = now
    db.commit()
    db.refresh(user)
    return user


def _resolve_scope(claims: dict) -> list[str]:
    scope = claims.get("scope", [])
    if isinstance(scope, str):
        scope = scope.split()
    return scope


def _build_authenticated_user(claims: dict, db: Session) -> "AuthenticatedUser":
    user = _upsert_user(db, claims)
    scope = _resolve_scope(claims)
    org_id = claims.get("org_id", "")
    azp = claims.get("azp", "")
    _log.debug("auth azp=%s sub=%s org=%s", azp, claims.get("sub"), org_id)
    return AuthenticatedUser(user, scope, org_id=org_id, azp=azp)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Missing auth token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_and_verify(credentials.credentials)
    except JWTExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Token has expired"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (JWTInvalidError, Exception):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid auth token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _build_authenticated_user(claims, db)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedUser | None:
    if credentials is None:
        return None
    try:
        claims = decode_and_verify(credentials.credentials)
    except JWTExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Token has expired"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (JWTInvalidError, Exception):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid auth token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _build_authenticated_user(claims, db)
