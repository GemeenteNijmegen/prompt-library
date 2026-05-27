from fastapi import APIRouter, Depends

from src.dependencies import get_current_user
from src.schemas.user import UserProfile

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
