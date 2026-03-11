from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class Track(Base):
    """Единая таблица треков — полная метадата как у Spotify / Яндекс Музыка."""
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    source: Mapped[str] = mapped_column(String(20), default="youtube")  # youtube/yandex/spotify/channel
    channel: Mapped[str | None] = mapped_column(String(50))  # tequila/fullmoon/external
    title: Mapped[str | None] = mapped_column(String(500))
    artist: Mapped[str | None] = mapped_column(String(255))
    album: Mapped[str | None] = mapped_column(String(500))
    genre: Mapped[str | None] = mapped_column(String(100))
    release_year: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(255))
    isrc: Mapped[str | None] = mapped_column(String(20))
    explicit: Mapped[bool | None] = mapped_column(Boolean)
    popularity: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(10))
    bpm: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)
    file_id: Mapped[str | None] = mapped_column(String(255))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_tracks_downloads", "downloads"),
        Index("ix_tracks_genre", "genre"),
        Index("ix_tracks_release_year", "release_year"),
        Index("ix_tracks_artist", "artist"),
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

    __table_args__ = (
        Index("ix_lh_user_action_created", "user_id", "action", created_at.desc()),
    )


class Payment(Base):
    """Запись об оплате Premium через Telegram Stars."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(Integer)  # Stars amount
    currency: Mapped[str] = mapped_column(String(10), default="XTR")
    payload: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
