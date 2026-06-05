from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _split_scopes(v):
    if isinstance(v, str):
        return v.split()
    return v


class ApiKeyCreate(BaseModel):
    label: str


class ApiKeyMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None

    _split_scopes = field_validator("scopes", mode="before")(_split_scopes)


class ApiKeyCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    # The raw secret — returned exactly once at creation, never stored.
    token: str

    _split_scopes = field_validator("scopes", mode="before")(_split_scopes)
