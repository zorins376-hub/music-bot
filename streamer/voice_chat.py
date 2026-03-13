"""
voice_chat.py — Pyrogram + pytgcalls стример для BLACK ROOM NIGHT CHAT (v2.0).

Что делает:
  - Подключается к Voice Chat одной или нескольких групп
  - Берёт треки из очереди Redis (radio:queue:tequila / fullmoon)
  - Стримит 24/7 с автоматическим переключением треков
  - Обновляет Redis ключ radio:current:{channel} для отображения текущего трека
  - Голосование 👍/👎 — при N 👎 автоматический skip

Для запуска:
  1. Все Pyrogram настройки в .env
  2. BLACKROOM_GROUP_ID (или через запятую несколько ID) в .env
  3. Раскомментировать streamer service в docker-compose.yml
"""
import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Local file cache for stutter-free playback ────────────────────────────
_STREAM_CACHE = Path("/tmp/music_bot_stream")
_STREAM_CACHE.mkdir(parents=True, exist_ok=True)
_prev_local: dict[int, str] = {}  # group_id → previous local file (for cleanup)


async def _ensure_local(app, file_id: str) -> str:
    """Download track to local disk if it's a Telegram file_id.

    Returns a path usable by AudioPiped.  Falls back to *file_id* itself
    when download is impossible (e.g. raw URL, already-local path).
    """
    if Path(file_id).exists():
        return file_id
    tag = hashlib.md5(file_id.encode()).hexdigest()[:16]
    local = _STREAM_CACHE / f"{tag}.ogg"
    if local.exists():
        return str(local)
    try:
        result = await app.download_media(file_id, file_name=str(local))
        if result:
            return str(result)
    except Exception as e:
        logger.warning("Pre-download failed (%s), using direct stream", e)
    return file_id


def _cleanup_prev(group_id: int) -> None:
    prev = _prev_local.pop(group_id, None)
    if prev:
        try:
            Path(prev).unlink(missing_ok=True)
        except Exception:
            pass


# Voting: {group_id: {"likes": set(user_ids), "dislikes": set(user_ids)}}
_votes: dict[int, dict[str, set[int]]] = defaultdict(lambda: {"likes": set(), "dislikes": set()})
_SKIP_THRESHOLD = 3  # number of 👎 to auto-skip


def _reset_votes(group_id: int) -> None:
    _votes[group_id] = {"likes": set(), "dislikes": set()}


async def vote(group_id: int, user_id: int, vote_type: str, skip_cb=None) -> dict:
    """Register a vote. Returns current tally. Calls skip_cb() if threshold met."""
    v = _votes[group_id]
    if vote_type == "like":
        v["likes"].add(user_id)
        v["dislikes"].discard(user_id)
    elif vote_type == "dislike":
        v["dislikes"].add(user_id)
        v["likes"].discard(user_id)

    tally = {"likes": len(v["likes"]), "dislikes": len(v["dislikes"])}

    if len(v["dislikes"]) >= _SKIP_THRESHOLD and skip_cb:
        _reset_votes(group_id)
        await skip_cb()

    return tally


async def _run_group(app, tgcalls, group_id: int, cache) -> None:
    """Run streaming for a single group."""

    async def get_next_track(channel: str = "tequila") -> dict | None:
        for ch in (channel, "fullmoon", "tequila"):
            data = await cache.redis.lpop(f"radio:queue:{ch}")
            if data:
                return json.loads(data)
        return None

    async def play_next() -> None:
        from pytgcalls.types import AudioPiped, AudioQuality

        track = await get_next_track()
        if not track:
            logger.info("Queue empty for group %s, waiting...", group_id)
            await asyncio.sleep(10)
            return

        _reset_votes(group_id)
        channel_label = track.get("channel", "tequila")
        logger.info("[%s] Playing: %s — %s", group_id, track.get("artist"), track.get("title"))

        await cache.redis.setex(
            f"radio:current:{channel_label}",
            track.get("duration", 300) + 30,
            json.dumps(track),
        )

        try:
            _cleanup_prev(group_id)
            local_path = await _ensure_local(app, track["file_id"])
            if local_path != track["file_id"]:
                _prev_local[group_id] = local_path

            await tgcalls.play(
                group_id,
                AudioPiped(
                    local_path,
                    audio_parameters=AudioQuality.MEDIUM,
                ),
            )
        except Exception as e:
            logger.error("[%s] Playback error: %s", group_id, e)

    @tgcalls.on_stream_end()
    async def on_stream_end(_, update):
        chat_id = getattr(update, "chat_id", group_id)
        _reset_votes(chat_id)
        await play_next()

    # Register vote handler via Pyrogram
    from pyrogram import filters

    @app.on_message(filters.chat(group_id) & filters.command(["like", "dislike", "vote"]))
    async def on_vote(_, message):
        cmd = message.command[0].lower() if message.command else ""
        if cmd == "like":
            vtype = "like"
        elif cmd == "dislike":
            vtype = "dislike"
        else:
            # /vote like or /vote dislike
            vtype = message.command[1].lower() if len(message.command) > 1 else "like"

        tally = await vote(group_id, message.from_user.id, vtype, skip_cb=play_next)
        await message.reply_text(
            f"👍 {tally['likes']}  👎 {tally['dislikes']}"
            + (f"  (skip at {_SKIP_THRESHOLD} 👎)" if tally["dislikes"] > 0 else ""),
            quote=True,
        )

    await play_next()
    logger.info("Streamer started for group %s", group_id)


async def main() -> None:
    try:
        from pyrogram import Client
        from pytgcalls import PyTgCalls
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

    # Support multiple group IDs separated by commas
    raw_ids = str(settings.BLACKROOM_GROUP_ID)
    group_ids = [int(gid.strip()) for gid in raw_ids.split(",") if gid.strip()]

    await app.start()
    await tgcalls.start()

    tasks = [_run_group(app, tgcalls, gid, cache) for gid in group_ids]
    logger.info("Launching streamer for %d group(s): %s", len(group_ids), group_ids)

    await asyncio.gather(*tasks)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    asyncio.run(main())
