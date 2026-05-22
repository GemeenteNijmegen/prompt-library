from datetime import datetime

from sqlalchemy import Integer, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base


class PromptRating(Base):
    __tablename__ = "prompt_ratings"
    __table_args__ = (
        UniqueConstraint("prompt_id", "user_id", name="uq_prompt_user_rating"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    prompt: Mapped["Prompt"] = relationship("Prompt", back_populates="ratings")
    user: Mapped["User"] = relationship("User", back_populates="ratings")
