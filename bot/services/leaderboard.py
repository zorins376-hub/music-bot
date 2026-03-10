"""
leaderboard.py — XP leaderboard using Redis sorted sets.

Weekly and all-time leaderboards stored in Redis.
"""
import logging
from datetime import datetime, timezone

from bot.services.cache import cache

logger = logging.getLogger(__name__)

_WEEKLY_KEY_FMT = "lb:weekly:{year}:{week}"
_ALLTIME_KEY = "lb:alltime"

# XP rewards per action
XP_PLAY = 1
XP_LIKE = 2
XP_SHARE = 3
XP_PLAYLIST_CREATE = 5

# Levels: XP thresholds
_LEVELS = [
    (1, 0),
    (2, 20),
    (3, 50),
    (4, 100),
    (5, 200),
    (6, 400),
    (7, 700),
    (8, 1100),
    (9, 1600),
    (10, 2200),
    (11, 3000),
    (12, 4000),
    (13, 5500),
    (14, 7500),
    (15, 10000),
]


def calc_level(xp: int) -> int:
    """Calculate user level from XP."""
    level = 1
    for lvl, threshold in _LEVELS:
        if xp >= threshold:
            level = lvl
        else:
            break
    return level


def xp_for_next_level(xp: int) -> tuple[int, int]:
    """Return (current_level_threshold, next_level_threshold)."""
    current_level = calc_level(xp)
    current_threshold = 0
    next_threshold = _LEVELS[-1][1]
    for lvl, threshold in _LEVELS:
        if lvl == current_level:
            current_threshold = threshold
        if lvl == current_level + 1:
            next_threshold = threshold
            break
    return current_threshold, next_threshold


def _weekly_key() -> str:
    now = datetime.now(timezone.utc)
    return _WEEKLY_KEY_FMT.format(year=now.year, week=now.isocalendar()[1])


async def add_xp(user_id: int, amount: int) -> None:
    """Add XP to user's leaderboard score."""
    try:
        await cache.redis.zincrby(_weekly_key(), amount, str(user_id))
        await cache.redis.zincrby(_ALLTIME_KEY, amount, str(user_id))
    except Exception as e:
        logger.debug("leaderboard add_xp failed: %s", e)


async def get_leaderboard(period: str = "weekly", limit: int = 50) -> list[tuple[int, float]]:
    """Get top users. Returns [(user_id, score), ...]."""
    try:
        key = _weekly_key() if period == "weekly" else _ALLTIME_KEY
        results = await cache.redis.zrevrange(key, 0, limit - 1, withscores=True)
        return [(int(uid), score) for uid, score in results]
    except Exception as e:
        logger.debug("leaderboard get failed: %s", e)
        return []


async def get_user_rank(user_id: int, period: str = "weekly") -> int | None:
    """Get user's rank (1-based). Returns None if not ranked."""
    try:
        key = _weekly_key() if period == "weekly" else _ALLTIME_KEY
        rank = await cache.redis.zrevrank(key, str(user_id))
        return rank + 1 if rank is not None else None
    except Exception:
        return None
