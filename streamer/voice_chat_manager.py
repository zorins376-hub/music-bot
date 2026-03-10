"""
voice_chat_manager.py — Multi-group voice chat session manager.

Tracks active sessions per group via Redis, handles play/skip/queue
operations across multiple group chats simultaneously.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "vc:session:"
_QUEUE_PREFIX = "vc:queue:"
_SESSION_TTL = 6 * 3600  # 6 hours


async def get_session(group_id: int) -> Optional[dict]:
    """Get current voice chat session for a group."""
    from bot.services.cache import cache
    try:
        data = await cache.redis.get(f"{_SESSION_PREFIX}{group_id}")
        return json.loads(data) if data else None
    except Exception:
        return None


async def create_session(group_id: int, started_by: int) -> dict:
    """Create a new voice chat session for a group."""
    from bot.services.cache import cache
    session = {
        "group_id": group_id,
        "started_by": started_by,
        "current_track": None,
        "is_playing": False,
    }
    await cache.redis.setex(
        f"{_SESSION_PREFIX}{group_id}",
        _SESSION_TTL,
        json.dumps(session, ensure_ascii=False),
    )
    return session


async def update_session(group_id: int, **kwargs) -> None:
    """Update session fields."""
    session = await get_session(group_id)
    if not session:
        return
    session.update(kwargs)
    from bot.services.cache import cache
    await cache.redis.setex(
        f"{_SESSION_PREFIX}{group_id}",
        _SESSION_TTL,
        json.dumps(session, ensure_ascii=False),
    )


async def delete_session(group_id: int) -> None:
    """Delete a voice chat session."""
    from bot.services.cache import cache
    await cache.redis.delete(f"{_SESSION_PREFIX}{group_id}")
    await cache.redis.delete(f"{_QUEUE_PREFIX}{group_id}")


async def add_to_queue(group_id: int, track: dict) -> int:
    """Add a track to the group's voice chat queue. Returns queue length."""
    from bot.services.cache import cache
    await cache.redis.rpush(
        f"{_QUEUE_PREFIX}{group_id}",
        json.dumps(track, ensure_ascii=False),
    )
    await cache.redis.expire(f"{_QUEUE_PREFIX}{group_id}", _SESSION_TTL)
    length = await cache.redis.llen(f"{_QUEUE_PREFIX}{group_id}")
    return length


async def get_queue(group_id: int) -> list[dict]:
    """Get all tracks in the group's queue."""
    from bot.services.cache import cache
    items = await cache.redis.lrange(f"{_QUEUE_PREFIX}{group_id}", 0, -1)
    result = []
    for raw in items:
        try:
            result.append(json.loads(raw))
        except Exception:
            continue
    return result


async def pop_next(group_id: int) -> Optional[dict]:
    """Pop the next track from the queue."""
    from bot.services.cache import cache
    data = await cache.redis.lpop(f"{_QUEUE_PREFIX}{group_id}")
    if data:
        return json.loads(data)
    return None


async def get_now_playing(group_id: int) -> Optional[dict]:
    """Get the currently playing track for a group."""
    session = await get_session(group_id)
    if session:
        return session.get("current_track")
    return None
