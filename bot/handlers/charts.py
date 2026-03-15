"""Top charts: Shazam · YouTube · VK — paginated lists with download."""

import asyncio
import itertools
import json
import logging
import re
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import get_or_create_user
from bot.db import upsert_track
from bot.i18n import t
from bot.models.base import async_session
from bot.models.playlist import Playlist, PlaylistTrack
from bot.services.downloader import cleanup_file, download_track, search_tracks
from bot.services.cache import cache
from bot.services.http_session import get_session
from bot.services.proxy_pool import proxy_pool

logger = logging.getLogger(__name__)
router = Router()

_LOGO = "◉ <b>BLACK ROOM</b>"
_PER_PAGE = 5
_CHART_TTL = 6 * 3600  # 6 hours cache
_CHART_IMPORT_DEFAULT_LIMIT = 100
_CHART_PREWARM_INTERVAL = 2 * 3600
_CHART_PREPARE_TOP_N = 100
_chart_cancel_jobs: set[str] = set()

_ytdl_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chart")


# ── Callback Data ────────────────────────────────────────────────────────

class ChartCb(CallbackData, prefix="ch"):
    src: str   # shazam / youtube / vk
    p: int     # page (0-based)


class ChartDl(CallbackData, prefix="cd"):
    sid: str   # session id
    i: int     # track index


class ChartBulk(CallbackData, prefix="cb"):
    src: str
    sid: str
    lim: int


class ChartBulkCtl(CallbackData, prefix="cbc"):
    job: str


class ChartBulkResume(CallbackData, prefix="cbr"):
    token: str


# ── Chart fetchers ───────────────────────────────────────────────────────

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def _has_cyrillic(text: str) -> bool:
    """Check if text contains at least one Cyrillic character."""
    return bool(_CYRILLIC_RE.search(text))


def _parse_yt_entries(entries: list, cyrillic_only: bool = False) -> list[dict]:
    """Parse yt-dlp playlist entries into chart track dicts.
    Filters out compilations (duration > 8 min) and keeps only individual songs.
    If cyrillic_only=True, keeps only tracks with Cyrillic in artist or title."""
    tracks = []
    for entry in entries:
        if not entry:
            continue
        # Skip compilations / mixes (> 8 minutes)
        dur = entry.get("duration") or 0
        if dur and dur > 480:
            continue
        raw_title = entry.get("title", "Unknown")
        uploader = entry.get("uploader") or entry.get("channel") or ""
        for sep in (" — ", " – ", " - "):
            if sep in raw_title:
                parts = raw_title.split(sep, 1)
                artist, title = parts[0].strip(), parts[1].strip()
                break
        else:
            artist, title = uploader, raw_title
        if cyrillic_only and not (_has_cyrillic(artist) or _has_cyrillic(title)):
            continue
        vid = entry.get("id", "")
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
            "video_id": vid,
            "cover_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None,
        })
    return tracks


async def _fetch_apple_chart(storefront: str) -> list[dict]:
    """Fetch Apple Music / iTunes top songs chart.
    Uses official iTunes RSS API (itunes.apple.com) as primary.
    storefront: 'us', 'ru', 'gb', 'de', etc."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*",
    }

    # Primary: official iTunes RSS API
    itunes_url = f"https://itunes.apple.com/{storefront}/rss/topsongs/limit=100/json"
    try:
        sess = get_session()
        logger.info("Apple chart %s: connector=%s, url=%s", storefront, type(sess.connector).__name__, itunes_url)
        async with sess.get(itunes_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                entries = data.get("feed", {}).get("entry", [])
                tracks = []
                for item in entries[:100]:
                    title = (item.get("im:name") or {}).get("label", "Unknown")
                    artist = (item.get("im:artist") or {}).get("label", "Unknown")
                    # Extract cover art from im:image (take largest)
                    images = item.get("im:image") or []
                    cover_url = None
                    if images:
                        raw_url = images[-1].get("label", "") if isinstance(images[-1], dict) else str(images[-1])
                        if raw_url:
                            # Upscale: replace size suffix (e.g. 170x170bb) with 400x400bb
                            cover_url = re.sub(r'\d+x\d+(bb|cc|sr)', '400x400\\1', raw_url) if raw_url else None
                    if title and artist:
                        tracks.append({
                            "title": title,
                            "artist": artist,
                            "query": f"{artist} - {title}",
                            "cover_url": cover_url,
                        })
                if tracks:
                    return tracks
            else:
                logger.warning("iTunes RSS %s returned HTTP %s", storefront, resp.status)
    except Exception as e:
        logger.warning("iTunes RSS error (%s): %s", storefront, e)

    # Fallback: Apple Music RSS v2 (unofficial mirror, may be down)
    fallback_url = f"https://rss.applemonitoring.com/api/v2/{storefront}/music/most-played/100/songs.json"
    try:
        sess = get_session()
        async with sess.get(fallback_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                results = data.get("feed", {}).get("results", [])
                tracks = []
                for item in results[:100]:
                    artist = item.get("artistName", "Unknown")
                    title = item.get("name", "Unknown")
                    cover_url = item.get("artworkUrl100") or None
                    if cover_url:
                        cover_url = cover_url.replace("100x100", "400x400")
                    tracks.append({
                        "title": title,
                        "artist": artist,
                        "query": f"{artist} - {title}",
                        "cover_url": cover_url,
                    })
                if tracks:
                    return tracks
    except Exception as e:
        logger.warning("Apple Music RSS mirror error (%s): %s", storefront, e)

    return []


def _fetch_yt_playlist_sync(playlist_urls: list[str], max_tracks: int = 100, cyrillic_only: bool = False) -> list[dict]:
    """Try multiple YouTube playlists, return first that works. Individual songs only."""
    import yt_dlp
    from bot.services.downloader import _base_opts

    fetch_extra = 80 if cyrillic_only else 20
    for playlist_url in playlist_urls:
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "playlistend": max_tracks + fetch_extra,
            **_base_opts(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                # Convert to list inside context to avoid I/O errors
                entries = list(info.get("entries", [])) if info else []
                tracks = _parse_yt_entries(entries, cyrillic_only=cyrillic_only)
                if tracks:
                    return tracks[:max_tracks]
        except Exception as e:
            logger.warning("YT playlist %s failed: %s", playlist_url, e)
    return []


async def _fetch_shazam() -> list[dict]:
    """Shazam Top 50 — Apple Music global chart (same ecosystem)."""
    # Apple Music most-played = closely mirrors Shazam chart
    tracks = await _fetch_apple_chart("us")
    if tracks:
        return tracks
    # Fallback: YouTube playlist extraction
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_yt_playlist_sync, [
        "https://www.youtube.com/playlist?list=PLDIoUOhQQPlXr63I_vwF9GD8sAKh77dWU",
        "https://www.youtube.com/playlist?list=PLhsz9CILh0673e1Hxlz54h0ldGpc4AMR0",
    ])


async def _fetch_youtube() -> list[dict]:
    """YouTube Music Global Top — official trending playlist."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_yt_playlist_sync, [
        "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
        "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
    ])


