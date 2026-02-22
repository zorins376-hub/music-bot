from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(5), default="ru")
    quality: Mapped[str] = mapped_column(String(10), default="192")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    # AI DJ профиль (v1.2)
    fav_genres: Mapped[list | None] = mapped_column(JSON, nullable=True)
    avg_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
