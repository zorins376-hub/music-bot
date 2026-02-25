"""Top charts: Shazam · YouTube · VK — paginated lists with download."""

import asyncio
import json
import logging
import re
import secrets
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
from bot.i18n import t
from bot.services.cache import cache

logger = logging.getLogger(__name__)
router = Router()

_LOGO = "◉ <b>BLACK ROOM</b>"
_PER_PAGE = 5
_CHART_TTL = 6 * 3600  # 6 hours cache

_ytdl_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chart")


# ── Callback Data ────────────────────────────────────────────────────────

class ChartCb(CallbackData, prefix="ch"):
    src: str   # shazam / youtube / vk
    p: int     # page (0-based)


class ChartDl(CallbackData, prefix="cd"):
    sid: str   # session id
    i: int     # track index


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
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
            "video_id": entry.get("id", ""),
        })
    return tracks


async def _fetch_apple_chart(storefront: str) -> list[dict]:
    """Fetch Apple Music most-played chart (individual songs, ranked).
    storefront: 'us' for Global, 'ru' for Russia, etc."""
    url = f"https://rss.applemonitoring.com/api/v2/{storefront}/music/most-played/100/songs.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("Apple Music RSS %s returned %s", storefront, resp.status)
                    return []
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.error("Apple Music RSS error (%s): %s", storefront, e)
        return []

    results = data.get("feed", {}).get("results", [])
    tracks = []
    for item in results[:50]:
        artist = item.get("artistName", "Unknown")
        title = item.get("name", "Unknown")
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
        })
    return tracks


def _fetch_yt_playlist_sync(playlist_urls: list[str], max_tracks: int = 50, cyrillic_only: bool = False) -> list[dict]:
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
                entries = info.get("entries", []) if info else []
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
    try:
        from yandex_music import ClientAsync
    except ImportError:
        logger.warning("yandex-music package not installed")
        return []

    from bot.config import settings
    token = settings.YANDEX_MUSIC_TOKEN or None
    try:
        client = await ClientAsync(token).init()
        # chart() returns ChartInfo; chart("russia") for Russian chart
        chart_info = await client.chart("russia")
        if not chart_info or not getattr(chart_info, "chart", None):
            return []

        tracks = []
        for item in (chart_info.chart.tracks or [])[:50]:
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
            tracks.append({
                "title": title,
                "artist": artist,
                "query": f"{artist} - {title}",
            })
        return tracks
    except Exception as e:
        logger.error("Яндекс Музыка chart error: %s", e)
        return []


async def _fetch_html(url: str, headers: dict) -> str:
    """Fetch HTML from URL, return empty string on failure."""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("HTTP %s for %s", resp.status, url)
                    return ""
                return await resp.text()
    except Exception as e:
        logger.warning("Fetch error %s: %s", url, e)
        return ""


