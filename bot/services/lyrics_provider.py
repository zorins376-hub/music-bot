"""
lyrics_provider.py — Fetch song lyrics via Genius API.

- Searches Genius for artist + title
- Returns first 10 lines + Genius URL (copyright compliance)
- Caches in Redis with TTL 7 days
"""
import json
import logging
import re

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

_GENIUS_SEARCH_URL = "https://api.genius.com/search"
_LYRICS_CACHE_TTL = 7 * 24 * 3600  # 7 days


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
        pass

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
        pass

    return result


async def _search_genius(artist: str, title: str) -> dict | None:
    """Search Genius API and scrape lyrics page."""
    query = f"{artist} {title}"
    headers = {"Authorization": f"Bearer {settings.GENIUS_TOKEN}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _GENIUS_SEARCH_URL,
                params={"q": query},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
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
        async with aiohttp.ClientSession() as session:
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
