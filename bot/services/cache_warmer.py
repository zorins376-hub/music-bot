"""Proactive search-cache warmer.

Slowly pre-resolves queries into the two-tier result cache (Redis RAM +
Postgres disk) so users hit instant Tier-0 answers instead of waiting for the
live engine. Candidate sources, in priority order:

1. Real user queries from the search:audit history (what people actually type);
2. "Artist Title" of popular tracks in our own DB (what they will likely type).

Safety properties:
- GENTLE: a small batch every few minutes (default 6 per 180s) — invisible to
  Yandex, never competes with organic user searches for provider quota.
- CORRECT-ONLY: a result set is cached only when it passes the same
  direct-hit confidence gate the live ranker uses; ambiguous/lyric-like
  queries are left to the full engine so quality is never reduced.
- IDEMPOTENT: processed queries are remembered in a Redis set (warm:done), so
  each candidate is attempted once; the rcache/disk tier then serves repeats.
"""
from __future__ import annotations

import asyncio
import logging
import time

from bot.config import settings

logger = logging.getLogger(__name__)

_WARM_INTERVAL = 180          # seconds between batches
_WARM_BATCH = 6               # queries resolved per batch
_WARM_START_DELAY = 120       # let the bot settle after startup
_DONE_SET = "warm:done"       # Redis set of already-processed norm queries
_AUDIT_SCAN = 3000            # how many recent audit entries to scan
_DB_SCAN = 3000               # how many popular tracks to scan

_task: asyncio.Task | None = None


async def _candidates() -> list[str]:
    """Ordered candidate queries: real user history first, then popular tracks."""
    import json as _json

    from bot.services.cache import cache

    out: list[str] = []
    seen: set[str] = set()

    # 1) Real user queries from the audit log (newest first)
    try:
        raw = await cache.redis.lrange("search:audit", 0, _AUDIT_SCAN - 1)
        for line in raw or []:
            try:
                entry = _json.loads(line)
            except Exception:
                continue
            if entry.get("t") != "search":
                continue
            q = (entry.get("pq") or entry.get("q") or "").strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
    except Exception:
        logger.debug("warmer: audit scan failed", exc_info=True)

    # 2) Popular tracks from our own DB -> "Artist Title"
    try:
        from sqlalchemy import select
        from bot.models.base import async_session
        from bot.models.track import Track

        async with async_session() as session:
            rows = await session.execute(
                select(Track.artist, Track.title)
                .where(Track.artist.isnot(None), Track.title.isnot(None))
                .where(Track.downloads > 0)
                .order_by(Track.downloads.desc())
                .limit(_DB_SCAN)
            )
            for artist, title in rows:
                q = f"{artist} {title}".strip()
                if len(q) > 4 and q.lower() not in seen:
                    seen.add(q.lower())
                    out.append(q)
    except Exception:
        logger.debug("warmer: db scan failed", exc_info=True)

    return out


async def _resolve_and_cache(query: str) -> bool:
    """Resolve one query through the slim pipeline; cache only confident results."""
    from bot.db import search_local_tracks
    from bot.services.cache import cache
    from bot.services.search_curated import (
        inject_curated_track,
        is_junk_search_query,
    )
    from bot.services.search_engine import (
        deduplicate_results,
        detect_script,
        is_lyric_like_query,
        normalize_query,
        parse_query,
    )
    from bot.services.yandex_provider import search_yandex

    if is_junk_search_query(query):
        return False
    parsed = parse_query(query)
    pq = parsed.get("clean") or parsed.get("original") or query
    # Lyric-like queries need the full engine (Genius/LRCLib) — never warm blind.
    if is_lyric_like_query(pq, parsed):
        return False
    norm_q = normalize_query(pq)
    if not norm_q:
        return False

    # Already cached (RAM or disk)? Nothing to do.
    if await cache.get_result_cache(norm_q):
        return False

    local_tracks = await search_local_tracks(pq, limit=5)
    local_results = []
    for tr in (local_tracks or []):
        local_results.append({
            "video_id": tr.source_id, "title": tr.title or "Unknown",
            "uploader": tr.artist or "Unknown", "duration": tr.duration or 0,
            "source": tr.source or "channel",
            "_downloads": tr.downloads or 0,
        })
    try:
        ya = await asyncio.wait_for(search_yandex(pq, limit=5), timeout=8)
    except Exception:
        ya = []

    all_results = local_results + list(ya or [])
    all_results = inject_curated_track(all_results, pq)
    if not all_results:
        return False
    results = deduplicate_results(
        all_results, lang_hint=detect_script(pq), query=pq
    )[:5]
    if not results:
        return False

    # Confidence gate: cache only when a top result covers ~the whole query —
    # the same signal the live ranker trusts. Ambiguous answers must keep going
    # through the full engine, or we'd serve "ready but wrong" values.
    from bot.handlers.search import _direct_hit_present
    if not (results[0].get("_curated") or _direct_hit_present(results, pq)):
        return False

    slim = [{k: v for k, v in r.items() if k != "file_id"} for r in results]
    await cache.set_result_cache(norm_q, slim)
    return True


async def _warm_cycle() -> tuple[int, int]:
    """One batch: pick the first unprocessed candidates and resolve them."""
    from bot.services.cache import cache

    try:
        done = await cache.redis.smembers(_DONE_SET)
        done = set(done or [])
    except Exception:
        done = set()

    warmed = tried = 0
    for q in await _candidates():
        if tried >= _WARM_BATCH:
            break
        key = q.lower().strip()[:300]
        if key in done:
            continue
        tried += 1
        try:
            if await _resolve_and_cache(q):
                warmed += 1
        except Exception:
            logger.debug("warmer: resolve failed for %r", q[:60], exc_info=True)
        try:
            await cache.redis.sadd(_DONE_SET, key)
        except Exception:
            pass
        await asyncio.sleep(2)  # spread provider calls inside the batch
    return tried, warmed


async def _warm_loop() -> None:
    await asyncio.sleep(_WARM_START_DELAY)
    logger.info(
        "Cache warmer started (batch=%d every %ds)", _WARM_BATCH, _WARM_INTERVAL
    )
    while True:
        t0 = time.monotonic()
        try:
            tried, warmed = await _warm_cycle()
            if tried:
                logger.info(
                    "Cache warmer: tried=%d warmed=%d in %.1fs",
                    tried, warmed, time.monotonic() - t0,
                )
        except Exception:
            logger.debug("warmer cycle failed", exc_info=True)
        await asyncio.sleep(_WARM_INTERVAL)


async def start_cache_warmer() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_warm_loop())


async def stop_cache_warmer() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
