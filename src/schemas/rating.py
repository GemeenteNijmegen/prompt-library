from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class RatingSubmit(BaseModel):
    rating: int = Field(..., ge=0, le=5)


class RatingDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt_id: int
    user_id: int
    rating: int
    created_at: datetime
    updated_at: datetime


class RatingStats(BaseModel):
    average: float
    count: int
    distribution: dict[str, int]
