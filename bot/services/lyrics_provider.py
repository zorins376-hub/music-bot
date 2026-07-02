"""
lyrics_provider.py — Fetch song lyrics via Genius API.

- Searches Genius for artist + title
- Returns first 10 lines + Genius URL (copyright compliance)
- Caches in Redis with TTL 7 days
"""
import asyncio
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
_LRCLIB_GET_URL = "https://lrclib.net/api/get"
_MUSIXMATCH_DEFAULT_KEY = "68abb93fbe3a11298b12092e27e6e56f"


def _lyrics_proxy() -> str | None:
    """Proxy for lyrics APIs — Genius/Musixmatch may block datacenter IPs."""
    for candidate in (
        settings.GENIUS_PROXY_URL,
        settings.YOUTUBE_PROXY,
    ):
        proxy = (candidate or "").strip()
        if proxy:
            if proxy.startswith("http://") or proxy.startswith("https://"):
                return proxy
            return None
    pool = (settings.PROXY_POOL or "").strip()
    if pool:
        first = pool.split(",")[0].strip()
        if first:
            if first.startswith("http://") or first.startswith("https://"):
                return first
            return None
    return None


def _genius_proxy() -> str | None:
    return _lyrics_proxy()


def _musixmatch_api_key() -> str:
    return (settings.MUSIXMATCH_API_KEY or "").strip() or _MUSIXMATCH_DEFAULT_KEY


def _genius_session() -> aiohttp.ClientSession:
    """Return an aiohttp session for Genius requests (proxy-aware)."""
    proxy = _genius_proxy()
    if proxy:
        conn = aiohttp.TCPConnector()
        return aiohttp.ClientSession(connector=conn)
    return get_session()


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
    """Search for song by lyrics text. Returns list of {artist, title, source} dicts.

    Tries Musixmatch q_lyrics first (best for lyric fragments), then Genius API /
    public endpoint. Multiple query variants are tried for typo / stop-word tails.
    Results are cached in Redis for 24h.
    """
    query = query.strip()
    if not query:
        return []

    from bot.services.cache import cache
    from bot.services.search_engine import lyric_search_variants, normalize_query

    norm = normalize_query(query)
    cache_key = f"lyrics:search:{norm[:120]}"
    try:
        cached = await cache.redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, list):
                return data[:limit]
    except Exception:
        logger.debug("lyrics search cache get failed", exc_info=True)

    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for variant in lyric_search_variants(query)[:5]:
        batch = await _search_musixmatch_lyrics(variant, limit)
        if not batch:
            batch = await _search_genius_lyrics(variant, limit)
        for hit in batch:
            key = (
                (hit.get("artist") or "").lower().strip(),
                (hit.get("title") or "").lower().strip(),
            )
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            hit["_variant"] = variant
            merged.append(hit)
        if len(merged) >= limit:
            break

    results = _rank_lyric_hints(merged, query)[:limit]

    try:
        await cache.redis.setex(
            cache_key,
            24 * 3600,
            json.dumps(results, ensure_ascii=False),
        )
    except Exception:
        logger.debug("lyrics search cache set failed", exc_info=True)

    return results


def _rank_lyric_hints(hints: list[dict], query: str) -> list[dict]:
    """Sort lyrics DB hits: prefer artist/title overlap with the lyric fragment."""
    from bot.services.search_engine import (
        extract_distinctive_lyric_words,
        normalize_query,
        query_word_coverage,
        _hint_word_in_title,
    )

    qn = normalize_query(query)
    distinctive = extract_distinctive_lyric_words(query)

    def _score(h: dict) -> float:
        artist = h.get("artist", "")
        title = h.get("title", "")
        cov = query_word_coverage(qn, artist, title)
        variant = h.get("_variant", "")
        if variant and variant != qn:
            cov = max(cov, query_word_coverage(normalize_query(variant), artist, title) * 0.85)
        title_n = normalize_query(title)
        for w in distinctive:
            if w in title_n or _hint_word_in_title(w, title_n):
                cov += 0.45
        return cov

    indexed = list(enumerate(hints))
    indexed.sort(key=lambda pair: (_score(pair[1]), -pair[0]), reverse=True)
    return [h for _, h in indexed]


async def _search_genius_lyrics(query: str, limit: int) -> list[dict]:
    """Search Genius by lyrics text."""
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
        err = str(e).lower()
        if "getaddrinfo failed" in err or "dns" in err or "nameresolutionerror" in err or "403" in err:
            _genius_disabled_until = time.time() + _GENIUS_RETRY_AFTER
            logger.warning("Genius lyrics search disabled for %ds after failure: %s", _GENIUS_RETRY_AFTER, e)
        else:
            logger.warning("Genius lyrics search error: %s", e)
        return []


