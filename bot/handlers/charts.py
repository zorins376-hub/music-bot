"""Top charts: Shazam · YouTube · VK — paginated lists with download."""

import asyncio
import json
import logging
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

async def _fetch_shazam() -> list[dict]:
    """Fetch Shazam Top 200 (world) via public discovery API."""
    # Primary: Shazam discovery API (more reliable)
    urls = [
        "https://www.shazam.com/services/charts/v1/top/world?pageSize=50&startFrom=0",
        "https://www.shazam.com/services/charts/v1/top/RU?pageSize=50&startFrom=0",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for url in urls:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning("Shazam API %s returned %s", url, resp.status)
                        continue
                    data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("Shazam fetch error (%s): %s", url, e)
            continue

        tracks = []
        # Try multiple response formats
        chart = data.get("chart") or data.get("tracks") or data.get("data") or []
        for item in chart[:50]:
            # Format 1: heading.title / heading.subtitle
            heading = item.get("heading", {})
            title = heading.get("title") or item.get("title") or item.get("track", "Unknown")
            artist = heading.get("subtitle") or item.get("subtitle") or item.get("artist", "Unknown")
            if title != "Unknown":
                tracks.append({
                    "title": title,
                    "artist": artist,
                    "query": f"{artist} - {title}",
                })
        if tracks:
            return tracks

    # Fallback: use yt-dlp to fetch Shazam Top 50 playlist from YouTube
    logger.info("Shazam API failed, falling back to YouTube playlist")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_shazam_yt_fallback)


def _fetch_shazam_yt_fallback() -> list[dict]:
    """Fetch Shazam Top 50 via YouTube search for Shazam playlist."""
    import yt_dlp
    from bot.services.downloader import _base_opts

    # Search for top Shazam songs
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch50",
        "socket_timeout": 15,
        **_base_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("Shazam Top 50 2026", download=False)
            entries = info.get("entries", []) if info else []
    except Exception as e:
        logger.error("Shazam YT fallback error: %s", e)
        return []

    tracks = []
    for entry in entries[:50]:
        if not entry:
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
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
            "video_id": entry.get("id", ""),
        })
    return tracks


def _fetch_youtube_sync() -> list[dict]:
    """Fetch YouTube Music Global Top 100 via yt-dlp (sync, runs in thread)."""
    import yt_dlp
    from bot.services.downloader import _base_opts

    playlist_url = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "playlistend": 50,
        **_base_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            entries = info.get("entries", []) if info else []
    except Exception as e:
        logger.error("YouTube chart fetch error: %s", e)
        return []

    tracks = []
    for entry in entries:
        if not entry:
            continue
        raw_title = entry.get("title", "Unknown")
        uploader = entry.get("uploader") or entry.get("channel") or ""
        # Try to split "Artist - Title"
        for sep in (" — ", " – ", " - "):
            if sep in raw_title:
                parts = raw_title.split(sep, 1)
                artist, title = parts[0].strip(), parts[1].strip()
                break
        else:
            artist, title = uploader, raw_title
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
            "video_id": entry.get("id", ""),
        })
    return tracks


async def _fetch_youtube() -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_youtube_sync)


async def _fetch_vk() -> list[dict]:
    """Fetch Russian/CIS music chart via yt-dlp YouTube search."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_ytdl_pool, _fetch_russia_sync)


def _fetch_russia_sync() -> list[dict]:
    """Fetch trending Russian music via yt-dlp search."""
    import yt_dlp
    from bot.services.downloader import _base_opts

    # Try multiple known Russian chart playlists
    playlist_urls = [
        # YouTube Music Top Songs - Russia
        "https://www.youtube.com/playlist?list=PLw-VjHDlEOgtYfGcmRbz3PS1MKx31KP-9",
        # Trending music Russia
        "https://www.youtube.com/playlist?list=PLw-VjHDlEOgs658kAHR_LAaILBXb-s6Q5",
    ]

    for playlist_url in playlist_urls:
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "playlistend": 50,
            **_base_opts(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                entries = info.get("entries", []) if info else []
                if entries:
                    break
        except Exception as e:
            logger.warning("Russia chart playlist %s failed: %s", playlist_url, e)
            entries = []

    if not entries:
        # Last resort: search for trending Russian music
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch50",
            "socket_timeout": 15,
            **_base_opts(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info("русский хит чарт 2026 топ", download=False)
                entries = info.get("entries", []) if info else []
        except Exception as e:
            logger.error("Russia chart search fallback error: %s", e)
            return []

    tracks = []
    for entry in entries[:50]:
        if not entry:
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
        tracks.append({
            "title": title,
            "artist": artist,
            "query": f"{artist} - {title}",
            "video_id": entry.get("id", ""),
        })
    return tracks


_CHART_FETCHERS = {
    "shazam": _fetch_shazam,
    "youtube": _fetch_youtube,
    "vk": _fetch_vk,
}

_CHART_LABELS = {
    "shazam": "🎵 Shazam Top 50",
    "youtube": "▶ YouTube Music Top 50",
    "vk": "🇷🇺 Топ Россия",
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
        [InlineKeyboardButton(text="🎵 Shazam Top 50", callback_data=ChartCb(src="shazam", p=0).pack())],
        [InlineKeyboardButton(text="▶ YouTube Music Top", callback_data=ChartCb(src="youtube", p=0).pack())],
        [InlineKeyboardButton(text="🇷🇺 Топ Россия", callback_data=ChartCb(src="vk", p=0).pack())],
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