async def _fetch_vk() -> list[dict]:
    """Яндекс Музыка Топ Россия — official chart, only Russian-language tracks."""
    tracks = await _fetch_yandex_chart()
    if tracks:
        return tracks
    # Fallback: Apple Music Russia with Cyrillic filter
    apple_tracks = await _fetch_apple_chart("ru")
    if apple_tracks:
        ru_tracks = [t for t in apple_tracks if _has_cyrillic(t["artist"]) or _has_cyrillic(t["title"])]
        if ru_tracks:
            return ru_tracks
    # Last resort: YouTube playlists
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_yt_playlist_sync, [
        "https://www.youtube.com/playlist?list=PLw-VjHDlEOgtYfGcmRbz3PS1MKx31KP-9",
        "https://www.youtube.com/playlist?list=PLw-VjHDlEOgs658kAHR_LAaILBXb-s6Q5",
    ], 50, True)


async def _fetch_yandex_chart() -> list[dict]:
    """Официальный чарт Яндекс Музыки (Россия)."""
    from bot.config import settings
    if not settings.CHART_YANDEX_ENABLED:
        return []  # Skip if disabled (geo-blocked IPs)
    try:
        from yandex_music import ClientAsync
    except ImportError:
        logger.warning("yandex-music package not installed")
        return []

    tokens: list[str] = []
    pool_raw = (settings.YANDEX_TOKENS or "").strip()
    if pool_raw:
        tokens.extend([t.strip() for t in pool_raw.split(",") if t.strip()])
    single = (settings.YANDEX_MUSIC_TOKEN or "").strip()
    if single and single not in tokens:
        tokens.append(single)
    if not tokens:
        logger.warning("Yandex chart: no token configured, trying anonymous access")
        tokens = [None]

    token_cycle = itertools.cycle(tokens)
    try:
        attempts = max(len(tokens), 1)
        for _ in range(attempts):
            token = next(token_cycle)
            proxy_url = proxy_pool.get_next() if proxy_pool.size else None
            try:
                kwargs = {"proxy_url": proxy_url} if proxy_url else {}
                if token:
                    client = await ClientAsync(token, **kwargs).init()
                else:
                    client = await ClientAsync(**kwargs).init()
                # chart() returns ChartInfo; chart("russia") for Russian chart
                chart_info = await client.chart("russia")
                if not chart_info or not getattr(chart_info, "chart", None):
                    if proxy_url:
                        proxy_pool.record_failure(proxy_url)
                    continue

                tracks = []
                for item in (chart_info.chart.tracks or [])[:100]:
                    track = getattr(item, "track", None) or item
                    if not track:
                        continue
                    title = getattr(track, "title", None) or "Unknown"
                    artists = getattr(track, "artists", []) or []
                    artist = artists[0].name if artists else "Unknown"
                    # Skip compilations (> 8 min)
                    dur_ms = getattr(track, "duration_ms", 0) or 0
                    if dur_ms and dur_ms > 480_000:
                        continue
                    # Build ym_ video_id for direct Yandex streaming
                    track_id = getattr(track, "id", None) or getattr(track, "track_id", None)
                    ym_video_id = f"ym_{track_id}" if track_id else ""
                    # Extract cover art (try track → albums → og_image)
                    cover_url = None
                    cover_uri = getattr(track, "cover_uri", None) or ""
                    if not cover_uri:
                        # Try album cover
                        albums = getattr(track, "albums", []) or []
                        if albums:
                            cover_uri = getattr(albums[0], "cover_uri", None) or ""
                    if not cover_uri:
                        cover_uri = getattr(track, "og_image", None) or ""
                    if cover_uri:
                        cover_url = "https://" + cover_uri.replace("%%", "400x400")
                    tracks.append({
                        "title": title,
                        "artist": artist,
                        "query": f"{artist} - {title}",
                        "video_id": ym_video_id,
                        "cover_url": cover_url,
                        "source": "yandex",
                        "duration": round(dur_ms / 1000) if dur_ms else 0,
                    })

                if tracks:
                    if proxy_url:
                        proxy_pool.record_success(proxy_url)
                    return tracks
                if proxy_url:
                    proxy_pool.record_failure(proxy_url)
            except Exception as inner_e:
                if proxy_url:
                    proxy_pool.record_failure(proxy_url)
                logger.warning("Yandex chart attempt failed (proxy=%s): %s", bool(proxy_url), inner_e)
                continue
        return []
    except Exception as e:
        logger.error("Яндекс Музыка chart error: %s", e)
        return []


