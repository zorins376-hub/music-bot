import asyncio
import logging

from aiogram import Router
from aiogram.types import InlineQueryResultArticle, InlineQueryResultCachedAudio, InputTextMessageContent, InlineQuery

from bot.db import search_local_tracks
from bot.services.downloader import search_tracks
from bot.services.yandex_provider import search_yandex
from bot.services.cache import cache
from bot.services.search_engine import deduplicate_results
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()

    if not query:
        await inline_query.answer([], cache_time=1)
        return

    # TASK-011: Search local DB + Yandex + YouTube in parallel
    async def _search_local():
        try:
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
                }
                for tr in tracks
            ]
        except Exception:
            return []

    async def _search_ym():
        try:
            return await asyncio.wait_for(search_yandex(query, limit=5), timeout=5)
        except Exception:
            return []

    async def _search_yt():
        try:
            return await asyncio.wait_for(search_tracks(query, max_results=5), timeout=5)
        except Exception:
            return []

    local_res, ym_res, yt_res = await asyncio.gather(
        _search_local(), _search_ym(), _search_yt()
    )

    all_results = (local_res or []) + (ym_res or []) + (yt_res or [])
    results_data = deduplicate_results(all_results)[:5]

    results = []
    for track in results_data:
        video_id = track["video_id"]

        # Use file_id from track dict (local DB) or Redis cache
        fid = track.get("file_id") or await cache.get_file_id(video_id)
        if fid:
            results.append(
                InlineQueryResultCachedAudio(
                    id=video_id,
                    audio_file_id=fid,
                )
            )
        else:
            results.append(
                InlineQueryResultArticle(
                    id=video_id,
                    title=f"♪ {track['uploader']} — {track['title']}",
                    description=f"◷ {track.get('duration_fmt', '?:??')} · Нажми чтобы получить в личке бота",
                    input_message_content=InputTextMessageContent(
                        message_text=f"♪ {track['uploader']} — {track['title']} ({track.get('duration_fmt', '?:??')})\n\n"
                                     f"Открой бота в личных сообщениях и отправь этот запрос:\n"
                                     f"<code>{track['uploader']} {track['title']}</code>",
                        parse_mode="HTML",
                    ),
                )
            )

    await inline_query.answer(results, cache_time=60)
