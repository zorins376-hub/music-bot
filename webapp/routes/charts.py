"""
Charts — chart listing and fetching endpoints.
Extracted from webapp/api.py for modularity.
"""
import json
import logging

from fastapi import APIRouter, Depends, Query

from webapp.deps import get_current_user
from webapp.schemas import SearchResult, TrackSchema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["charts"])


@router.post("/api/charts/refresh")
async def refresh_charts(user: dict = Depends(get_current_user)):
    """Force refresh all chart caches."""
    from bot.handlers.charts import _CHART_FETCHERS, _CHART_TTL
    from bot.services.cache import cache
    refreshed = {}
    for src, fetcher in _CHART_FETCHERS.items():
        await cache.redis.delete(f"chart:{src}")
        try:
            tracks = await fetcher()
            if tracks:
                await cache.redis.setex(
                    f"chart:{src}",
                    _CHART_TTL,
                    json.dumps(tracks, ensure_ascii=False),
                )
            refreshed[src] = len(tracks) if tracks else 0
        except Exception as e:
            refreshed[src] = f"error: {e}"
    return refreshed


@router.post("/api/indexer/run")
async def run_indexer_now(user: dict = Depends(get_current_user)):
    """Trigger a manual track indexing run (harvests metadata from all sources)."""
    from bot.services.track_indexer import run_indexer
    results = await run_indexer()
    return {"status": "ok", "indexed": results}


@router.get("/api/crawler/stats")
async def crawler_stats(user: dict = Depends(get_current_user)):
    """Get deep crawler progress stats."""
    from bot.services.deep_crawler import get_crawler_stats
    return await get_crawler_stats()


@router.post("/api/crawler/run")
async def run_crawler_now(user: dict = Depends(get_current_user)):
    """Trigger a manual deep crawl cycle."""
    from bot.services.deep_crawler import run_deep_crawl
    results = await run_deep_crawl()
    return {"status": "ok", "crawled": results}


@router.get("/api/charts")
async def list_charts(user: dict = Depends(get_current_user)):
    """List available chart sources."""
    from bot.handlers.charts import _CHART_LABELS
    return [{"id": k, "label": v} for k, v in _CHART_LABELS.items()]


@router.get("/api/charts/{source}", response_model=SearchResult)
async def get_chart(
    source: str,
    limit: int = Query(default=100, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get chart tracks by source."""
    from bot.handlers.charts import _get_chart
    from bot.utils import fmt_duration as _fmt_dur
    tracks_raw = await _get_chart(source)
    if not tracks_raw:
        return SearchResult(tracks=[], total=0)
    tracks = [
        TrackSchema(
            video_id=r.get("video_id", ""),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", "Unknown"),
            duration=r.get("duration", 0),
            duration_fmt=_fmt_dur(r.get("duration", 0)),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or (
                f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg"
                if r.get("video_id") and not r.get("video_id", "").startswith(("ym_", "sp_", "vk_"))
                else None
            ),
        )
        for r in tracks_raw[:limit]
        if r.get("title")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))
