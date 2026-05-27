from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base
from src.models.joins import prompts_categories, prompts_tags


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published_org', 'published_public', 'archived')",
            name="ck_prompts_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    example_output: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="public")
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # stored as JSON string; Alembic overrides to JSONB on PostgreSQL
    embedding_vector: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    creator: Mapped["User"] = relationship("User", back_populates="prompts")
    categories: Mapped[list["PromptCategory"]] = relationship(
        "PromptCategory", secondary=prompts_categories, back_populates="prompts"
    )
    tags: Mapped[list["PromptTag"]] = relationship(
        "PromptTag", secondary=prompts_tags, back_populates="prompts"
    )
    ratings: Mapped[list["PromptRating"]] = relationship("PromptRating", back_populates="prompt", cascade="all, delete-orphan")
