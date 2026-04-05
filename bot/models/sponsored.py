"""
sponsored.py — Sponsored campaigns and events for B2B artist promotion.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class SponsoredCampaign(Base):
    __tablename__ = "sponsored_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"))
    budget_stars: Mapped[int] = mapped_column(Integer, default=0)
    spent_stars: Mapped[int] = mapped_column(Integer, default=0)
    impressions_total: Mapped[int] = mapped_column(Integer, default=0)
    clicks_total: Mapped[int] = mapped_column(Integer, default=0)
    target_genres: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, paused, finished
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class SponsoredEvent(Base):
    __tablename__ = "sponsored_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("sponsored_campaigns.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(20))  # impression, click
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
