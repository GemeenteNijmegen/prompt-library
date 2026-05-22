from datetime import datetime

from sqlalchemy import Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base
from src.models.joins import prompts_categories


class PromptCategory(Base):
    __tablename__ = "prompt_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    prompts: Mapped[list["Prompt"]] = relationship(
        "Prompt", secondary=prompts_categories, back_populates="categories"
    )
