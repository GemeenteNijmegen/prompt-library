import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

_log = logging.getLogger(__name__)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.dependencies import get_current_user, get_db
from src.models.api_key import ApiKey
from src.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyMetadata
from src.schemas.user import UserProfile
from src.services.audit_service import write_event
from src.services.keycloak_client import KeycloakClient, KeycloakError, get_keycloak_client

router = APIRouter(tags=["me"])

_bearer_scheme = HTTPBearer(auto_error=False)


def _require_scope(scope: str):
    def dep(user=Depends(get_current_user)):
        if not user.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": f"Requires {scope}"}},
            )
        return user
    return dep


@router.get("/me", response_model=dict)
def get_me(caller=Depends(get_current_user)):
    profile = UserProfile(
        id=caller.id,
        external_id=caller.external_id,
        name=caller.name,
        email=caller.email,
        avatar_url=caller.avatar_url,
        last_seen_at=caller.last_seen_at,
    )
    return {"data": profile.model_dump()}


@router.post("/me/api-keys", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreate,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    caller=Depends(_require_scope("apikey:create")),
    db: Session = Depends(get_db),
    kc: KeycloakClient = Depends(get_keycloak_client),
):
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        offline_token, session_id = kc.issue_offline_token(credentials.credentials)
    except KeycloakError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": {"code": "KEYCLOAK_ERROR", "message": str(exc)}},
        )

    key = ApiKey(
        user_id=caller.id,
        label=body.label,
        keycloak_session_id=session_id,
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    write_event(
        db,
        entity_type="apikey",
        entity_id=str(key.id),
        action="issued",
        caller=caller,
        details={"label": body.label},
    )

    result = ApiKeyCreated(
        id=key.id,
        label=key.label,
        created_at=key.created_at,
        token=offline_token,
    )
    return {"data": result.model_dump()}


@router.get("/me/api-keys", response_model=dict)
def list_api_keys(
    caller=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == caller.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {"data": [ApiKeyMetadata.model_validate(k).model_dump() for k in keys]}


@router.post("/me/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT)
def logout_everywhere(
    caller=Depends(get_current_user),
    db: Session = Depends(get_db),
    kc: KeycloakClient = Depends(get_keycloak_client),
):
    failures: list[str] = []

    # 1. Invalidate all interactive Keycloak sessions for this user.
    try:
        kc.logout_all_sessions(caller.external_id)
    except KeycloakError as exc:
        _log.error("logout-everywhere: sessions call failed user=%s err=%s", caller.id, exc)
        failures.append(f"session logout: {exc}")

    # 2. Revoke all active API keys via Keycloak and mark them revoked in DB.
    active_keys = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == caller.id, ApiKey.revoked_at.is_(None))
        .all()
    )
    now = datetime.now(timezone.utc)
    for key in active_keys:
        try:
            kc.revoke_session(key.keycloak_session_id)
        except KeycloakError as exc:
            _log.error(
                "logout-everywhere: key revocation failed key_id=%s err=%s", key.id, exc
            )
            failures.append(f"api_key {key.id}: {exc}")
            continue
        key.revoked_at = now

    if active_keys:
        db.commit()

    if failures:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "code": "KEYCLOAK_ERROR",
                    "message": "logout-everywhere partially failed",
                    "failures": failures,
                }
            },
        )

    write_event(
        db,
        entity_type="user",
        entity_id=str(caller.id),
        action="logout_everywhere",
        caller=caller,
    )


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    caller=Depends(get_current_user),
    db: Session = Depends(get_db),
    kc: KeycloakClient = Depends(get_keycloak_client),
):
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == caller.id).first()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "API key not found"}},
        )
    if key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "CONFLICT", "message": "API key already revoked"}},
        )

    try:
        kc.revoke_session(key.keycloak_session_id)
    except KeycloakError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": {"code": "KEYCLOAK_ERROR", "message": str(exc)}},
        )

    key.revoked_at = datetime.now(timezone.utc)
    db.commit()

    write_event(
        db,
        entity_type="apikey",
        entity_id=str(key_id),
        action="revoked",
        caller=caller,
        details={"label": key.label},
    )
