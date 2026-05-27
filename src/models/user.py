from datetime import datetime

from sqlalchemy import Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    org_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    prompts: Mapped[list["Prompt"]] = relationship("Prompt", back_populates="creator")
    ratings: Mapped[list["PromptRating"]] = relationship("PromptRating", back_populates="user")
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user")
