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
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

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


async def _sync_current_track_state(cache, track: dict | None, previous_channel: str | None) -> str | None:
    next_channel: str | None = None
    if track:
        next_channel = (track.get("channel") or "tequila").strip() or "tequila"

    if previous_channel and previous_channel != next_channel:
        await cache.redis.delete(f"radio:current:{previous_channel}")

    if not track:
        return None

    await cache.redis.setex(
        f"radio:current:{next_channel}",
        track.get("duration", 300) + 30,
        json.dumps(track),
    )
    return next_channel


async def _handle_radio_command(command: str, *, group_id: int, tgcalls, play_next, clear_current_track, cache) -> None:
    normalized = (command or "").strip().lower()
    if normalized == "skip":
        _reset_votes(group_id)
        await play_next()
        return

    if normalized == "pause":
        pause_stream = getattr(tgcalls, "pause_stream", None)
        if callable(pause_stream):
            await pause_stream(group_id)
        else:
            logger.warning("Pause command is not supported by the current tgcalls client")
        return

    if normalized == "stop":
        stop_stream = getattr(tgcalls, "leave_call", None)
        if callable(stop_stream):
            await stop_stream(group_id)
            await clear_current_track()
        else:
            logger.warning("Stop command is not supported by the current tgcalls client")
        return

    logger.debug("Ignoring unknown radio command: %s", normalized)


