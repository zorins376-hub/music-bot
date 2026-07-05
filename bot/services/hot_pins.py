"""
hot_pins.py — Dynamic, Redis-backed curated pins (add/remove with NO deploy).

A "hot pin" maps a normalized query to a ready-to-play track dict. It is checked
at Tier-0 in search.py right after the static curated pins, so it answers
instantly and outranks the result cache. Two writers:

  1. Admins — ``/admin pin <query> => <artist - title>``  (source="manual")
  2. Auto-promoter — a learned "🔁 Не тот трек?" correction confirmed enough
     times is promoted here automatically (source="auto").

Unlike search_memory (per-query learning gated by a confirmation threshold), a
hot pin is an explicit, immediately-authoritative override — listable and
removable by admins. Writing one busts any stale result cache for that query so
it takes effect at once (no waiting for RCACHE_TTL).

Storage: one Redis hash ``hotpins`` mapping ``field = normalized query`` ->
JSON ``{track, q, added_by, source, ts, hits}``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

_HKEY = "hotpins"
_TRACK_FIELDS = (
    "video_id", "source", "title", "uploader",
    "duration", "duration_fmt", "file_id", "ym_track_id",
)
# Learned corrections with at least this many confirmations get auto-promoted.
# Higher than search_memory's auto-pick threshold (3) so a promoted pin is
# well-established before it becomes a listable, near-permanent override.
_PROMOTE_MIN_COUNT = 5
_PROMOTER_INTERVAL = 1800  # 30 min


def _slim(track: dict) -> dict:
    return {k: track.get(k) for k in _TRACK_FIELDS if track.get(k) is not None}


def _key(query: str) -> str | None:
    """Canonical hash field for a query (same normalization as curated pins)."""
    try:
        from bot.services.search_curated import _normalize_query_key
        n = _normalize_query_key(query or "")
    except Exception:
        from bot.services.search_engine import normalize_query
        n = normalize_query(query or "")
    return n if n and len(n) >= 2 else None


def _variants(query: str) -> list[str]:
    """Lookup keys for a query — mirrors curated pin variant matching."""
    try:
        from bot.services.search_curated import _query_norm_variants
        return [v for v in _query_norm_variants(query) if v]
    except Exception:
        k = _key(query)
        return [k] if k else []


async def set_hot_pin(query: str, track: dict, *, added_by: int = 0, source: str = "manual") -> bool:
    """Pin `track` as the instant answer for `query`. Busts stale cache. Returns ok."""
    key = _key(query)
    if not key or not track or not track.get("video_id"):
        return False
    from bot.services.cache import cache
    payload = {
        "track": _slim(track),
        "q": key,
        "added_by": int(added_by or 0),
        "source": source,
        "ts": int(time.time()),
        "hits": 0,
    }
    try:
        await cache.redis.hset(_HKEY, key, json.dumps(payload, ensure_ascii=False))
        await cache.bust_result_cache(key)  # a stale wrong cache must not shadow the pin
        logger.info(
            "hot_pins: set %r -> %s (%s) by=%s src=%s",
            key, track.get("title"), track.get("video_id"), added_by, source,
        )
        return True
    except Exception:
        logger.debug("hot_pins set failed", exc_info=True)
        return False


async def get_hot_pin(query: str) -> dict | None:
    """Return the pinned track dict for `query`, or None. Bumps a hit counter."""
    from bot.services.cache import cache
    for v in _variants(query):
        try:
            raw = await cache.redis.hget(_HKEY, v)
        except Exception:
            raw = None
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        track = payload.get("track")
        if track and track.get("video_id"):
            try:  # best-effort hit counter
                payload["hits"] = int(payload.get("hits", 0)) + 1
                await cache.redis.hset(_HKEY, v, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass
            return dict(track)
    return None


async def remove_hot_pin(query: str) -> bool:
    key = _key(query)
    if not key:
        return False
    from bot.services.cache import cache
    try:
        removed = await cache.redis.hdel(_HKEY, key)
        await cache.bust_result_cache(key)
        return bool(removed)
    except Exception:
        logger.debug("hot_pins remove failed", exc_info=True)
        return False


async def list_hot_pins() -> list[dict]:
    from bot.services.cache import cache
    try:
        raw = await cache.redis.hgetall(_HKEY)
    except Exception:
        return []
    out: list[dict] = []
    for field, val in (raw or {}).items():
        try:
            payload = json.loads(val)
            q = field.decode() if isinstance(field, (bytes, bytearray)) else field
            payload.setdefault("q", q)
            out.append(payload)
        except Exception:
            continue
    out.sort(key=lambda p: p.get("ts", 0), reverse=True)
    return out


async def promote_learned_pins(scan_limit: int = 2000) -> dict:
    """Promote well-confirmed learned corrections (search_memory) into hot pins."""
    from bot.services.cache import cache
    promoted = 0
    seen = 0
    try:
        cursor = 0
        while True:
            cursor, keys = await cache.redis.scan(cursor, match="search:learn:*", count=200)
            for lkey in keys or []:
                seen += 1
                try:
                    raw = await cache.redis.get(lkey)
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    if int(payload.get("count", 0)) < _PROMOTE_MIN_COUNT:
                        continue
                    q = payload.get("q")
                    track = payload.get("track")
                    if not q or not track or not track.get("video_id"):
                        continue
                    if await cache.redis.hexists(_HKEY, q):
                        continue  # already pinned
                    if await set_hot_pin(q, track, added_by=0, source="auto"):
                        promoted += 1
                except Exception:
                    continue
            if cursor == 0 or seen >= scan_limit:
                break
    except Exception:
        logger.debug("promote_learned_pins failed", exc_info=True)
    if promoted:
        logger.info("hot_pins: auto-promoted %d learned correction(s)", promoted)
    return {"promoted": promoted, "scanned": seen}


async def _promoter_loop(interval_sec: int = _PROMOTER_INTERVAL) -> None:
    await asyncio.sleep(120)  # let startup settle first
    while True:
        try:
            await promote_learned_pins()
        except Exception:
            logger.debug("hot_pins promoter loop error", exc_info=True)
        await asyncio.sleep(interval_sec)


async def start_hot_pins_promoter() -> None:
    asyncio.create_task(_promoter_loop())
    logger.info(
        "hot_pins: auto-promoter started (every %ds, min_count=%d)",
        _PROMOTER_INTERVAL, _PROMOTE_MIN_COUNT,
    )
