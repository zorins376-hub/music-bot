from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class PartySession(Base):
    """Совместная вечеринка — общий плейлист для группового чата."""
    __tablename__ = "party_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(100), default="Party 🎉")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PartyTrack(Base):
    """Трек в очереди Party-сессии."""
    __tablename__ = "party_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    artist: Mapped[str] = mapped_column(String(255), default="Unknown")
    duration: Mapped[int] = mapped_column(Integer, default=0)
    duration_fmt: Mapped[str] = mapped_column(String(10), default="0:00")
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="youtube")
    added_by: Mapped[int] = mapped_column(BigInteger)
    added_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    skip_votes: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_party_tracks_party_pos", "party_id", "position"),
    )
