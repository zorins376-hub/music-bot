from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # track|mix|playlist
    entity_id: Mapped[int] = mapped_column(Integer, default=0)
    short_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