def _parse_rusradio_tracks(html: str) -> list[dict]:
    """
    Try multiple HTML parsing strategies for rusradio.ru charts.
    Strategy 1: track card blocks (current chart layout).
    Strategy 2: JSON-LD structured data.
    Strategy 3: legacy voting page (seasonal Золотой Граммофон).
    """
    tracks: list[dict] = []
    seen: set[str] = set()

    def _add(artist: str, title: str) -> bool:
        artist = artist.strip()
        title = title.strip()
        if not artist or not title:
            return False
        if len(artist) > 80 or len(title) > 80:
            return False
        key = f"{artist.lower()}\t{title.lower()}"
        if key in seen:
            return False
        seen.add(key)
        tracks.append({"title": title, "artist": artist, "query": f"{artist} - {title}"})
        return True

    # Strategy 1: JSON-LD (most reliable if present)
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                              html, re.DOTALL | re.IGNORECASE):
        try:
            obj = json.loads(match.group(1))
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if isinstance(item, dict) and item.get("@type") in ("MusicRecording", "Song"):
                    artist = item.get("byArtist", {})
                    if isinstance(artist, dict):
                        artist = artist.get("name", "")
                    title = item.get("name", "")
                    _add(str(artist), str(title))
        except Exception:
            pass

    if tracks:
        return tracks

    # Strategy 2: track/song card blocks — look for data-* or class="*track*" patterns
    # rusradio.ru uses blocks like: <div class="chart__item"> ... artist ... title ...
    card_re = re.compile(
        r'class="[^"]*(?:chart|track|song|music)[^"]*"[^>]*>(.*?)</(?:div|article|li)>',
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
        for i in range(len(lines) - 1):
            for sep in (" — ", " – ", " - "):
                combined = f"{lines[i]}{sep}{lines[i+1]}"
                if _has_cyrillic(combined):
                    _add(lines[i], lines[i + 1])
                    break
        if len(tracks) >= 50:
            break

    if tracks:
        return tracks

    # Strategy 3: generic separator parsing (artist — title appearing anywhere in text)
    sep_re = re.compile(
        r'(?:^|>)([А-ЯЁA-Z][^\n<>—–\-]{1,40})\s*[—–]\s*([^\n<>—–]{2,60})(?:$|<)',
        re.MULTILINE,
    )
    for m in sep_re.finditer(html):
        artist, title = m.group(1).strip(), m.group(2).strip()
        if _has_cyrillic(artist) or _has_cyrillic(title):
            _add(artist, title)
        if len(tracks) >= 50:
            break

    if tracks:
        return tracks

    # Strategy 4: legacy voting page (seasonal Золотой Граммофон)
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
            _add(lines[1], lines[0])  # page order: title then artist
        if len(tracks) >= 50:
            break

    return tracks


async def _fetch_rusradio() -> list[dict]:
    """Русское Радио — TOP чарт (Золотой Граммофон / TOP-20)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Try primary chart URLs in order of preference
    chart_urls = [
        "https://rusradio.ru/music/chart/",
        "https://rusradio.ru/charts/top-20/",
        "https://rusradio.ru/charts/",
        "https://rusradio.ru/charts/golosujte-za-treki",
    ]
    for url in chart_urls:
        html = await _fetch_html(url, headers)
        if not html:
            continue
        tracks = _parse_rusradio_tracks(html)
        if tracks:
            logger.info("Rusradio chart: %d tracks from %s", len(tracks), url)
            return tracks
        logger.debug("Rusradio: no tracks parsed from %s", url)

    logger.warning("Rusradio chart: all URLs failed, using fallback")

    # Fallback 1: Яндекс Музыка чарт Россия (already works for VK chart)
    yandex_tracks = await _fetch_yandex_chart()
    if yandex_tracks:
        return yandex_tracks

    # Fallback 2: Apple Music Russia + Cyrillic filter
    apple_tracks = await _fetch_apple_chart("ru")
    if apple_tracks:
        ru_tracks = [t for t in apple_tracks if _has_cyrillic(t["artist"]) or _has_cyrillic(t["title"])]
        if ru_tracks:
            return ru_tracks[:30]

    return []


async def _fetch_europa() -> list[dict]:
    """Европа Плюс TOP40 — Apple Music Europe (gb→de→us) chart."""
    for storefront in ("gb", "de", "us"):
        tracks = await _fetch_apple_chart(storefront)
        if tracks:
            return tracks
    return []


_CHART_FETCHERS = {
    "shazam": _fetch_shazam,
    "youtube": _fetch_youtube,
    "vk": _fetch_vk,
    "rusradio": _fetch_rusradio,
    "europa": _fetch_europa,
}

_CHART_LABELS = {
    "shazam": "🎵 Apple Music Global Top",
    "youtube": "▶ YouTube Music Top",
    "vk": "🇷🇺 Яндекс Топ Россия",
    "rusradio": "📻 Русское Радио — Золотой Граммофон",
    "europa": "🎶 Европа Плюс TOP40",
}


# ── Cache helpers ────────────────────────────────────────────────────────

async def _get_chart(source: str) -> list[dict]:
    """Get chart from Redis cache or fetch fresh."""
    key = f"chart:{source}"
    raw = await cache.redis.get(key)
    if raw:
        return json.loads(raw)

    fetcher = _CHART_FETCHERS.get(source)
    if not fetcher:
        return []
    tracks = await fetcher()
    if tracks:
        await cache.redis.setex(key, _CHART_TTL, json.dumps(tracks, ensure_ascii=False))
    return tracks


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


@router.callback_query(lambda c: c.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    await callback.answer()
