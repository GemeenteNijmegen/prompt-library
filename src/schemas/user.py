from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    name: str | None
    email: str | None
    avatar_url: str | None
    last_seen_at: datetime
