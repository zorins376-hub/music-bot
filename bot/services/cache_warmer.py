"""Proactive search-cache warmer.

Slowly pre-resolves queries into the two-tier result cache (Redis RAM +
Postgres disk) so users hit instant Tier-0 answers instead of waiting for the
live engine. Candidate sources, in priority order:

1. Real user queries — the Redis search:audit ring AND the full DB search
   history (every distinct query ever typed, most-frequent first);
2. Current top-chart tracks (5 sources, deep) + Last.fm global/Russia charts —
   fresh popular tracks users will likely type next;
3. "Artist Title" of popular tracks in our own DB.

All provider resolution goes through Yandex (never YouTube), so aggressive
warming never competes with users for the YouTube quota it gets rate-limited on.

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

_WARM_INTERVAL = 150          # seconds between batches
_WARM_BATCH = 10              # queries resolved per batch
_WARM_START_DELAY = 120       # let the bot settle after startup
_DONE_SET = "warm:done"       # Redis set of already-processed norm queries
_AUDIT_SCAN = 3000            # how many recent audit entries to scan
_DB_HISTORY_SCAN = 5000       # how many distinct DB search queries to scan
_DB_SCAN = 4000               # how many popular tracks to scan
_CHART_DEPTH = 150            # how deep into each chart to warm
_LASTFM_LIMIT = 200           # top tracks per Last.fm chart

_task: asyncio.Task | None = None


async def _lastfm_top_tracks() -> list[str]:
    """Parse Last.fm charts (global + Russia geo) into 'Artist Title' queries — a
    fresh popular-track source beyond our own charts/DB."""
    key = getattr(settings, "LASTFM_API_KEY", "") or ""
    if not key:
        return []
    import aiohttp

    out: list[str] = []
    endpoints = (
        f"http://ws.audioscrobbler.com/2.0/?method=chart.gettoptracks&limit={_LASTFM_LIMIT}&api_key={key}&format=json",
        f"http://ws.audioscrobbler.com/2.0/?method=geo.gettoptracks&country=Russia&limit={_LASTFM_LIMIT}&api_key={key}&format=json",
    )
    try:
        async with aiohttp.ClientSession() as sess:
            for url in endpoints:
                try:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                        data = await r.json()
                except Exception:
                    continue
                tracks = ((data or {}).get("tracks") or {}).get("track") or []
                for t in tracks:
                    name = (t.get("name") or "").strip()
                    artist = ((t.get("artist") or {}).get("name") or "").strip()
                    q = f"{artist} {name}".strip()
                    if len(q) > 4:
                        out.append(q)
    except Exception:
        logger.debug("warmer: lastfm fetch failed", exc_info=True)
    return out


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

    # 1b) EVERY distinct query users have ever typed (DB search history — broader
    # and more durable than the Redis audit ring), most-frequent first.
    try:
        from sqlalchemy import func as _func, select as _select
        from bot.models.base import async_session
        from bot.models.track import ListeningHistory

        async with async_session() as session:
            rows = await session.execute(
                _select(ListeningHistory.query)
                .where(
                    ListeningHistory.action == "search",
                    ListeningHistory.query.isnot(None),
                )
                .group_by(ListeningHistory.query)
                .order_by(_func.count().desc())
                .limit(_DB_HISTORY_SCAN)
            )
            for (q,) in rows:
                q = (q or "").strip()
                if len(q) > 4 and q.lower() not in seen:
                    seen.add(q.lower())
                    out.append(q)
    except Exception:
        logger.debug("warmer: db history scan failed", exc_info=True)

    # 2) Current TOP-CHART tracks -> "Artist Title": these are the queries users
    # are MOST likely to type next, so they belong in the fast-access cache
    # before they are ever searched. Charts refresh over time; new entries are
    # not in warm:done yet, so they are picked up automatically.
    try:
        from bot.handlers.charts import _CHART_FETCHERS, _get_chart
        for source in _CHART_FETCHERS:
            try:
                tracks = await _get_chart(source)
            except Exception:
                continue
            for tr in (tracks or [])[:_CHART_DEPTH]:
                artist = (tr.get("uploader") or tr.get("artist") or "").strip()
                title = (tr.get("title") or "").strip()
                q = f"{artist} {title}".strip()
                if len(q) > 4 and q.lower() not in seen:
                    seen.add(q.lower())
                    out.append(q)
    except Exception:
        logger.debug("warmer: chart scan failed", exc_info=True)

    # 2b) Last.fm charts (global + Russia geo) — a fresh external popular-track
    # source beyond our own charts, so the warm pool keeps growing.
    try:
        for q in await _lastfm_top_tracks():
            if len(q) > 4 and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
    except Exception:
        logger.debug("warmer: lastfm scan failed", exc_info=True)

    # 2c) CIS per-country Apple charts (RU/BY/KZ/AM/AZ/KG/MD/TJ/UZ/UA/GE top-100) —
    # locally-popular tracks for our audience.
    try:
        from bot.handlers.charts import cis_chart_tracks
        for tr in await cis_chart_tracks():
            artist = (tr.get("artist") or tr.get("uploader") or "").strip()
            title = (tr.get("title") or "").strip()
            q = f"{artist} {title}".strip()
            if len(q) > 4 and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
    except Exception:
        logger.debug("warmer: cis chart scan failed", exc_info=True)

    # 3) Popular tracks from our own DB -> "Artist Title"
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
