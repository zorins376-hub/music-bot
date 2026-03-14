"""Apple Music provider — search via iTunes Search API (public, no auth).

NOTE: Apple Music does NOT allow direct audio downloads.
Tracks found here are downloaded through Yandex Music or YouTube (fallback).
"""
import logging
from typing import Optional

import aiohttp

from bot.config import settings
from bot.services.http_session import get_session
from bot.utils import fmt_duration as _fmt_dur

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"


def _track_to_dict(tr: dict) -> Optional[dict]:
    """Convert iTunes API result to internal dict."""
    try:
        title = (tr.get("trackName") or "").strip()
        artist = (tr.get("artistName") or "").strip()
        if not title or not artist:
            return None
        dur_ms = int(tr.get("trackTimeMillis") or 0)
        dur_s = dur_ms // 1000
        if dur_s <= 0 or dur_s > settings.MAX_DURATION:
            return None
        track_id = tr.get("trackId")
        if not track_id:
            return None
        cover = (tr.get("artworkUrl100") or "").replace("100x100", "600x600")
        return {
            "video_id": f"am_{track_id}",
            "apple_track_id": int(track_id),
            "title": title,
            "uploader": artist,
            "duration": dur_s,
            "duration_fmt": _fmt_dur(dur_s),
            "source": "apple",
            "cover_url": cover,
            "yt_query": f"{artist} - {title}",
        }
    except Exception:
        return None


async def search_apple(query: str, limit: int = 5) -> list[dict]:
    """Search Apple Music / iTunes catalog (public API, no auth)."""
    try:
        session = get_session()
        async with session.get(
            _SEARCH_URL,
            params={
                "term": query,
                "media": "music",
                "entity": "song",
                "limit": min(limit + 5, 50),
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)
            results: list[dict] = []
            for item in data.get("results", []):
                d = _track_to_dict(item)
                if d:
                    results.append(d)
                if len(results) >= limit:
                    break
            return results
    except Exception as e:
        logger.error("Apple Music search error: %s", e)
        return []
