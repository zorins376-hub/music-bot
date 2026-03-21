from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class DailyMix(Base):
    __tablename__ = "daily_mixes"
    __table_args__ = (
        UniqueConstraint("user_id", "mix_date", name="uq_daily_mix_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mix_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(120), default="Daily Mix")
    source: Mapped[str] = mapped_column(String(20), default="daily_mix")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DailyMixTrack(Base):
    __tablename__ = "daily_mix_tracks"
    __table_args__ = (
        UniqueConstraint("mix_id", "track_id", name="uq_daily_mix_track"),
        Index("ix_daily_mix_tracks_mix_pos", "mix_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mix_id: Mapped[int] = mapped_column(Integer, ForeignKey("daily_mixes.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
