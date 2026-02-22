"""
voice_chat.py — Pyrogram + pytgcalls стример для BLACK ROOM NIGHT CHAT (v1.1).

Что делает:
  - Подключается к Voice Chat группы BLACK ROOM NIGHT CHAT
  - Берёт треки из очереди Redis (radio:queue:tequila / fullmoon)
  - Стримит 24/7 с автоматическим переключением треков
  - Обновляет Redis ключ radio:current:{channel} для отображения текущего трека

Для запуска:
  1. Все Pyrogram настройки в .env
  2. BLACKROOM_GROUP_ID в .env
  3. Раскомментировать streamer service в docker-compose.yml
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        from pyrogram import Client
        from pytgcalls import PyTgCalls
        from pytgcalls.types import AudioPiped, AudioQuality
    except ImportError:
        logger.error("Установи: pyrogram pytgcalls TgCrypto")
        return

    from bot.config import settings
    from bot.services.cache import cache

    if not settings.PYROGRAM_SESSION_STRING or not settings.BLACKROOM_GROUP_ID:
        logger.error("PYROGRAM_SESSION_STRING и BLACKROOM_GROUP_ID обязательны")
        return

    app = Client(
        "streamer",
        api_id=settings.PYROGRAM_API_ID,
        api_hash=settings.PYROGRAM_API_HASH,
        session_string=settings.PYROGRAM_SESSION_STRING,
    )
    tgcalls = PyTgCalls(app)
    group_id = settings.BLACKROOM_GROUP_ID

    async def get_next_track(channel: str = "tequila") -> dict | None:
        """Берёт следующий трек из Redis очереди."""
        for ch in (channel, "fullmoon", "tequila"):
            data = await cache.redis.lpop(f"radio:queue:{ch}")
            if data:
                return json.loads(data)
        return None

    async def play_next() -> None:
        track = await get_next_track()
        if not track:
            logger.info("Queue empty, waiting...")
            await asyncio.sleep(10)
            return

        channel_label = track.get("channel", "tequila")
        logger.info("Playing: %s — %s", track.get("artist"), track.get("title"))

        # Обновляем текущий трек в Redis
        await cache.redis.setex(
            f"radio:current:{channel_label}",
            track.get("duration", 300) + 30,
            json.dumps(track),
        )

        try:
            await tgcalls.play(
                group_id,
                AudioPiped(
                    track["file_id"],
                    audio_parameters=AudioQuality.HIGH,
                ),
            )
        except Exception as e:
            logger.error("Playback error: %s", e)

    @tgcalls.on_stream_end()
    async def on_stream_end(_, __) -> None:
        await play_next()

    await app.start()
    await tgcalls.start()
    await play_next()

    logger.info("Streamer started for group %s", group_id)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
