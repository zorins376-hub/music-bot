from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class ArtistWatchlist(Base):
    __tablename__ = "artist_watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_artist_watchlist_user_artist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    artist_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(20), default="auto")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