async def _listen_for_radio_commands(pubsub, *, group_id: int, tgcalls, play_next, clear_current_track, cache) -> None:
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            payload = message.get("data")
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="ignore")

            await _handle_radio_command(
                str(payload or ""),
                group_id=group_id,
                tgcalls=tgcalls,
                play_next=play_next,
                clear_current_track=clear_current_track,
                cache=cache,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Radio command listener crashed for group %s", group_id)
    finally:
        close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
        if callable(close):
            maybe_awaitable = close()
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable


async def _run_radio_command_listener(
    redis,
    *,
    group_id: int,
    tgcalls,
    play_next,
    clear_current_track,
    cache,
    reconnect_delay: float = 1.0,
) -> None:
    while True:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe("radio:cmd")
            await _listen_for_radio_commands(
                pubsub,
                group_id=group_id,
                tgcalls=tgcalls,
                play_next=play_next,
                clear_current_track=clear_current_track,
                cache=cache,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Radio command listener setup failed for group %s", group_id)

        await asyncio.sleep(reconnect_delay)


async def _run_group(app, tgcalls, group_id: int, cache, *, consume_radio_commands: bool = False) -> None:
    """Run streaming for a single group."""
    current_channel: str | None = None
    transition_lock = asyncio.Lock()
    transition_in_progress = False

    async def get_next_track(channel: str = "tequila") -> dict | None:
        preferred_channels: list[str] = []
        try:
            if await cache.redis.get("broadcast:live"):
                active_channel = await cache.redis.hget("broadcast:state", "channel")
                if active_channel:
                    preferred_channels.append(active_channel)
        except Exception:
            logger.debug("Failed to resolve active broadcast channel", exc_info=True)

        preferred_channels.extend((channel, "fullmoon", "tequila"))

        seen: set[str] = set()
        for raw_channel in preferred_channels:
            ch = (raw_channel or "").strip()
            if not ch or ch in seen:
                continue
            seen.add(ch)
            data = await cache.redis.lpop(f"radio:queue:{ch}")
            if data:
                return json.loads(data)
        return None

    async def play_next() -> None:
        nonlocal current_channel, transition_in_progress
        from pytgcalls.types import AudioPiped, AudioQuality

        if transition_in_progress:
            logger.debug("Transition already in progress for group %s; skipping duplicate trigger", group_id)
            return

        transition_in_progress = True

        try:
            async with transition_lock:
                while True:
                    track = await get_next_track()
                    if not track:
                        current_channel = await _sync_current_track_state(cache, None, current_channel)
                        logger.info("Queue empty for group %s, waiting...", group_id)
                        await asyncio.sleep(10)
                        return

                    _reset_votes(group_id)
                    channel_label = track.get("channel", "tequila")
                    logger.info("[%s] Playing: %s — %s", group_id, track.get("artist"), track.get("title"))
                    current_channel = await _sync_current_track_state(cache, track, current_channel)

                    try:
                        await tgcalls.play(
                            group_id,
                            AudioPiped(
                                track["file_id"],
                                audio_parameters=AudioQuality.HIGH,
                            ),
                        )
                        return
                    except Exception as e:
                        logger.error("[%s] Playback error for %s: %s", group_id, track.get("file_id"), e)
                        current_channel = await _sync_current_track_state(cache, None, current_channel)
        finally:
            transition_in_progress = False

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

    async def clear_current_track() -> None:
        nonlocal current_channel
        current_channel = await _sync_current_track_state(cache, None, current_channel)

    if consume_radio_commands:
        asyncio.create_task(
            _run_radio_command_listener(
                cache.redis,
                group_id=group_id,
                tgcalls=tgcalls,
                play_next=play_next,
                clear_current_track=clear_current_track,
                cache=cache,
                reconnect_delay=1.0,
            )
        )

    await play_next()
    logger.info("Streamer started for group %s", group_id)


async def _run_groups(app, tgcalls, group_ids: list[int], cache, *, consume_radio_commands: bool = False) -> None:
    """Run synchronized streaming across multiple groups using one shared queue consumer."""
    current_channel: str | None = None
    transition_lock = asyncio.Lock()
    transition_in_progress = False
    group_id_set = set(group_ids)

    def _reset_group_votes() -> None:
        for gid in group_ids:
            _reset_votes(gid)

    async def get_next_track(channel: str = "tequila") -> dict | None:
        preferred_channels: list[str] = []
        try:
            if await cache.redis.get("broadcast:live"):
                active_channel = await cache.redis.hget("broadcast:state", "channel")
                if active_channel:
                    preferred_channels.append(active_channel)
        except Exception:
            logger.debug("Failed to resolve active broadcast channel", exc_info=True)

        preferred_channels.extend((channel, "fullmoon", "tequila"))

        seen: set[str] = set()
        for raw_channel in preferred_channels:
            ch = (raw_channel or "").strip()
            if not ch or ch in seen:
                continue
            seen.add(ch)
            data = await cache.redis.lpop(f"radio:queue:{ch}")
            if data:
                return json.loads(data)
        return None

    async def play_next() -> None:
        nonlocal current_channel, transition_in_progress
        from pytgcalls.types import AudioPiped, AudioQuality

        if transition_in_progress:
            logger.debug("Transition already in progress for groups %s; skipping duplicate trigger", group_ids)
            return

        transition_in_progress = True
        try:
            async with transition_lock:
                while True:
                    track = await get_next_track()
                    if not track:
                        current_channel = await _sync_current_track_state(cache, None, current_channel)
                        logger.info("Queue empty for groups %s, waiting...", group_ids)
                        await asyncio.sleep(10)
                        return

                    _reset_group_votes()
                    logger.info("[%s] Broadcasting to %d groups: %s — %s", group_ids[0], len(group_ids), track.get("artist"), track.get("title"))
                    current_channel = await _sync_current_track_state(cache, track, current_channel)

                    success_count = 0
                    for target_group_id in group_ids:
                        try:
                            await tgcalls.play(
                                target_group_id,
                                AudioPiped(
                                    track["file_id"],
                                    audio_parameters=AudioQuality.HIGH,
                                ),
                            )
                            success_count += 1
                        except Exception as e:
                            logger.error("[%s] Playback error for %s: %s", target_group_id, track.get("file_id"), e)

                    if success_count > 0:
                        return

                    current_channel = await _sync_current_track_state(cache, None, current_channel)
        finally:
            transition_in_progress = False

    @tgcalls.on_stream_end()
    async def on_stream_end(_, update):
        chat_id = getattr(update, "chat_id", None)
        if chat_id in group_id_set:
            _reset_group_votes()
            await play_next()

    from pyrogram import filters

    for target_group_id in group_ids:
        @app.on_message(filters.chat(target_group_id) & filters.command(["like", "dislike", "vote"]))
        async def on_vote(_, message, target_group_id=target_group_id):
            cmd = message.command[0].lower() if message.command else ""
            if cmd == "like":
                vtype = "like"
            elif cmd == "dislike":
                vtype = "dislike"
            else:
                vtype = message.command[1].lower() if len(message.command) > 1 else "like"

            tally = await vote(target_group_id, message.from_user.id, vtype, skip_cb=play_next)
            await message.reply_text(
                f"👍 {tally['likes']}  👎 {tally['dislikes']}"
                + (f"  (skip at {_SKIP_THRESHOLD} 👎)" if tally["dislikes"] > 0 else ""),
                quote=True,
            )

    async def clear_current_track() -> None:
        nonlocal current_channel
        current_channel = await _sync_current_track_state(cache, None, current_channel)

    if consume_radio_commands:
        class _MultiGroupTgCallsBridge:
            async def pause_stream(self, _group_id):
                for target_group_id in group_ids:
                    pause_stream = getattr(tgcalls, "pause_stream", None)
                    if callable(pause_stream):
                        await pause_stream(target_group_id)

            async def leave_call(self, _group_id):
                for target_group_id in group_ids:
                    leave_call = getattr(tgcalls, "leave_call", None)
                    if callable(leave_call):
                        await leave_call(target_group_id)

        asyncio.create_task(
            _run_radio_command_listener(
                cache.redis,
                group_id=group_ids[0],
                tgcalls=_MultiGroupTgCallsBridge(),
                play_next=play_next,
                clear_current_track=clear_current_track,
                cache=cache,
                reconnect_delay=1.0,
            )
        )

    await play_next()
    logger.info("Streamer started for groups %s", group_ids)


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

    if len(group_ids) == 1:
        tasks = [
            _run_group(app, tgcalls, gid, cache, consume_radio_commands=index == 0)
            for index, gid in enumerate(group_ids)
        ]
    else:
        tasks = [
            _run_groups(app, tgcalls, group_ids, cache, consume_radio_commands=True)
        ]
    logger.info("Launching streamer for %d group(s): %s", len(group_ids), group_ids)

    await asyncio.gather(*tasks)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
