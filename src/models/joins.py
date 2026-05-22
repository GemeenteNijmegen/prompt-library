from sqlalchemy import Table, Column, Integer, ForeignKey

from src.models import Base

prompts_categories = Table(
    "prompts_categories",
    Base.metadata,
    Column("prompt_id", Integer, ForeignKey("prompts.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", Integer, ForeignKey("prompt_categories.id", ondelete="CASCADE"), primary_key=True),
)

prompts_tags = Table(
    "prompts_tags",
    Base.metadata,
    Column("prompt_id", Integer, ForeignKey("prompts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("prompt_tags.id", ondelete="CASCADE"), primary_key=True),
)