_MUSIXMATCH_SEARCH_URL = "https://api.musixmatch.com/ws/1.1/track.search"
_MUSIXMATCH_LYRICS_URL = "https://api.musixmatch.com/ws/1.1/track.lyrics.get"


def _normalize_lyric_blob(text: str) -> str:
    from bot.services.search_engine import normalize_query

    blob = normalize_query(text.replace("\n", " "))
    return blob.replace("ё", "е")


def _lyric_word_in_blob(word: str, lyrics_norm: str) -> bool:
    if word in lyrics_norm:
        return True
    folded = word.replace("ь", "").replace("ъ", "")
    if folded and folded in lyrics_norm:
        return True
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return False
    for chunk in lyrics_norm.split():
        if len(word) >= 5 and len(chunk) >= 5:
            if float(fuzz.ratio(word, chunk)) / 100.0 >= 0.82:
                return True
    return False


def lyric_fragment_matches_query(query_norm: str, plain_lyrics: str) -> bool:
    """True when plain lyrics contain the user's lyric fragment."""
    if not query_norm or not plain_lyrics:
        return False
    lyrics_norm = _normalize_lyric_blob(plain_lyrics)
    qn = _normalize_lyric_blob(query_norm)
    if not lyrics_norm:
        return False
    if qn in lyrics_norm:
        return True
    words = [w for w in qn.split() if len(w) > 2]
    if len(words) >= 2:
        tail = " ".join(words[-3:])
        if tail in lyrics_norm:
            return True
        found = sum(1 for w in words if _lyric_word_in_blob(w, lyrics_norm))
        return found / len(words) >= 0.65
    return False


def _lyric_match_strength(query_norm: str, plain_lyrics: str) -> float:
    lyrics_norm = _normalize_lyric_blob(plain_lyrics)
    qn = _normalize_lyric_blob(query_norm)
    if not lyrics_norm:
        return 0.0
    if qn in lyrics_norm:
        return 1.0
    words = [w for w in qn.split() if len(w) > 2]
    if not words:
        return 0.0
    found = sum(1 for w in words if _lyric_word_in_blob(w, lyrics_norm))
    return found / len(words)


async def _lrclib_fetch_plain_lyrics(artist: str, title: str) -> str | None:
    """Fetch plain lyrics text from LRCLib (free, no API key)."""
    from bot.services.cache import cache

    cache_key = f"lrclib:plain:{artist.lower()}:{title.lower()}"
    try:
        cached = await cache.redis.get(cache_key)
        if cached is not None:
            return cached or None
    except Exception:
        pass

    plain: str | None = None
    try:
        session = get_session()
        async with session.get(
            _LRCLIB_GET_URL,
            params={"artist_name": artist, "track_name": title},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                plain = (data.get("plainLyrics") or "").strip() or None
    except Exception as e:
        logger.debug("LRCLib get failed %s - %s: %s", artist, title, e)

    try:
        await cache.redis.setex(cache_key, 7 * 24 * 3600, plain or "")
    except Exception:
        pass
    return plain


async def resolve_lyrics_from_candidates(
    query: str,
    candidates: list[dict],
    *,
    limit: int = 3,
) -> list[dict]:
    """Verify provider candidates against LRCLib lyrics text."""
    from bot.services.search_engine import normalize_query

    qn = normalize_query(query)
    if not qn or not candidates:
        return []

    seen: set[tuple[str, str]] = set()
    verified: list[tuple[float, dict]] = []

    for track in candidates:
        artist = (track.get("uploader") or "").strip()
        title = (track.get("title") or "").strip()
        if not artist or not title:
            continue
        key = (artist.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)

        plain = await _lrclib_fetch_plain_lyrics(artist, title)
        if not plain or not lyric_fragment_matches_query(qn, plain):
            continue
        strength = _lyric_match_strength(qn, plain)
        verified.append((
            strength,
            {
                "artist": artist,
                "title": title,
                "source": "lrclib",
                "_match_strength": strength,
            },
        ))

    verified.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in verified[:limit]]


