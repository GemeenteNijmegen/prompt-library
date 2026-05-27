from fastapi import APIRouter, Depends

from src.dependencies import get_current_user
from src.schemas.user import UserProfile

# Audit hook point: POST /me/api-keys and DELETE /me/api-keys/{id} must call
# write_event(entity_type="apikey", action="issued"/"revoked") once #36 is merged.

router = APIRouter(tags=["me"])


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
