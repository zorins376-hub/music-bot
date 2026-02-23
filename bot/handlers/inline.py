import logging

from aiogram import Router
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, InlineQuery

from bot.services.downloader import search_tracks
from bot.services.cache import cache

logger = logging.getLogger(__name__)

router = Router()


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()

    if not query:
        await inline_query.answer([], cache_time=1)
        return

    results_data = await search_tracks(query, max_results=5)

    results = []
    for track in results_data:
        video_id = track["video_id"]

        # Если трек уже кэширован — используем cached audio
        file_id = await cache.get_file_id(video_id)
        if file_id:
            from aiogram.types import InlineQueryResultCachedAudio
            results.append(
                InlineQueryResultCachedAudio(
                    id=video_id,
                    audio_file_id=file_id,
                )
            )
        else:
            # Возвращаем статью — пользователь может открыть бота в личке
            results.append(
                InlineQueryResultArticle(
                    id=video_id,
                    title=f"♪ {track['uploader']} — {track['title']}",
                    description=f"◷ {track['duration_fmt']} · Нажми чтобы получить в личке бота",
                    input_message_content=InputTextMessageContent(
                        message_text=f"♪ {track['uploader']} — {track['title']} ({track['duration_fmt']})\n\n"
                                     f"Открой бота в личных сообщениях и отправь этот запрос:\n"
                                     f"<code>{track['uploader']} {track['title']}</code>",
                        parse_mode="HTML",
                    ),
                )
            )

    await inline_query.answer(results, cache_time=60)
