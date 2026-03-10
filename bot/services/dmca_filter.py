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


async def find_alternative(artist: str, title: str) -> dict | None:
    """Find an alternative version of a blocked track (live/cover/remix).

    Returns a search_tracks-compatible dict or None.
    """
    from bot.services.downloader import search_tracks

    alt_queries = [
        f"{artist} {title} live",
        f"{artist} {title} cover",
        f"{artist} {title} remix",
    ]
    for q in alt_queries:
        try:
            results = await search_tracks(q, max_results=1, source="youtube")
            if results:
                vid = results[0].get("video_id", "")
                if vid and vid not in _blocked_ids:
                    return results[0]
        except Exception:
            continue
    return None


async def create_appeal(user_id: int, blocked_track_id: int, reason: str) -> int | None:
    """Create a DMCA unblock appeal. Returns appeal ID or None."""
    try:
        from bot.models.dmca_appeal import DmcaAppeal
        async with async_session() as session:
            appeal = DmcaAppeal(
                user_id=user_id,
                blocked_track_id=blocked_track_id,
                reason=reason,
            )
            session.add(appeal)
            await session.commit()
            return appeal.id
    except Exception as e:
        logger.error("create_appeal failed: %s", e)
        return None


async def review_appeal(appeal_id: int, approved: bool, admin_id: int) -> bool:
    """Approve or reject a DMCA appeal. If approved, unblocks the track."""
    try:
        from bot.models.dmca_appeal import DmcaAppeal
        async with async_session() as session:
            result = await session.execute(
                select(DmcaAppeal).where(DmcaAppeal.id == appeal_id)
            )
            appeal = result.scalar_one_or_none()
            if not appeal or appeal.status != "pending":
                return False

            appeal.status = "approved" if approved else "rejected"
            appeal.reviewed_by = admin_id
            await session.commit()

            if approved:
                # Unblock the track
                bt = await session.execute(
                    select(BlockedTrack).where(BlockedTrack.id == appeal.blocked_track_id)
                )
                blocked = bt.scalar_one_or_none()
                if blocked:
                    await unblock_track(blocked.source_id)

            return True
    except Exception as e:
        logger.error("review_appeal failed: %s", e)
        return False
