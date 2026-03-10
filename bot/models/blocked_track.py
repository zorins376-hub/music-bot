from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class BlockedTrack(Base):
    """Заблокированные треки (DMCA / правообладатель)."""
    __tablename__ = "blocked_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    reason: Mapped[str] = mapped_column(String(255), default="DMCA")
    blocked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alternative_source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