async def _fetch_html(url: str, headers: dict) -> str:
    """Fetch HTML from URL, return empty string on failure."""
    try:
        sess = get_session()
        async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning("HTTP %s for %s", resp.status, url)
                return ""
            return await resp.text()
    except Exception as e:
        logger.warning("Fetch error %s: %s", url, e)
        return ""


def _extract_json_array(html: str, key: str) -> list:
    """Find `"key":[...]` in HTML and extract the JSON array.
    Handles both plain JSON and escaped JSON-in-JS (\\"key\\":[...])."""
    for quote in ('"', '\\"'):
        marker = f'{quote}{key}{quote}:'
        idx = html.find(marker)
        if idx < 0:
            continue
        # Find opening bracket
        bracket_start = html.find("[", idx + len(marker))
        if bracket_start < 0 or bracket_start - (idx + len(marker)) > 5:
            continue

        if quote == '\\"':
            # Unescape a window around the data (up to 300KB), then parse
            window = html[bracket_start: bracket_start + 300_000]
            unescaped = window.replace('\\"', '"').replace("\\\\", "\\")
        else:
            unescaped = html[bracket_start: bracket_start + 300_000]

        # Bracket-count to extract the full array
        depth = 0
        in_str = False
        escaped = False
        for i, c in enumerate(unescaped):
            if escaped:
                escaped = False
                continue
            if c == "\\" and in_str:
                escaped = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if not in_str:
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(unescaped[: i + 1])
                        except Exception:
                            return []
    return []


def _parse_rusradio_json(html: str) -> list[dict]:
    """Parse track data from rusradio.ru Next.js SSR page (embedded JSON)."""
    items = _extract_json_array(html, "tracks")
    if not items:
        return []
    tracks: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        artist = str(item.get("artist") or "").strip()
        if not title or not artist:
            continue
        if len(title) > 80 or len(artist) > 80:
            continue
        # Skip compilations (duration in seconds on this site)
        dur = item.get("duration") or 0
        if dur and dur > 480:
            continue
        key = f"{artist.lower()}\t{title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        tracks.append({"title": title, "artist": artist, "query": f"{artist} - {title}"})
    return tracks


def _parse_rusradio_html_fallback(html: str) -> list[dict]:
    """Fallback HTML scraping for older rusradio.ru chart pages."""
    tracks: list[dict] = []
    seen: set[str] = set()

    def _add(artist: str, title: str) -> bool:
        artist, title = artist.strip(), title.strip()
        if not artist or not title or len(artist) > 80 or len(title) > 80:
            return False
        key = f"{artist.lower()}\t{title.lower()}"
        if key in seen:
            return False
        seen.add(key)
        tracks.append({"title": title, "artist": artist, "query": f"{artist} - {title}"})
        return True

    # JSON-LD
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    ):
        try:
            obj = json.loads(m.group(1))
            for item in (obj if isinstance(obj, list) else [obj]):
                if isinstance(item, dict) and item.get("@type") in ("MusicRecording", "Song"):
                    a = item.get("byArtist", {})
                    _add(a.get("name", "") if isinstance(a, dict) else str(a), item.get("name", ""))
        except Exception:
            pass
    if tracks:
        return tracks

    # Legacy voting page (Голосовать buttons)
    parts = re.split(r"rusradio\.ru/b/d/\S+?\.(?:webp|jpg|png)", html)
    for chunk in parts[1:]:
        gpos = chunk.find("ГОЛОСОВАТЬ")
        if gpos < 0 or gpos > 2000:
            continue
        block = chunk[:gpos]
        text = re.sub(r"<[^>]+>", "\n", block)
        lines = [
            ln.strip() for ln in text.splitlines()
            if ln.strip()
            and re.search(r"[А-Яа-яA-Za-z]", ln)
            and 2 <= len(ln.strip()) <= 80
            and not ln.strip().startswith("http")
            and not ln.strip().isdigit()
        ]
        if len(lines) >= 2:
            _add(lines[1], lines[0])
        if len(tracks) >= 50:
            break

    return tracks


