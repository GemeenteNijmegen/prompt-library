import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.api_key import ApiKey
from src.models.user import User
from src.services.api_key_service import hash_token, is_api_key
from src.utils.jwt_utils import JWTExpiredError, JWTInvalidError, decode_and_verify

_log = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "UNAUTHORIZED", "message": message}},
        headers={"WWW-Authenticate": "Bearer"},
    )


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

    @property
    def is_api_key(self) -> bool:
        """True if this identity was established via an opaque API key."""
        return self.azp.startswith("apikey:")


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
    """Extract scopes from the token.

    Keycloak production tokens carry permissions as realm roles in
    ``realm_access.roles`` and are checked first.  Standard OAuth2 tokens
    (and HS256 dev tokens) carry them in the ``scope`` claim, either as a
    space-separated string or a JSON array.  The two formats are mutually
    exclusive: when ``realm_access.roles`` is present it is used exclusively
    to avoid accidentally admitting OIDC scopes (``openid``, ``profile``, …)
    that a Keycloak token also places in the ``scope`` string."""
    realm_roles = ((claims.get("realm_access") or {}).get("roles") or [])
    if realm_roles:
        return list(realm_roles)

    scope = claims.get("scope")
    if isinstance(scope, list):
        return scope
    if isinstance(scope, str):
        return scope.split()
    return []


def _build_authenticated_user(claims: dict, db: Session) -> "AuthenticatedUser":
    user = _upsert_user(db, claims)
    scope = _resolve_scope(claims)
    org_id = claims.get("org_id", "")
    azp = claims.get("azp", "")
    _log.debug("auth azp=%s sub=%s org=%s", azp, claims.get("sub"), org_id)
    return AuthenticatedUser(user, scope, org_id=org_id, azp=azp)


def _authenticate_api_key(token: str, db: Session) -> "AuthenticatedUser":
    """Resolve an opaque API key to its owner (ADR 0004 §"API-key issuance").

    The key's scopes are the snapshot taken at issuance; ``org_id`` is read live
    from the owning user row (identity, not capability). ``azp`` is set to
    ``apikey:<id>`` so request logs and audit events can attribute the call to a
    specific key — the same forensic role ``azp`` plays for OAuth clients.
    """
    key = db.query(ApiKey).filter(ApiKey.token_hash == hash_token(token)).first()
    if key is None:
        raise _unauthorized("Invalid API key")
    if key.revoked_at is not None:
        raise _unauthorized("API key has been revoked")
    now = datetime.now(timezone.utc)
    if key.expires_at is not None and key.expires_at < now.replace(tzinfo=None):
        raise _unauthorized("API key has expired")

    user = db.query(User).filter(User.id == key.user_id).first()
    if user is None:
        raise _unauthorized("Invalid API key")

    key.last_used_at = now
    db.commit()

    scope = key.scopes.split()
    _log.debug("auth apikey id=%s sub=%s org=%s", key.id, user.external_id, user.org_id)
    return AuthenticatedUser(user, scope, org_id=user.org_id, azp=f"apikey:{key.id}")


def _authenticate(
    credentials: HTTPAuthorizationCredentials | None, db: Session
) -> "AuthenticatedUser":
    """Resolve a bearer credential — opaque API key or Keycloak JWT — to a user.

    Both front doors converge on a single ``AuthenticatedUser`` that flows
    through one authorization path. The credential is dispatched by prefix: keys
    start with ``pg_`` (see api_key_service), everything else is treated as a JWT.
    """
    if credentials is None:
        raise _unauthorized("Missing auth token")

    token = credentials.credentials
    if is_api_key(token):
        return _authenticate_api_key(token, db)

    try:
        claims = decode_and_verify(token)
    except JWTExpiredError:
        raise _unauthorized("Token has expired")
    except (JWTInvalidError, Exception):
        raise _unauthorized("Invalid auth token")
    if "sub" not in claims:
        raise _unauthorized("Token missing required claim: sub")
    return _build_authenticated_user(claims, db)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    return _authenticate(credentials, db)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedUser | None:
    if credentials is None:
        return None
    return _authenticate(credentials, db)
