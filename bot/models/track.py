from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class Track(Base):
    """Единая таблица треков: из каналов + YouTube + SoundCloud."""
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    source: Mapped[str] = mapped_column(String(20), default="youtube")  # youtube/soundcloud/channel
    channel: Mapped[str | None] = mapped_column(String(50))  # tequila/fullmoon/external
    title: Mapped[str | None] = mapped_column(String(500))
    artist: Mapped[str | None] = mapped_column(String(255))
    genre: Mapped[str | None] = mapped_column(String(50))
    bpm: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)
    file_id: Mapped[str | None] = mapped_column(String(255))
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ListeningHistory(Base):
    """История прослушивания — основа для AI DJ рекомендаций."""
    __tablename__ = "listening_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    track_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tracks.id"), nullable=True)
    query: Mapped[str | None] = mapped_column(String(500))
    # action: play / skip / like / dislike
    action: Mapped[str] = mapped_column(String(20), default="play")
    listen_duration: Mapped[int | None] = mapped_column(Integer)
    # source: search / radio / automix / recommend
    source: Mapped[str | None] = mapped_column(String(20), default="search")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
