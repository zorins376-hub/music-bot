"""
channel_parser.py — Pyrogram userbot парсер каналов TEQUILA и FULLMOON (v1.1).

Что делает:
  - Подключается к Telegram как userbot (аккаунт пользователя)
  - Мониторит новые посты в TEQUILA_CHANNEL и FULLMOON_CHANNEL
  - Извлекает аудио-файлы, сохраняет file_id в БД
  - Добавляет треки в очередь эфира (Redis)

Для запуска нужно:
  1. PYROGRAM_API_ID, PYROGRAM_API_HASH в .env
  2. PYROGRAM_SESSION_STRING (получить: python -m parser.generate_session)
  3. TEQUILA_CHANNEL, FULLMOON_CHANNEL в .env
  4. Раскомментировать parser service в docker-compose.yml
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        from pyrogram import Client, filters
        from pyrogram.types import Message as PyroMessage
    except ImportError:
        logger.error("pyrogram не установлен. Добавьте в requirements.txt.")
        return

    from bot.config import settings
    from bot.db import upsert_track
    from bot.services.cache import cache

    if not settings.PYROGRAM_SESSION_STRING:
        logger.error("PYROGRAM_SESSION_STRING не задан в .env")
        return

    app = Client(
        "parser",
        api_id=settings.PYROGRAM_API_ID,
        api_hash=settings.PYROGRAM_API_HASH,
        session_string=settings.PYROGRAM_SESSION_STRING,
    )

    channels = {
        settings.TEQUILA_CHANNEL: "tequila",
        settings.FULLMOON_CHANNEL: "fullmoon",
    }
    channel_ids = {ch for ch in channels if ch}

    @app.on_message(filters.channel & filters.audio)
    async def handle_audio(client: Client, message: PyroMessage) -> None:
        chat_username = f"@{message.chat.username}" if message.chat.username else str(message.chat.id)
        channel_label = channels.get(chat_username, "external")

        audio = message.audio
        if not audio:
            return

        source_id = f"tg_{message.chat.id}_{message.id}"
        title = audio.title or audio.file_name or "Unknown"
        artist = audio.performer or ""

        logger.info("[%s] New track: %s — %s", channel_label, artist, title)

        track = await upsert_track(
            source_id=source_id,
            title=title,
            artist=artist,
            duration=audio.duration,
            file_id=audio.file_id,
            source="channel",
            channel=channel_label,
        )

        # Добавить в очередь эфира
        queue_key = f"radio:queue:{channel_label}"
        await cache.redis.rpush(
            queue_key,
            json.dumps({
                "track_id": track.id,
                "file_id": audio.file_id,
                "title": title,
                "artist": artist,
                "duration": audio.duration,
            }),
        )
        logger.info("[%s] Added to queue: %s — %s", channel_label, artist, title)

    logger.info("Parser started. Watching: %s", list(channel_ids))
    await app.start()
    await asyncio.Event().wait()  # run forever
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
