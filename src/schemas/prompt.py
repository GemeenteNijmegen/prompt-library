from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class PromptCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1)
    prompt_text: str = Field(..., min_length=1)
    example_output: str | None = None
    image_url: str | None = None
    status: Literal["draft", "published_org", "published_public", "archived"] = "draft"
    visibility: Literal["public", "internal", "restricted"] = "public"
    featured: bool = False
    category_ids: list[int] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    prompt_text: str | None = None
    example_output: str | None = None
    image_url: str | None = None
    status: Literal["draft", "published_org", "published_public", "archived"] | None = None
    visibility: Literal["public", "internal", "restricted"] | None = None
    featured: bool | None = None
    category_ids: list[int] | None = None
    tag_names: list[str] | None = None


class TagSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class PromptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: str
    visibility: str
    featured: bool
    view_count: int
    use_count: int
    created_at: datetime
    published_at: datetime | None
    categories: list[CategorySummary]
    tags: list[TagSummary]


class PromptDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    prompt_text: str
    example_output: str | None
    image_url: str | None
    status: str
    visibility: str
    featured: bool
    creator_id: int
    view_count: int
    use_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    categories: list[CategorySummary]
    tags: list[TagSummary]
