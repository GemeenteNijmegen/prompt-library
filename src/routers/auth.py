import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from pydantic import BaseModel

from src.config import settings
from src.dependencies import get_current_user
from src.schemas.user import UserProfile

router = APIRouter(tags=["auth"])


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


class GenerateKeyRequest(BaseModel):
    scope: list[str]
    expires_in_days: int = 365


@router.post("/auth/generate-key", response_model=dict, status_code=201)
def generate_key(
    body: GenerateKeyRequest,
    caller=Depends(get_current_user),
):
    if not caller.has_scope("admin:manage_keys"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Requires admin:manage_keys"}},
        )

    if not settings.JWT_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "CONFIG_ERROR", "message": "JWT_SECRET_KEY not configured"}},
        )

    now = int(time.time())
    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
    payload = {
        "sub": f"machine:{caller.external_id}",
        "scope": body.scope,
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

    return {
        "data": {
            "token": token,
            "expires_at": expires_at.isoformat(),
            "scope": body.scope,
        }
    }