async def _fetch_rusradio() -> list[dict]:
    """Русское Радио — Хит-парад Золотой Граммофон."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Primary: parse embedded JSON from the official hit-parad page
    html = await _fetch_html("https://rusradio.ru/charts/hit-parad-zolotoj-grammofon", headers)
    if html:
        tracks = _parse_rusradio_json(html)
        if tracks:
            logger.info("Rusradio chart: %d tracks from hit-parad JSON", len(tracks))
            return tracks
        # Try HTML fallback on same page (old layout)
        tracks = _parse_rusradio_html_fallback(html)
        if tracks:
            logger.info("Rusradio chart: %d tracks from hit-parad HTML", len(tracks))
            return tracks

    # Try general charts page
    html = await _fetch_html("https://rusradio.ru/charts", headers)
    if html:
        tracks = _parse_rusradio_json(html)
        if tracks:
            logger.info("Rusradio chart: %d tracks from /charts JSON", len(tracks))
            return tracks

    # Seasonal voting page (active during award season)
    html = await _fetch_html("https://rusradio.ru/charts/golosujte-za-treki", headers)
    if html:
        tracks = _parse_rusradio_html_fallback(html)
        if tracks:
            logger.info("Rusradio chart: %d tracks from voting page", len(tracks))
            return tracks

    logger.warning("Rusradio chart: all strategies failed, using Яндекс fallback")

    # Fallback 1: Яндекс Музыка чарт Россия (already works for VK chart)
    yandex_tracks = await _fetch_yandex_chart()
    if yandex_tracks:
        return yandex_tracks

    # Fallback 2: Apple Music Russia + Cyrillic filter
    apple_tracks = await _fetch_apple_chart("ru")
    if apple_tracks:
        ru_tracks = [t for t in apple_tracks if _has_cyrillic(t["artist"]) or _has_cyrillic(t["title"])]
        if ru_tracks:
            return ru_tracks[:100]

    return []


async def _fetch_europaplus_site() -> list[dict]:
    """Scrape europaplus.ru TOP40 chart directly."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    urls = [
        "https://www.europaplus.ru/top/top40/",
        "https://www.europaplus.ru/top40/",
        "https://europaplus.ru/top/top40/",
    ]
    tracks: list[dict] = []
    seen: set[str] = set()

    for url in urls:
        html = await _fetch_html(url, headers)
        if not html:
            continue

        # Strategy 1: JSON-LD structured data
        for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                obj = json.loads(m.group(1))
                items = obj if isinstance(obj, list) else [obj]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") in ("MusicRecording", "Song"):
                        artist = item.get("byArtist", {})
                        if isinstance(artist, dict):
                            artist = artist.get("name", "")
                        title = item.get("name", "")
                        if artist and title:
                            key = f"{str(artist).lower()}\t{str(title).lower()}"
                            if key not in seen:
                                seen.add(key)
                                tracks.append({"title": str(title), "artist": str(artist),
                                               "query": f"{artist} - {title}"})
            except Exception:
                pass
        if tracks:
            return tracks

        # Strategy 2: chart/track card blocks
        card_re = re.compile(
            r'class="[^"]*(?:top40|chart|track|song|item)[^"]*"[^>]*>(.*?)</(?:div|li|article)>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in card_re.finditer(html):
            block = m.group(1)
            text = re.sub(r"<[^>]+>", "\n", block)
            lines = [
                ln.strip() for ln in text.splitlines()
                if ln.strip()
                and re.search(r"[А-Яа-яA-Za-z]", ln)
                and 2 <= len(ln.strip()) <= 80
                and not ln.strip().startswith("http")
                and not re.match(r"^\d+$", ln.strip())
            ]
            if len(lines) >= 2:
                for i in range(len(lines) - 1):
                    for sep in (" — ", " – ", " - "):
                        if sep in lines[i]:
                            parts = lines[i].split(sep, 1)
                            key = f"{parts[0].lower()}\t{parts[1].lower()}"
                            if key not in seen:
                                seen.add(key)
                                tracks.append({"title": parts[1], "artist": parts[0],
                                               "query": f"{parts[0]} - {parts[1]}"})
                            break
                    else:
                        key = f"{lines[i].lower()}\t{lines[i+1].lower()}"
                        if key not in seen:
                            seen.add(key)
                            tracks.append({"title": lines[i + 1], "artist": lines[i],
                                           "query": f"{lines[i]} - {lines[i+1]}"})
            if len(tracks) >= 40:
                break
        if tracks:
            return tracks

        # Strategy 3: generic «Artist — Title» separator in text
        for m in re.finditer(
            r'(?:^|>)([А-ЯЁA-Z][^\n<>—–\-]{1,40})\s*[—–]\s*([^\n<>—–]{2,60})(?:$|<)',
            html, re.MULTILINE
        ):
            artist, title = m.group(1).strip(), m.group(2).strip()
            key = f"{artist.lower()}\t{title.lower()}"
            if key not in seen:
                seen.add(key)
                tracks.append({"title": title, "artist": artist, "query": f"{artist} - {title}"})
            if len(tracks) >= 40:
                break
        if tracks:
            return tracks

    return []


async def _fetch_europa() -> list[dict]:
    """Европа Плюс TOP40 — прямой скрейпинг сайта, затем iTunes RSS."""
    # Primary: scrape europaplus.ru
    tracks = await _fetch_europaplus_site()
    if tracks:
        logger.info("Europa Plus: %d tracks from europaplus.ru", len(tracks))
        return tracks[:40]  # TOP 40

    logger.warning("Europa Plus: site scraping failed, trying iTunes RSS")
    # Fallback: iTunes RSS for European storefronts
    for storefront in ("gb", "de", "fr", "us"):
        tracks = await _fetch_apple_chart(storefront)
        if tracks:
            logger.info("Europa Plus fallback: %d tracks from iTunes %s", len(tracks), storefront)
            return tracks[:40]  # Cap to TOP 40
    return []


_CHART_FETCHERS = {
    "shazam": _fetch_shazam,
    "youtube": _fetch_youtube,
    "vk": _fetch_vk,
    "rusradio": _fetch_rusradio,
    "europa": _fetch_europa,
}

_CHART_LABELS = {
    "shazam": "Apple Music Global",
    "youtube": "YouTube Music Top",
    "vk": "Яндекс Топ Россия",
    "rusradio": "Русское Радио",
    "europa": "Европа Плюс TOP40",
}


# ── Cache helpers ────────────────────────────────────────────────────────

# Minimum expected track count per source (for stale cache detection)
_CHART_MIN_EXPECTED = {
    "shazam": 80,
    "youtube": 80,
    "vk": 80,
    "rusradio": 15,
    "europa": 35,
}


async def _get_chart(source: str) -> list[dict]:
    """Get chart from Redis cache or fetch fresh.
    Auto-refreshes if cached data is below the expected minimum for this source,
    or if too many tracks are missing cover_url or video_id (stale data).
    """
    key = f"chart:{source}"
    raw = await cache.redis.get(key)
    if raw:
        tracks = json.loads(raw)
        min_expected = _CHART_MIN_EXPECTED.get(source, 80)
        if len(tracks) >= min_expected:
            # Quality check: if >30% of tracks with video_id lack cover_url, re-fetch
            # (Apple chart tracks may not have video_id initially — that's OK)
            tracks_with_vid = [t for t in tracks if t.get("video_id")]
            if tracks_with_vid:
                n_no_cover = sum(1 for t in tracks_with_vid if not t.get("cover_url"))
                if n_no_cover > len(tracks_with_vid) * 0.3:
                    logger.info("Chart %s: %d/%d tracks missing covers, refreshing",
                                source, n_no_cover, len(tracks_with_vid))
                else:
                    return tracks
            else:
                # No tracks have video_id — either Apple chart (OK) or stale
                n_no_cover = sum(1 for t in tracks if not t.get("cover_url"))
                if n_no_cover <= len(tracks) * 0.3:
                    return tracks
                logger.info("Chart %s: %d/%d tracks missing covers, refreshing",
                            source, n_no_cover, len(tracks))
        else:
            logger.info("Chart %s has only %d tracks (min %d), refreshing", source, len(tracks), min_expected)
        await cache.redis.delete(key)

    fetcher = _CHART_FETCHERS.get(source)
    if not fetcher:
        return []
    tracks = await fetcher()
    if tracks:
        await cache.redis.setex(key, _CHART_TTL, json.dumps(tracks, ensure_ascii=False))
    return tracks


async def _prepare_chart_tracks(tracks: list[dict], max_items: int = _CHART_PREPARE_TOP_N) -> list[dict]:
    """Pre-resolve YouTube video IDs for top chart items to speed up bulk imports."""
    if not tracks:
        return tracks

    prepared = list(tracks)
    limit = min(max_items, len(prepared))
    for i in range(limit):
        tr = prepared[i]
        vid = (tr.get("video_id") or "").strip()
        if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            continue

        query = (tr.get("query") or f"{tr.get('artist', '')} {tr.get('title', '')}").strip()
        if not query:
            continue
        try:
            found = await search_tracks(query, max_results=1, source="youtube")
            if found:
                video_id = (found[0].get("video_id") or "").strip()
                if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    tr["video_id"] = video_id
        except Exception:
            continue

    return prepared


async def _prewarm_charts_once() -> None:
    """Warm chart cache and prepare top entries with resolved video IDs."""
    for src in _CHART_FETCHERS:
        try:
            tracks = await _get_chart(src)
            # _get_chart already handles stale cache refresh via _CHART_MIN_EXPECTED
            if not tracks:
                fetcher = _CHART_FETCHERS.get(src)
                if fetcher:
                    fresh = await fetcher()
                    if fresh:
                        tracks = fresh
            if not tracks:
                continue
            prepared = await _prepare_chart_tracks(tracks)
            await cache.redis.setex(
                f"chart:{src}",
                _CHART_TTL,
                json.dumps(prepared, ensure_ascii=False),
            )
            logger.info("Chart prewarm: %s prepared=%d", src, len(prepared))
        except Exception as e:
            logger.warning("Chart prewarm failed for %s: %s", src, e)


async def start_chart_cache_prewarm_scheduler() -> None:
    """Start background chart prewarm loop."""
    asyncio.create_task(_chart_prewarm_loop())


async def _chart_prewarm_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            await _prewarm_charts_once()
        except Exception as e:
            logger.warning("Chart prewarm loop error: %s", e)
        await asyncio.sleep(_CHART_PREWARM_INTERVAL)


# ── UI builders ──────────────────────────────────────────────────────────

def _chart_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Apple Music Global", callback_data=ChartCb(src="shazam", p=0).pack())],
        [InlineKeyboardButton(text="▶ YouTube Music Top", callback_data=ChartCb(src="youtube", p=0).pack())],
        [InlineKeyboardButton(text="🇷🇺 Яндекс Топ Россия", callback_data=ChartCb(src="vk", p=0).pack())],
        [InlineKeyboardButton(text="📻 Русское Радио", callback_data=ChartCb(src="rusradio", p=0).pack())],
        [InlineKeyboardButton(text="🎶 Европа Плюс TOP40", callback_data=ChartCb(src="europa", p=0).pack())],
        [InlineKeyboardButton(text="◁ Меню", callback_data="action:menu")],
    ])