async def gather_lyric_verify_pool(
    query: str,
    base_candidates: list[dict],
    *,
    search_yandex_fn,
    search_vk_fn,
    parsed: dict | None = None,
    max_tracks: int = 45,
) -> list[dict]:
    """Widen provider pool before LRCLib text verification."""
    from bot.services.search_engine import (
        extract_distinctive_lyric_words,
        lyric_search_variants,
        normalize_query,
    )

    pool: list[dict] = list(base_candidates)
    seen: set[str] = {
        t.get("video_id", "")
        for t in pool
        if t.get("video_id")
    }

    extra_queries = list(lyric_search_variants(query, parsed))
    words = normalize_query(query).split()
    if len(words) >= 2:
        extra_queries.append(" ".join(words[-2:]))
    for word in extract_distinctive_lyric_words(query)[:2]:
        extra_queries.append(word)

    for q in list(dict.fromkeys(extra_queries))[:6]:
        try:
            yandex, vk = await asyncio.gather(
                asyncio.wait_for(search_yandex_fn(q, limit=4), timeout=8),
                asyncio.wait_for(search_vk_fn(q, limit=3), timeout=8),
            )
        except Exception:
            continue
        for track in (yandex or []) + (vk or []):
            vid = track.get("video_id", "")
            if vid and vid in seen:
                continue
            if vid:
                seen.add(vid)
            pool.append(track)
            if len(pool) >= max_tracks:
                return pool
    return pool


async def search_lrclib_catalog(query: str, limit: int = 5) -> list[dict]:
    """Search LRCLib metadata index, then verify plainLyrics against the fragment."""
    from bot.services.search_engine import extract_distinctive_lyric_words, normalize_query

    qn = normalize_query(query)
    queries = [qn] + extract_distinctive_lyric_words(query)[:2]
    seen: set[tuple[str, str]] = set()
    verified: list[tuple[float, dict]] = []

    session = get_session()
    for q in dict.fromkeys(queries):
        try:
            async with session.get(
                "https://lrclib.net/api/search",
                params={"q": q},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    continue
                items = await resp.json()
        except Exception:
            continue
        if not isinstance(items, list):
            continue

        for item in items[: max(limit, 8)]:
            artist = (item.get("artistName") or "").strip()
            title = (item.get("trackName") or "").strip()
            if not artist or not title:
                continue
            key = (artist.lower(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            plain = await _lrclib_fetch_plain_lyrics(artist, title)
            if not plain or not lyric_fragment_matches_query(qn, plain):
                continue
            strength = _lyric_match_strength(qn, plain)
            verified.append((
                strength,
                {
                    "artist": artist,
                    "title": title,
                    "source": "lrclib",
                    "_match_strength": strength,
                },
            ))

    verified.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in verified[:limit]]


async def _search_musixmatch_lyrics(query: str, limit: int) -> list[dict]:
    """Fallback lyrics search via Musixmatch public API."""
    try:
        session = get_session()
        proxy = _lyrics_proxy()
        params = {
            "q_lyrics": query,
            "page_size": max(limit, 5),
            "page": 1,
            "s_track_rating": "desc",
            "apikey": _musixmatch_api_key(),
        }
        async with session.get(
            _MUSIXMATCH_SEARCH_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=8),
            proxy=proxy,
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        status_code = data.get("message", {}).get("header", {}).get("status_code", 200)
        if status_code != 200:
            return []

        track_list = (
            data.get("message", {})
            .get("body", {})
            .get("track_list", [])
        )
        results = []
        for item in track_list[:limit]:
            track = item.get("track", {})
            artist = (track.get("artist_name") or "").strip()
            title = (track.get("track_name") or "").strip()
            if artist and title:
                results.append({
                    "artist": artist,
                    "title": title,
                    "source": "musixmatch",
                })
        if results:
            return results

        # General track search when q_lyrics returns nothing.
        async with session.get(
            _MUSIXMATCH_SEARCH_URL,
            params={
                "q": query,
                "page_size": max(limit, 5),
                "page": 1,
                "s_track_rating": "desc",
                "apikey": params["apikey"],
            },
            timeout=aiohttp.ClientTimeout(total=8),
            proxy=proxy,
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        if data.get("message", {}).get("header", {}).get("status_code", 200) != 200:
            return []
        track_list = (
            data.get("message", {})
            .get("body", {})
            .get("track_list", [])
        )
        for item in track_list[:limit]:
            track = item.get("track", {})
            artist = (track.get("artist_name") or "").strip()
            title = (track.get("track_name") or "").strip()
            if artist and title:
                results.append({
                    "artist": artist,
                    "title": title,
                    "source": "musixmatch",
                })
        return results
    except Exception as e:
        logger.debug("Musixmatch lyrics search error: %s", e)
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
    params = {"q": text[:500], "langpair": f"auto|{target_lang}"}

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

        if data.get("responseStatus") not in (200, "200"):
            return None
        translated = data.get("responseData", {}).get("translatedText", "")
        if not translated or "MYMEMORY" in translated.upper():
            return None
        return [l for l in translated.split("\n") if l.strip()]
    except Exception as e:
        logger.warning("Translation error: %s", e)
        return None
