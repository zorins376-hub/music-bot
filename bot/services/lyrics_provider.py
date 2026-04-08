"""
lyrics_provider.py — Fetch song lyrics via Genius API.

- Searches Genius for artist + title
- Returns first 10 lines + Genius URL (copyright compliance)
- Caches in Redis with TTL 7 days
"""
import json
import logging
import re
import time

import aiohttp

from bot.config import settings
from bot.services.http_session import get_session

logger = logging.getLogger(__name__)

_GENIUS_SEARCH_URL = "https://api.genius.com/search"
_GENIUS_PUBLIC_MULTI_URL = "https://genius.com/api/search/multi"
_LYRICS_CACHE_TTL = 7 * 24 * 3600  # 7 days
_GENIUS_RETRY_AFTER = 15 * 60
_genius_disabled_until = 0.0


def _genius_session() -> aiohttp.ClientSession:
    """Return an aiohttp session for Genius requests (proxy-aware)."""
    proxy = (settings.GENIUS_PROXY_URL or "").strip()
    if proxy:
        conn = aiohttp.TCPConnector()
        return aiohttp.ClientSession(connector=conn)
    return get_session()


def _genius_proxy() -> str | None:
    proxy = (settings.GENIUS_PROXY_URL or "").strip()
    return proxy or None


async def get_lyrics(artist: str, title: str) -> dict | None:
    """
    Return {'lines': list[str], 'url': str, 'full_title': str} or None.
    'lines' contains only the first 10 lines of lyrics.
    """
    from bot.services.cache import cache

    cache_key = f"lyrics:{artist.lower().strip()}:{title.lower().strip()}"

    # Check cache
    try:
        cached = await cache.redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return data if data.get("lines") else None
    except Exception:
        logger.debug("lyrics cache get failed", exc_info=True)

    # No Genius token — can't fetch
    if not settings.GENIUS_TOKEN:
        return None

    result = await _search_genius(artist, title)

    # Cache result (even empty to avoid repeated lookups)
    try:
        await cache.redis.setex(
            cache_key, _LYRICS_CACHE_TTL,
            json.dumps(result or {}, ensure_ascii=False),
        )
    except Exception:
        logger.debug("lyrics cache set failed", exc_info=True)

    return result


async def _search_genius(artist: str, title: str) -> dict | None:
    """Search Genius API and scrape lyrics page."""
    query = f"{artist} {title}"
    headers = {"Authorization": f"Bearer {settings.GENIUS_TOKEN}"}

    try:
        session = get_session()
        proxy = _genius_proxy()
        async with session.get(
            _GENIUS_SEARCH_URL,
            params={"q": query},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
            proxy=proxy,
        ) as resp:
            if resp.status != 200:
                logger.warning("Genius search failed: %s", resp.status)
                return None
            data = await resp.json()

        hits = data.get("response", {}).get("hits", [])
        if not hits:
            return None

        # Take the first result
        hit = hits[0]["result"]
        genius_url = hit.get("url", "")
        full_title = hit.get("full_title", f"{artist} — {title}")

        # Scrape lyrics from Genius page
        lyrics_text = await _scrape_lyrics(session, genius_url)
        if not lyrics_text:
            return None

        lines = [l for l in lyrics_text.split("\n") if l.strip()]
        # Return only first 10 lines (copyright compliance)
        preview_lines = lines[:10]

        return {
            "lines": preview_lines,
            "url": genius_url,
            "full_title": full_title,
        }
    except Exception as e:
        logger.warning("Genius API error: %s", e)
        return None


async def _scrape_lyrics(session: aiohttp.ClientSession, url: str) -> str | None:
    """Scrape lyrics text from a Genius page."""
    if not url:
        return None
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Mozilla/5.0"},
            proxy=_genius_proxy(),
        ) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()

        # Extract lyrics from data-lyrics-container divs
        # Genius wraps lyrics in <div data-lyrics-container="true">
        containers = re.findall(
            r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        if not containers:
            return None

        text = "\n".join(containers)
        # Remove HTML tags
        text = re.sub(r"<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        # Decode HTML entities
        text = text.replace("&#x27;", "'").replace("&amp;", "&").replace("&quot;", '"')
        text = text.strip()
        return text if text else None
    except Exception as e:
        logger.warning("Genius scrape error: %s", e)
        return None


async def search_by_lyrics(query: str, limit: int = 3) -> list[dict]:
    """Search Genius by lyrics text. Returns list of {artist, title, source} dicts.

    Useful when user searches by song lyrics rather than artist/title.
    """
    if not query.strip():
        return []

    global _genius_disabled_until
    if _genius_disabled_until > time.time():
        return []

    try:
        session = get_session()
        proxy = _genius_proxy()
        hits = []
        if settings.GENIUS_TOKEN:
            headers = {"Authorization": f"Bearer {settings.GENIUS_TOKEN}"}
            async with session.get(
                _GENIUS_SEARCH_URL,
                params={"q": query},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=8),
                proxy=proxy,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hits = data.get("response", {}).get("hits", [])
        else:
            async with session.get(
                _GENIUS_PUBLIC_MULTI_URL,
                params={"q": query, "per_page": max(limit, 5)},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=8),
                proxy=proxy,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sections = data.get("response", {}).get("sections", [])
                    for section in sections:
                        if section.get("type") != "song":
                            continue
                        hits = [item for item in section.get("hits", []) if item.get("result")]
                        if hits:
                            break

        results = []
        for hit in hits[:limit]:
            song = hit.get("result", {})
            artist = song.get("primary_artist", {}).get("name", "").strip()
            title = song.get("title", "").strip()
            if artist and title:
                results.append({
                    "artist": artist,
                    "title": title,
                    "genius_url": song.get("url", ""),
                    "source": "genius",
                })
        return results
    except Exception as e:
        if "getaddrinfo failed" in str(e).lower() or "dns" in str(e).lower() or "nameresolutionerror" in str(e).lower():
            _genius_disabled_until = time.time() + _GENIUS_RETRY_AFTER
            logger.warning("Genius lyrics search disabled for %ds after DNS failure", _GENIUS_RETRY_AFTER)
        else:
            logger.warning("Genius lyrics search error: %s", e)
        return []


async def translate_lyrics(lines: list[str], target_lang: str = "ru") -> list[str] | None:
    """Translate lyrics lines using MyMemory free API.

    target_lang: ISO 639-1 code (e.g. 'ru', 'en', 'kg').
    Returns translated lines or None on failure.
    """
    text = "\n".join(lines)
    if not text.strip():
        return None

    # MyMemory auto-detects source language
    params = {"q": text[:4500], "langpair": f"auto|{target_lang}"}

    try:
        session = get_session()
        async with session.get(
            "https://api.mymemory.translated.net/get",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        translated = data.get("responseData", {}).get("translatedText", "")
        if not translated or "MYMEMORY" in translated.upper():
            return None
        return [l for l in translated.split("\n") if l.strip()]
    except Exception as e:
        logger.warning("Translation error: %s", e)
        return None