def _chart_page_kb(
    source: str, page: int, total: int, session_id: str, tracks: list[dict]
) -> InlineKeyboardMarkup:
    """Build paginated track list with download buttons."""
    start = page * _PER_PAGE
    end = min(start + _PER_PAGE, total)
    rows: list[list[InlineKeyboardButton]] = []

    for i in range(start, end):
        tr = tracks[i]
        label = f"{i + 1}. {tr['artist']} — {tr['title']}"
        if len(label) > 55:
            label = label[:52] + "..."
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=ChartDl(sid=session_id, i=i).pack(),
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="➕ Импорт 100 треков",
            callback_data=ChartBulk(src=source, sid=session_id, lim=_CHART_IMPORT_DEFAULT_LIMIT).pack(),
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="➕ Импорт весь чарт",
            callback_data=ChartBulk(src=source, sid=session_id, lim=0).pack(),
        )
    ])

    # Navigation
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◁", callback_data=ChartCb(src=source, p=page - 1).pack()))
    max_page = (total - 1) // _PER_PAGE
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="▷", callback_data=ChartCb(src=source, p=page + 1).pack()))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text="◁ Чарты", callback_data="action:charts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bar(done: int, total: int) -> str:
    if total <= 0:
        return "░░░░░░░░░░"
    filled = int((done / total) * 10)
    filled = max(0, min(10, filled))
    return "█" * filled + "░" * (10 - filled)


