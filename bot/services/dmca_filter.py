"""
dmca_filter.py — DMCA / blocked track filter.

Admin can block tracks by source_id. Blocked tracks are filtered from
search results before display.
"""
import logging

from sqlalchemy import delete, select

from bot.models.base import async_session
from bot.models.blocked_track import BlockedTrack

logger = logging.getLogger(__name__)

# In-memory cache for fast filtering (refreshed periodically)
_blocked_ids: set[str] = set()
_loaded = False


async def load_blocked_ids() -> None:
    """Load blocked source IDs into memory cache."""
    global _blocked_ids, _loaded
    try:
        async with async_session() as session:
            result = await session.execute(select(BlockedTrack.source_id))
            _blocked_ids = {row[0] for row in result.fetchall()}
            _loaded = True
            logger.info("DMCA filter: loaded %d blocked IDs", len(_blocked_ids))
    except Exception as e:
        logger.warning("Failed to load blocked IDs: %s", e)


def is_blocked(source_id: str) -> bool:
    """Check if a track is blocked (fast in-memory check)."""
    return source_id in _blocked_ids


def filter_blocked(tracks: list[dict]) -> list[dict]:
    """Remove blocked tracks from search results."""
    if not _blocked_ids:
        return tracks
    return [t for t in tracks if t.get("video_id", "") not in _blocked_ids]


async def block_track(source_id: str, reason: str = "DMCA", blocked_by: str | None = None) -> bool:
    """Block a track by source_id. Returns True if newly blocked."""
    try:
        async with async_session() as session:
            existing = await session.execute(
                select(BlockedTrack).where(BlockedTrack.source_id == source_id)
            )
            if existing.scalar_one_or_none():
                return False
            session.add(BlockedTrack(
                source_id=source_id, reason=reason, blocked_by=blocked_by
            ))
            await session.commit()
        _blocked_ids.add(source_id)
        return True
    except Exception as e:
        logger.error("block_track failed: %s", e)
        return False


async def unblock_track(source_id: str) -> bool:
    """Unblock a track by source_id."""
    try:
        async with async_session() as session:
            result = await session.execute(
                delete(BlockedTrack).where(BlockedTrack.source_id == source_id)
            )
            await session.commit()
            if result.rowcount > 0:
                _blocked_ids.discard(source_id)
                return True
            return False
    except Exception as e:
        logger.error("unblock_track failed: %s", e)
        return False
