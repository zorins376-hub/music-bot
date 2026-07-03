"""Disk tier of the search-result cache.

Redis (RAM, 1 GB, volatile-lru) is the hot tier; this table is the durable cold
tier. Every final ranked result set is written here as well, so entries evicted
from RAM by the LRU size cap (or lost to a Redis restart) are transparently
re-read from disk and re-warmed into RAM — search history is never lost.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class SearchCache(Base):
    __tablename__ = "search_cache"

    norm_query: Mapped[str] = mapped_column(String(300), primary_key=True)
    results_json: Mapped[str] = mapped_column(Text, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
