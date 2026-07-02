"""
search_memory.py — Self-improving search: learn the correct track for a query.

When a user taps "🔁 Не тот трек?" and picks an alternative, that is a strong
human label: "for THIS query, the right answer is THIS track." We persist that
mapping in Redis and pin the learned track to the top on future searches of the
same (normalized) query.

Admins can also pin overrides manually via remember_correction(..., weight=...).
"""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

_KEY_PREFIX = "search:learn:"
_TTL_SECONDS = 90 * 24 * 3600  # 90 days
# Minimum confirmations before a learned mapping is trusted for auto-pick.
_MIN_CONFIRMATIONS = 3
# Fields we persist for a learned track (enough to play it later).
_TRACK_FIELDS = (
    "video_id", "source", "title", "uploader",
    "duration", "duration_fmt", "file_id", "ym_track_id",
)


def _norm_key(query: str) -> str | None:
    from bot.services.search_engine import normalize_query

    norm = normalize_query(query or "")
    if not norm or len(norm) < 2:
        return None
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:20]
    return f"{_KEY_PREFIX}{digest}"


def _slim_track(track: dict) -> dict:
    return {k: track.get(k) for k in _TRACK_FIELDS if track.get(k) is not None}


async def remember_correction(query: str, track: dict, *, weight: int = 1) -> None:
    """Record that `track` is the correct answer for `query`."""
    key = _norm_key(query)
    if not key or not track or not track.get("video_id"):
        return
    from bot.services.cache import cache
    from bot.services.search_engine import normalize_query

    try:
        prev_raw = await cache.redis.get(key)
        prev = json.loads(prev_raw) if prev_raw else {}
    except Exception:
        prev = {}

    new_vid = track.get("video_id")
    count = int(prev.get("count", 0))
    # Same track confirmed again → strengthen; different track → switch with reset.
    if prev.get("track", {}).get("video_id") == new_vid:
        count += weight
    else:
        count = weight

    payload = {
        "q": normalize_query(query),
        "track": _slim_track(track),
        "count": count,
    }
    try:
        await cache.redis.setex(key, _TTL_SECONDS, json.dumps(payload, ensure_ascii=False))
        logger.info(
            "search_memory: learned %r -> %s (%s) count=%d",
            payload["q"], track.get("title"), new_vid, count,
        )
    except Exception:
        logger.debug("search_memory remember failed", exc_info=True)


async def get_learned_track(query: str, *, min_confirmations: int = _MIN_CONFIRMATIONS) -> dict | None:
    """Return the learned track dict for this query, or None."""
    key = _norm_key(query)
    if not key:
        return None
    from bot.services.cache import cache

    try:
        raw = await cache.redis.get(key)
        if not raw:
            return None
        payload = json.loads(raw)
        if int(payload.get("count", 0)) < min_confirmations:
            return None
        track = payload.get("track")
        if track and track.get("video_id"):
            return track
    except Exception:
        logger.debug("search_memory get failed", exc_info=True)
    return None