def _fmt_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _calc_eta(started_at: float, done: int, total: int, base_done: int = 0) -> int | None:
    processed = done - base_done
    if processed <= 0:
        return None
    elapsed = time.monotonic() - started_at
    if elapsed <= 0:
        return None
    rate = elapsed / processed
    remaining = max(0, total - done)
    return int(remaining * rate)


def _bulk_kb(job: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="⏹ Отмена",
                callback_data=ChartBulkCtl(job=job).pack(),
            )
        ]]
    )


async def _append_to_chart_playlist(user_id: int, playlist_name: str, imported_track_ids: list[int]) -> int | None:
    """Append unique tracks to user's playlist. Returns added count, or None if playlist limit reached."""
    if not imported_track_ids:
        return 0

    added = 0
    async with async_session() as session:
        from sqlalchemy import func, select

        cnt = await session.scalar(select(func.count()).where(Playlist.user_id == user_id))
        existing = await session.execute(
            select(Playlist).where(Playlist.user_id == user_id, Playlist.name == playlist_name)
        )
        playlist = existing.scalar_one_or_none()

        if playlist is None:
            if (cnt or 0) >= 20:
                return None
            playlist = Playlist(user_id=user_id, name=playlist_name)
            session.add(playlist)
            await session.flush()

        existing_track_ids_r = await session.execute(
            select(PlaylistTrack.track_id).where(PlaylistTrack.playlist_id == playlist.id)
        )
        existing_track_ids = {row[0] for row in existing_track_ids_r.all()}

        pos = int(
            await session.scalar(select(func.count()).where(PlaylistTrack.playlist_id == playlist.id)) or 0
        )
        for tid in imported_track_ids:
            if tid in existing_track_ids:
                continue
            if pos >= 50:
                break
            session.add(PlaylistTrack(playlist_id=playlist.id, track_id=tid, position=pos))
            existing_track_ids.add(tid)
            pos += 1
            added += 1

        await session.commit()

    return added


# ── Handlers ─────────────────────────────────────────────────────────────

@router.message(Command("charts"))
async def cmd_charts(message: Message) -> None:
    await message.answer(
        f"{_LOGO}\n\n<b>🏆 Топ-чарты</b>\n\nВыбери рейтинг:",
        reply_markup=_chart_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "action:charts")
async def handle_charts_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"{_LOGO}\n\n<b>🏆 Топ-чарты</b>\n\nВыбери рейтинг:",
            reply_markup=_chart_menu_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"{_LOGO}\n\n<b>🏆 Топ-чарты</b>\n\nВыбери рейтинг:",
            reply_markup=_chart_menu_kb(),
            parse_mode="HTML",
        )


