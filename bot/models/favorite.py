from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class FavoriteTrack(Base):
    __tablename__ = "favorite_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "track_id", name="uq_favorite_user_track"),
        Index("ix_favorites_user_created", "user_id", "created_at"),
    )
