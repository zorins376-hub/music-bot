"""Admin audit log model — TASK-015."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class AdminLog(Base):
    __tablename__ = "admin_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(50))  # broadcast, ban, unban, settings, premium
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