@router.callback_query(ChartCb.filter())
async def handle_chart_page(callback: CallbackQuery, callback_data: ChartCb) -> None:
    await callback.answer()
    source = callback_data.src
    page = callback_data.p

    if source not in _CHART_FETCHERS:
        return

    tracks = await _get_chart(source)
    if not tracks:
        try:
            await callback.message.edit_text(
                f"{_LOGO}\n\n{_CHART_LABELS.get(source, source)}\n\n<i>Не удалось загрузить чарт. Попробуй позже.</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◁ Чарты", callback_data="action:charts")]
                ]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # Store tracks in Redis for download callbacks
    session_id = f"chart_{source}"
    await cache.redis.setex(
        f"search:{session_id}",
        _CHART_TTL,
        json.dumps(tracks, ensure_ascii=False),
    )

    total = len(tracks)
    kb = _chart_page_kb(source, page, total, session_id, tracks)
    label = _CHART_LABELS.get(source, source)

    try:
        await callback.message.edit_text(
            f"{_LOGO}\n\n<b>{label}</b>\n\n<i>Нажми на трек чтобы скачать</i>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(ChartDl.filter())
async def handle_chart_download(callback: CallbackQuery, callback_data: ChartDl) -> None:
    """User tapped a chart track — search and download it."""
    await callback.answer("⏳ Ищу трек...")

    user = await get_or_create_user(callback.from_user)

    raw = await cache.redis.get(f"search:{callback_data.sid}")
    if not raw:
        await callback.message.answer("Сессия истекла. Открой чарт заново.")
        return
    tracks = json.loads(raw)
    if callback_data.i >= len(tracks):
        return

    track = tracks[callback_data.i]
    query = track.get("query") or f"{track.get('artist', '')} {track.get('title', '')}"

    # Delegate to search handler's _do_search via a synthetic message approach
    # Simpler: just trigger search directly
    from bot.handlers.search import _do_search
    await _do_search(callback.message, query.strip())


@router.callback_query(ChartBulk.filter())
async def handle_chart_bulk(callback: CallbackQuery, callback_data: ChartBulk) -> None:
    await callback.answer("⏳ Готовлю импорт чарта...")

    user = await get_or_create_user(callback.from_user)
    raw = await cache.redis.get(f"search:{callback_data.sid}")
    if not raw:
        await callback.message.answer("Сессия чарта истекла. Открой чарт заново.")
        return

    tracks_all = json.loads(raw)
    limit = len(tracks_all) if callback_data.lim <= 0 else min(int(callback_data.lim), len(tracks_all))
    tracks = tracks_all[:limit]
    if not tracks:
        await callback.message.answer("Чарт пуст.")
        return

    source_label = _CHART_LABELS.get(callback_data.src, callback_data.src)
    date_label = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    playlist_name = f"Chart {source_label[:32]} {date_label}"[:95]

    job_id = secrets.token_urlsafe(6)
    started_at = time.monotonic()
    status = await callback.message.answer(
        f"⏳ Импорт чарта в плейлист\n"
        f"ETA: {_fmt_eta(None)}\n\n"
        f"[{_bar(0, len(tracks))}] 0/{len(tracks)}",
        reply_markup=_bulk_kb(job_id),
    )

    # Determine target bitrate (free users max 192)
    try:
        bitrate = int(user.quality) if str(user.quality).isdigit() else 192
    except Exception:
        bitrate = 192
    if not user.is_premium:
        bitrate = min(bitrate, 192)

    imported_track_ids: list[int] = []
    downloaded = 0
    failed = 0
    cancelled = False

    next_index = 0
    for idx, tr in enumerate(tracks, 1):
        if job_id in _chart_cancel_jobs:
            cancelled = True
            next_index = idx - 1
            break

        query = tr.get("query") or f"{tr.get('artist', '')} {tr.get('title', '')}".strip()
        video_id = tr.get("video_id") or ""
        info = None

        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            info = {
                "video_id": video_id,
                "title": tr.get("title") or "Unknown",
                "uploader": tr.get("artist") or "Unknown",
                "duration": None,
            }
        else:
            found = await search_tracks(query, max_results=1, source="youtube")
            if found:
                info = found[0]

        if not info:
            failed += 1
        else:
            mp3_path = None
            try:
                mp3_path = await download_track(
                    info["video_id"],
                    bitrate=bitrate,
                    dl_id=uuid.uuid4().hex[:8],
                )
                downloaded += 1
                track = await upsert_track(
                    source_id=info["video_id"],
                    title=info.get("title"),
                    artist=info.get("uploader"),
                    duration=int(info["duration"]) if info.get("duration") else None,
                    source="youtube",
                    channel="external",
                )
                imported_track_ids.append(track.id)
            except Exception:
                failed += 1
            finally:
                if mp3_path:
                    cleanup_file(mp3_path)

        if idx % 2 == 0 or idx == len(tracks):
            eta = _calc_eta(started_at, idx, len(tracks))
            try:
                await status.edit_text(
                    "⏳ Импорт чарта в плейлист\n"
                    f"Скачано: {downloaded} · Ошибок: {failed}\n\n"
                    f"ETA: {_fmt_eta(eta)}\n"
                    f"[{_bar(idx, len(tracks))}] {idx}/{len(tracks)}",
                    reply_markup=_bulk_kb(job_id),
                )
            except Exception:
                pass

    _chart_cancel_jobs.discard(job_id)

    if cancelled:
        added_partial = await _append_to_chart_playlist(user.id, playlist_name, imported_track_ids)
        if added_partial is None:
            await status.edit_text("⚠️ Достигнут лимит плейлистов (20). Удали один и повтори.")
            return

        resume_token = secrets.token_urlsafe(8)
        resume_payload = {
            "user_id": user.id,
            "src": callback_data.src,
            "sid": callback_data.sid,
            "total_limit": limit,
            "next_index": next_index,
            "playlist_name": playlist_name,
            "downloaded": downloaded,
            "failed": failed,
        }
        try:
            await cache.redis.setex(
                f"chart:resume:{resume_token}",
                3600,
                json.dumps(resume_payload, ensure_ascii=False),
            )
        except Exception:
            resume_token = ""

        resume_kb = None
        if resume_token:
            resume_kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="▶ Продолжить импорт",
                        callback_data=ChartBulkResume(token=resume_token).pack(),
                    )
                ]]
            )

        try:
            await status.edit_text(
                "⏹ Импорт чарта остановлен пользователем\n\n"
                f"Успешно скачано: <b>{downloaded}</b>\n"
                f"Добавлено в плейлист: <b>{added_partial}</b>\n"
                f"Ошибок: <b>{failed}</b>",
                parse_mode="HTML",
                reply_markup=resume_kb,
            )
        except Exception:
            pass
        return

    added = await _append_to_chart_playlist(user.id, playlist_name, imported_track_ids)
    if added is None:
        await status.edit_text("⚠️ Достигнут лимит плейлистов (20). Удали один и повтори.")
        return

    await status.edit_text(
        "✅ Импорт чарта завершён\n\n"
        f"Плейлист: <b>{playlist_name}</b>\n"
        f"Скачано: <b>{downloaded}</b>\n"
        f"Добавлено в плейлист: <b>{added}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.callback_query(ChartBulkCtl.filter())
async def handle_chart_bulk_cancel(callback: CallbackQuery, callback_data: ChartBulkCtl) -> None:
    _chart_cancel_jobs.add(callback_data.job)
    await callback.answer("Останавливаю импорт...", show_alert=False)


@router.callback_query(ChartBulkResume.filter())
async def handle_chart_bulk_resume(callback: CallbackQuery, callback_data: ChartBulkResume) -> None:
    await callback.answer("⏳ Продолжаю импорт...")

    raw_resume = await cache.redis.get(f"chart:resume:{callback_data.token}")
    if not raw_resume:
        await callback.message.answer("Сессия продолжения истекла. Запусти импорт заново из чарта.")
        return

    try:
        payload = json.loads(raw_resume)
    except Exception:
        await callback.message.answer("Не удалось восстановить сессию. Запусти импорт заново.")
        return

    user = await get_or_create_user(callback.from_user)
    if int(payload.get("user_id", 0)) != user.id:
        await callback.answer("Эта сессия продолжения не твоя", show_alert=True)
        return

    sid = str(payload.get("sid", ""))
    src = str(payload.get("src", ""))
    start_index = int(payload.get("next_index", 0))
    total_limit = int(payload.get("total_limit", 0))
    playlist_name = str(payload.get("playlist_name", "Chart import"))
    downloaded = int(payload.get("downloaded", 0))
    failed = int(payload.get("failed", 0))

    raw_tracks = await cache.redis.get(f"search:{sid}")
    if not raw_tracks:
        await callback.message.answer("Сессия чарта истекла. Открой чарт заново.")
        return
    tracks_all = json.loads(raw_tracks)
    tracks = tracks_all[:total_limit] if total_limit > 0 else tracks_all
    if not tracks or start_index >= len(tracks):
        await callback.message.answer("Нечего продолжать — чарт уже обработан.")
        return

    try:
        bitrate = int(user.quality) if str(user.quality).isdigit() else 192
    except Exception:
        bitrate = 192
    if not user.is_premium:
        bitrate = min(bitrate, 192)

    job_id = secrets.token_urlsafe(6)
    status = await callback.message.answer(
        "⏳ Продолжение импорта чарта\n"
        f"Скачано: {downloaded} · Ошибок: {failed}\n\n"
        f"ETA: {_fmt_eta(None)}\n"
        f"[{_bar(start_index, len(tracks))}] {start_index}/{len(tracks)}",
        reply_markup=_bulk_kb(job_id),
    )
    started_at = time.monotonic()

    imported_track_ids: list[int] = []
    cancelled = False
    next_index = start_index

    for idx, tr in enumerate(tracks[start_index:], start_index + 1):
        if job_id in _chart_cancel_jobs:
            cancelled = True
            next_index = idx - 1
            break

        query = tr.get("query") or f"{tr.get('artist', '')} {tr.get('title', '')}".strip()
        video_id = tr.get("video_id") or ""
        info = None

        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            info = {
                "video_id": video_id,
                "title": tr.get("title") or "Unknown",
                "uploader": tr.get("artist") or "Unknown",
                "duration": None,
            }
        else:
            found = await search_tracks(query, max_results=1, source="youtube")
            if found:
                info = found[0]

        if not info:
            failed += 1
        else:
            mp3_path = None
            try:
                mp3_path = await download_track(
                    info["video_id"],
                    bitrate=bitrate,
                    dl_id=uuid.uuid4().hex[:8],
                )
                downloaded += 1
                track = await upsert_track(
                    source_id=info["video_id"],
                    title=info.get("title"),
                    artist=info.get("uploader"),
                    duration=int(info["duration"]) if info.get("duration") else None,
                    source="youtube",
                    channel="external",
                )
                imported_track_ids.append(track.id)
            except Exception:
                failed += 1
            finally:
                if mp3_path:
                    cleanup_file(mp3_path)

        if idx % 2 == 0 or idx == len(tracks):
            eta = _calc_eta(started_at, idx, len(tracks), base_done=start_index)
            try:
                await status.edit_text(
                    "⏳ Продолжение импорта чарта\n"
                    f"Скачано: {downloaded} · Ошибок: {failed}\n\n"
                    f"ETA: {_fmt_eta(eta)}\n"
                    f"[{_bar(idx, len(tracks))}] {idx}/{len(tracks)}",
                    reply_markup=_bulk_kb(job_id),
                )
            except Exception:
                pass

    _chart_cancel_jobs.discard(job_id)

    if cancelled:
        added_partial = await _append_to_chart_playlist(user.id, playlist_name, imported_track_ids)
        if added_partial is None:
            await status.edit_text("⚠️ Достигнут лимит плейлистов (20). Удали один и повтори.")
            return

        new_token = secrets.token_urlsafe(8)
        resume_payload = {
            "user_id": user.id,
            "src": src,
            "sid": sid,
            "total_limit": len(tracks),
            "next_index": next_index,
            "playlist_name": playlist_name,
            "downloaded": downloaded,
            "failed": failed,
        }
        try:
            await cache.redis.setex(
                f"chart:resume:{new_token}",
                3600,
                json.dumps(resume_payload, ensure_ascii=False),
            )
            resume_kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="▶ Продолжить импорт",
                        callback_data=ChartBulkResume(token=new_token).pack(),
                    )
                ]]
            )
        except Exception:
            resume_kb = None

        await status.edit_text(
            "⏹ Импорт чарта остановлен пользователем\n\n"
            f"Успешно скачано: <b>{downloaded}</b>\n"
            f"Добавлено в плейлист: <b>{added_partial}</b>\n"
            f"Ошибок: <b>{failed}</b>",
            parse_mode="HTML",
            reply_markup=resume_kb,
        )
        return

    added = await _append_to_chart_playlist(user.id, playlist_name, imported_track_ids)
    if added is None:
        await status.edit_text("⚠️ Достигнут лимит плейлистов (20). Удали один и повтори.")
        return

    try:
        await cache.redis.delete(f"chart:resume:{callback_data.token}")
    except Exception:
        pass

    await status.edit_text(
        "✅ Импорт чарта завершён\n\n"
        f"Плейлист: <b>{playlist_name}</b>\n"
        f"Скачано: <b>{downloaded}</b>\n"
        f"Добавлено в плейлист: <b>{added}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    await callback.answer()
