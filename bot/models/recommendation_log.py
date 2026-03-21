"""RecommendationLog model for A/B testing and CTR tracking."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class RecommendationLog(Base):
    """Log of recommendations shown to users for A/B testing.
    
    Each record represents one track shown in a recommendation list.
    Used to compute CTR (click-through rate) by algo type.
    """
    __tablename__ = "recommendation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"))
    algo: Mapped[str] = mapped_column(String(20))  # "ml" | "sql" | "popular"
    position: Mapped[int] = mapped_column(Integer)  # position in list (0-indexed)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clicked: Mapped[bool] = mapped_column(Boolean, default=False)  # updated on click
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_reclog_user_created", "user_id", "created_at"),
        Index("ix_reclog_algo_created", "algo", "created_at"),
    )
