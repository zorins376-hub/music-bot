from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
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


class PartyMember(Base):
    """Участник Party-сессии с ролью и presence-статусом."""
    __tablename__ = "party_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="listener")
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("party_id", "user_id", name="uq_party_members_party_user"),
        Index("ix_party_members_party_online", "party_id", "is_online"),
    )


class PartyTrackVote(Base):
    """Уникальные голоса участников за skip/remove."""
    __tablename__ = "party_track_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_tracks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    vote_type: Mapped[str] = mapped_column(String(20), default="skip")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("track_id", "user_id", "vote_type", name="uq_party_track_votes_unique"),
        Index("ix_party_track_votes_party_type", "party_id", "vote_type"),
    )


class PartyEvent(Base):
    """Лента событий Party-сессии."""
    __tablename__ = "party_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), default="info")
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PartyPlaybackState(Base):
    """Состояние синхронизированного воспроизведения комнаты."""
    __tablename__ = "party_playback_states"

    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), primary_key=True)
    track_position: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[str] = mapped_column(String(20), default="idle")
    seek_position: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PartyReaction(Base):
    """Emoji reactions for party tracks."""
    __tablename__ = "party_reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_sessions.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("party_tracks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    emoji: Mapped[str] = mapped_column(String(16), default="🔥")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("track_id", "user_id", "emoji", name="uq_party_reactions_unique"),
        Index("ix_party_reactions_track_emoji", "track_id", "emoji"),
    )
