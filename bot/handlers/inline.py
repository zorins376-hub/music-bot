import asyncio
import base64
import logging

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
)

from bot.db import search_local_tracks
from bot.services.downloader import search_tracks
from bot.services.yandex_provider import search_yandex
from bot.services.spotify_provider import search_spotify
from bot.services.vk_provider import search_vk
from bot.services.cache import cache
from bot.services.search_engine import deduplicate_results, detect_script
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()

_SOURCE_ICON = {
    "yandex": "🟡",
    "spotify": "🟢",
    "vk": "🔵",
    "soundcloud": "🟠",
    "youtube": "▶️",
    "channel": "📁",
}


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()

    if not query:
        await inline_query.answer([], cache_time=1)
        return

    # D-01: Search local DB + Yandex + Spotify + VK + YouTube in parallel
    async def _safe(coro):
        try:
            return await asyncio.wait_for(coro, timeout=5)
        except Exception:
            return []

    async def _search_local():
        tracks = await search_local_tracks(query, limit=5)
        return [
            {
                "video_id": tr.source_id,
                "title": tr.title or "Unknown",
                "uploader": tr.artist or "Unknown",
                "duration": tr.duration or 0,
                "duration_fmt": fmt_duration(tr.duration) if tr.duration else "?:??",
                "source": tr.source or "channel",
                "file_id": tr.file_id,
                "_provider_pos": i,
            }
            for i, tr in enumerate(tracks)
        ]

    local_res, ym_res, sp_res, vk_res, yt_res = await asyncio.gather(
        _safe(_search_local()),
        _safe(search_yandex(query, limit=5)),
        _safe(search_spotify(query, limit=3)),
        _safe(search_vk(query, limit=3)),
        _safe(search_tracks(query, max_results=5)),
        return_exceptions=True,
    )

    all_results = []
    for r in (local_res, ym_res, sp_res, vk_res, yt_res):
        if isinstance(r, BaseException) or r is None:
            continue
        # Stamp provider position so ranking preserves provider relevance order
        for i, track in enumerate(r):
            track["_provider_pos"] = i
        all_results.extend(r)
    script = detect_script(query)
    results_data = deduplicate_results(all_results, lang_hint=script, query=query)[:10]

    # D-02: Build deep-link URL for non-cached tracks
    bot_me = await inline_query.bot.me()
    bot_username = bot_me.username or "bot"

    results = []
    for track in results_data:
        video_id = track["video_id"]
        source = track.get("source", "youtube")
        icon = _SOURCE_ICON.get(source, "♪")

        # Use file_id from track dict (local DB) or Redis cache or DB fallback
        fid = track.get("file_id") or await cache.get_file_id(video_id)
        if not fid:
            try:
                from bot.services.telegram_cache import get_file_id as _tg_get_fid
                fid = await _tg_get_fid(video_id)
            except Exception:
                pass
        if fid:
            results.append(
                InlineQueryResultCachedAudio(
                    id=video_id[:64],
                    audio_file_id=fid,
                )
            )
        else:
            # D-02: deep-link button → opens bot DM and auto-searches
            dl_query = f"{track['uploader']} {track['title']}"
            b64 = base64.urlsafe_b64encode(dl_query.encode()).decode().rstrip("=")
            deep_link = f"https://t.me/{bot_username}?start=s_{b64}"
            # D-03: WebApp link → opens mini app with track pre-loaded
            webapp_link = f"https://t.me/{bot_username}/app?startapp=play_{video_id}"
            results.append(
                InlineQueryResultArticle(
                    id=video_id[:64],
                    title=f"{icon} {track['uploader']} — {track['title']}",
                    description=f"◷ {track.get('duration_fmt', '?:??')} · {source}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"{icon} <b>{track['uploader']}</b> — {track['title']} ({track.get('duration_fmt', '?:??')})",
                        parse_mode="HTML",
                    ),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="▶ Слушать", url=webapp_link),
                            InlineKeyboardButton(text="Скачать", url=deep_link),
                        ]
                    ]),
                )
            )

    await inline_query.answer(results, cache_time=60)
