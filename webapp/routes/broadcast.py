"""
Broadcast (Live Radio) — admin-only live DJ streaming.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import json
import logging
import time as _time
from datetime import datetime, timezone

from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse

from bot.config import settings
from webapp.auth import verify_init_data
from webapp.deps import (
    _fire_task,
    _get_or_create_webapp_user,
    _get_redis,
    get_current_user,
    logger,
)

router = APIRouter(tags=["broadcast"])

# ── In-memory state ──────────────────────────────────────────────────────
_MAX_BROADCAST_SUBSCRIBERS = 500
_broadcast_subscribers: list[asyncio.Queue] = []

# ── Redis keys ───────────────────────────────────────────────────────────
_BCAST_LIVE_KEY = "broadcast:live"
_BCAST_STATE_KEY = "broadcast:state"
_BCAST_QUEUE_KEY = "broadcast:queue"
_BCAST_PIN_KEY = "broadcast:pinned_msgs"


# ── Helpers ──────────────────────────────────────────────────────────────

def _is_broadcast_dj(user: dict) -> bool:
    from bot.db import is_admin
    user_id = int(user.get("id", 0))
    username = user.get("username")
    return is_admin(user_id, username)


async def _require_broadcast_admin(user: dict):
    if not _is_broadcast_dj(user):
        raise HTTPException(status_code=403, detail="Only authorized DJs can control the broadcast")


async def _notify_broadcast(event: str, data: dict | None = None):
    payload = json.dumps({"event": event, "data": data or {}}, ensure_ascii=False)
    dead: list[asyncio.Queue] = []
    for q in _broadcast_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _broadcast_subscribers.remove(q)
        except ValueError:
            pass


def _clamp_broadcast_index(index: int, queue_len: int) -> int:
    if queue_len <= 0:
        return 0
    return min(max(index, 0), queue_len - 1)


def _reorder_broadcast_index(current_idx: int, from_pos: int, to_pos: int) -> int:
    if from_pos == to_pos:
        return current_idx
    if current_idx == from_pos:
        return to_pos
    if from_pos < current_idx <= to_pos:
        return current_idx - 1
    if to_pos <= current_idx < from_pos:
        return current_idx + 1
    return current_idx


async def _normalize_broadcast_state(r) -> tuple[int, int]:
    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    normalized_idx = _clamp_broadcast_index(current_idx, queue_len)

    mapping: dict[str, str] = {}
    if normalized_idx != current_idx:
        mapping["current_idx"] = str(normalized_idx)
    if queue_len <= 0:
        mapping["seek_pos"] = "0"
        mapping["action"] = "idle"

    if mapping:
        await r.hset(_BCAST_STATE_KEY, mapping=mapping)

    return normalized_idx, queue_len


async def _get_broadcast_state() -> dict:
    r = await _get_redis()
    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        return {
            "is_live": False, "dj_id": None, "dj_name": None,
            "current_idx": 0, "seek_pos": 0, "action": "idle",
            "started_at": None, "updated_at": None, "channel": None,
            "listener_count": len(_broadcast_subscribers), "tracks": [],
        }

    current_idx, _queue_len = await _normalize_broadcast_state(r)
    state = await r.hgetall(_BCAST_STATE_KEY)
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    tracks = []
    for i, raw in enumerate(queue_raw):
        try:
            t = json.loads(raw)
            t["position"] = i
            tracks.append(t)
        except Exception:
            pass

    # Compute real-time playback position so listeners can sync mid-track
    seek_pos = float(state.get("seek_pos", 0))
    action = state.get("action", "idle") if tracks else "idle"
    elapsed_pos = seek_pos
    if action == "play" and state.get("updated_at"):
        try:
            updated_at = datetime.fromisoformat(state["updated_at"])
            elapsed = (datetime.now(timezone.utc) - updated_at).total_seconds()
            elapsed_pos = seek_pos + max(0, elapsed)
            # Clamp to current track duration
            if tracks and current_idx < len(tracks):
                dur = tracks[current_idx].get("duration", 0)
                if dur and elapsed_pos > dur:
                    elapsed_pos = dur
        except Exception:
            pass

    return {
        "is_live": True,
        "dj_id": int(state.get("dj_id", 0)) if state.get("dj_id") else None,
        "dj_name": state.get("dj_name"),
        "current_idx": current_idx,
        "seek_pos": seek_pos,
        "elapsed_pos": round(elapsed_pos, 1),
        "action": action,
        "started_at": state.get("started_at"),
        "updated_at": state.get("updated_at"),
        "channel": state.get("channel"),
        "listener_count": len(_broadcast_subscribers),
        "tracks": tracks,
    }


async def _collect_broadcast_group_ids() -> list[int]:
    """Collect all group IDs to notify: BLACKROOM config + all active bot_chats."""
    group_ids: list[int] = []

    # From config
    if settings.BLACKROOM_GROUP_ID:
        for gid in str(settings.BLACKROOM_GROUP_ID).split(","):
            gid = gid.strip()
            if gid:
                try:
                    group_ids.append(int(gid))
                except ValueError:
                    pass

    # From DB: all groups where bot is active
    try:
        from bot.models.base import async_session as _as
        from bot.models.bot_chat import BotChat
        from sqlalchemy import select
        async with _as() as session:
            result = await session.execute(
                select(BotChat.chat_id).where(BotChat.is_active == True)
            )
            for row in result.all():
                if row[0] not in group_ids:
                    group_ids.append(row[0])
    except Exception as e:
        logger.warning("Failed to load bot_chats for broadcast: %s", e)

    return group_ids


async def _broadcast_send_track_to_chats(track: dict, dj_name: str = "DJ"):
    """Send the current track as audio message to all groups where bot is active."""
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        if not settings.BOT_TOKEN or not track.get("file_id"):
            return

        group_ids = await _collect_broadcast_group_ids()
        if not group_ids:
            return

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            caption = (
                f"<b>ON AIR</b>  {track.get('title', '?')} — {track.get('artist', '?')}\n"
                f"DJ: {dj_name}"
            )
            for gid in group_ids:
                try:
                    await bot.send_audio(
                        chat_id=gid,
                        audio=track["file_id"],
                        caption=caption,
                        title=track.get("title"),
                        performer=track.get("artist"),
                    )
                except Exception as e:
                    logger.warning("Failed to send track to chat %s: %s", gid, e)
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Broadcast send track to chats failed: %s", e)


async def _broadcast_notify_chat(action: str, dj_name: str = "DJ"):
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        if not settings.BOT_TOKEN:
            return

        group_ids = await _collect_broadcast_group_ids()
        if not group_ids:
            return

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            r = await _get_redis()

            if action == "started":
                text = (
                    f"<b>ON AIR</b>\n\n"
                    f"DJ <b>{dj_name}</b> started a live broadcast!\n"
                    f"Open the app to listen together"
                )
                rows = []
                if settings.BOT_TOKEN:
                    # Use deep link — works in channels, groups, and private chats
                    bot_username = (await bot.get_me()).username
                    rows.append([
                        InlineKeyboardButton(
                            text="🔴 Listen Live",
                            url=f"https://t.me/{bot_username}/app?startapp=broadcast",
                        ),
                    ])
                kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

                for gid in group_ids:
                    try:
                        msg = await bot.send_message(gid, text, reply_markup=kb)
                        try:
                            await bot.pin_chat_message(
                                chat_id=gid,
                                message_id=msg.message_id,
                                disable_notification=False,
                            )
                            await r.hset(_BCAST_PIN_KEY, str(gid), str(msg.message_id))
                        except Exception as pin_err:
                            logger.warning("Failed to pin ON AIR in %s: %s", gid, pin_err)
                    except Exception as e:
                        logger.warning("Failed to notify group %s: %s", gid, e)

            elif action == "stopped":
                for gid in group_ids:
                    try:
                        pinned_mid = await r.hget(_BCAST_PIN_KEY, str(gid))
                        if pinned_mid:
                            mid = int(pinned_mid)
                            try:
                                await bot.unpin_chat_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                            try:
                                await bot.delete_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                            await r.hdel(_BCAST_PIN_KEY, str(gid))
                    except Exception:
                        pass

                text = "The broadcast has ended. See you next time!"
                for gid in group_ids:
                    try:
                        await bot.send_message(gid, text)
                    except Exception as e:
                        logger.warning("Failed to notify group %s: %s", gid, e)
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Broadcast chat notification failed: %s", e)


def _broadcast_voice_chat_keys(channel: str | None) -> tuple[str, str]:
    channel_name = (channel or "tequila").strip() or "tequila"
    return f"radio:queue:{channel_name}", f"radio:current:{channel_name}"


async def _broadcast_append_voice_chat_queue(r, channel: str | None, tracks_raw: list[str]) -> None:
    if not tracks_raw:
        return
    vc_queue_key, _ = _broadcast_voice_chat_keys(channel)
    for raw in tracks_raw:
        await r.rpush(vc_queue_key, raw)


async def _broadcast_rebuild_voice_chat_queue(
    r,
    channel: str | None,
    *,
    include_current: bool = False,
) -> None:
    vc_queue_key, _ = _broadcast_voice_chat_keys(channel)
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    if not queue_raw:
        await r.delete(vc_queue_key)
        return

    current_idx = _clamp_broadcast_index(
        int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0),
        len(queue_raw),
    )
    start_idx = current_idx if include_current else current_idx + 1
    pending_tracks = queue_raw[start_idx:] if start_idx < len(queue_raw) else []

    await r.delete(vc_queue_key)
    if pending_tracks:
        for raw in pending_tracks:
            await r.rpush(vc_queue_key, raw)


async def _broadcast_sync_voice_chat(r, action: str, channel: str = "tequila"):
    try:
        state = await r.hgetall(_BCAST_STATE_KEY)
        active_channel = state.get("channel") or channel
        vc_queue_key, vc_current_key = _broadcast_voice_chat_keys(active_channel)

        if action == "started":
            queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
            await r.delete(vc_queue_key)
            if queue_raw:
                for raw in queue_raw:
                    await r.rpush(vc_queue_key, raw)
                logger.info("Synced %d broadcast tracks to %s", len(queue_raw), vc_queue_key)
            else:
                await r.delete(vc_current_key)

        elif action == "stopped":
            await r.delete(vc_queue_key)
            await r.delete(vc_current_key)
    except Exception as e:
        logger.error("Voice chat sync failed: %s", e)


async def _broadcast_publish_voice_chat_command(r, command: str) -> None:
    try:
        await r.publish("radio:cmd", command)
    except Exception as e:
        logger.error("Voice chat command publish failed: %s", e)


async def _broadcast_wake_voice_chat_if_idle(r, added_tracks: list[str], *, queue_len_before: int) -> None:
    if queue_len_before <= 0 and added_tracks:
        await _broadcast_publish_voice_chat_command(r, "skip")


async def _load_channel_to_broadcast(r, channel: str, limit: int, exclude: list[str] | None = None) -> list[str]:
    from bot.models.base import async_session as _as
    from bot.models.track import Track as TrackModel
    from sqlalchemy import select, func

    exclude_set = set(exclude or [])
    added_tracks: list[str] = []

    async with _as() as session:
        q = select(
            TrackModel.source_id, TrackModel.title, TrackModel.artist,
            TrackModel.duration, TrackModel.cover_url, TrackModel.file_id,
        ).where(
            TrackModel.channel == channel,
            TrackModel.file_id.isnot(None),
        )
        # Exclude already-queued tracks at DB level to avoid duplicates
        if exclude_set:
            q = q.where(TrackModel.source_id.notin_(list(exclude_set)))
        q = q.order_by(func.random()).limit(limit)

        result = await session.execute(q)
        for row in result.all():
            vid = row[0]
            track_data = json.dumps({
                "video_id": vid,
                "title": row[1] or "Unknown",
                "artist": row[2] or "Unknown",
                "duration": row[3] or 0,
                "duration_fmt": f"{(row[3] or 0) // 60}:{(row[3] or 0) % 60:02d}",
                "source": "channel",
                "cover_url": row[4],
                "file_id": row[5],
                "channel": channel,
            }, ensure_ascii=False)
            await r.rpush(_BCAST_QUEUE_KEY, track_data)
            added_tracks.append(track_data)

    return added_tracks


async def _import_channel_tracks(user: dict, channel_ref: str, label: str):
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from bot.db import upsert_track

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        admin_id = int(user["id"])
        try:
            chat = await bot.get_chat(channel_ref)
            chat_id = chat.id
            saved, msg_id, consecutive_fails = 0, 0, 0
            start_time = _time.monotonic()
            max_scan = 5000
            timeout_sec = 300

            while consecutive_fails < 30 and msg_id < max_scan:
                if _time.monotonic() - start_time > timeout_sec:
                    logger.warning("Channel import timeout for %s after %d msgs", channel_ref, msg_id)
                    break
                msg_id += 1
                try:
                    fwd = await bot.forward_message(
                        chat_id=admin_id,
                        from_chat_id=chat_id,
                        message_id=msg_id,
                        disable_notification=True,
                    )
                    consecutive_fails = 0

                    if fwd.audio:
                        audio = fwd.audio
                        source_id = f"tg_{chat_id}_{msg_id}"
                        title = audio.title or (audio.file_name or "Unknown")
                        artist = audio.performer or ""

                        await upsert_track(
                            source_id=source_id,
                            title=title,
                            artist=artist,
                            duration=audio.duration,
                            file_id=audio.file_id,
                            source="channel",
                            channel=label,
                        )
                        saved += 1

                    try:
                        await bot.delete_message(admin_id, fwd.message_id)
                    except Exception:
                        pass

                    await asyncio.sleep(0.1)
                except Exception:
                    consecutive_fails += 1
                    await asyncio.sleep(0.05)

            logger.info("Imported %d tracks from %s -> %s", saved, channel_ref, label)

            try:
                await bot.send_message(
                    admin_id,
                    f"Import done! {saved} tracks from {channel_ref} -> {label}",
                )
            except Exception:
                pass
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Channel import failed: %s", e)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/api/broadcast")
async def get_broadcast(user: dict = Depends(get_current_user)):
    state = await _get_broadcast_state()
    state["is_dj"] = _is_broadcast_dj(user)
    return state


@router.post("/api/broadcast/start")
async def start_broadcast(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    r = await _get_redis()

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    channel = body.get("channel", "tequila")
    limit = min(int(body.get("limit", 30)), 100)

    now = datetime.now(timezone.utc).isoformat()

    await r.set(_BCAST_LIVE_KEY, "1")
    await r.hset(_BCAST_STATE_KEY, mapping={
        "dj_id": str(user["id"]),
        "dj_name": user.get("first_name", "DJ"),
        "action": "play",
        "current_idx": "0",
        "seek_pos": "0",
        "started_at": now,
        "updated_at": now,
        "channel": channel,
    })
    await r.delete(_BCAST_QUEUE_KEY)

    try:
        await _load_channel_to_broadcast(r, channel, limit)
    except Exception as e:
        logger.error("Failed to load channel tracks for broadcast: %s", e)

    await _notify_broadcast("started", {
        "dj_id": user["id"], "dj_name": user.get("first_name", "DJ"),
    })

    dj_name = user.get("first_name", "DJ")
    _fire_task(_broadcast_notify_chat("started", dj_name))
    _fire_task(_broadcast_sync_voice_chat(r, "started", channel))
    _fire_task(_broadcast_publish_voice_chat_command(r, "skip"))

    return await _get_broadcast_state()


@router.post("/api/broadcast/stop")
async def stop_broadcast(user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    r = await _get_redis()
    channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
    await r.delete(_BCAST_LIVE_KEY, _BCAST_STATE_KEY, _BCAST_QUEUE_KEY)
    await _notify_broadcast("stopped", {})

    _fire_task(_broadcast_notify_chat("stopped"))
    _fire_task(_broadcast_sync_voice_chat(r, "stopped", channel))
    _fire_task(_broadcast_publish_voice_chat_command(r, "stop"))

    return {"ok": True}


@router.post("/api/broadcast/load-channel")
async def broadcast_load_channel(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    body = await request.json()
    channel = body.get("channel", "tequila")
    limit = min(int(body.get("limit", 30)), 100)

    r = await _get_redis()
    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        raise HTTPException(400, "Broadcast not active")

    existing = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    queue_len_before = len(existing)
    exclude = []
    for raw in existing:
        try:
            exclude.append(json.loads(raw).get("video_id", ""))
        except Exception:
            pass

    added_tracks = await _load_channel_to_broadcast(r, channel, limit, exclude)
    _fire_task(_broadcast_append_voice_chat_queue(r, await r.hget(_BCAST_STATE_KEY, "channel") or channel, added_tracks))
    _fire_task(_broadcast_wake_voice_chat_if_idle(r, added_tracks, queue_len_before=queue_len_before))
    await _notify_broadcast("queue_updated", {
        "track_count": await r.llen(_BCAST_QUEUE_KEY),
    })
    return await _get_broadcast_state()


@router.post("/api/broadcast/tracks")
async def broadcast_add_track(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    body = await request.json()
    r = await _get_redis()

    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        raise HTTPException(400, "Broadcast not active")

    active_channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
    queue_len_before = await r.llen(_BCAST_QUEUE_KEY)

    track_data = json.dumps({
        "video_id": body.get("video_id", ""),
        "title": body.get("title", ""),
        "artist": body.get("artist", ""),
        "duration": body.get("duration", 0),
        "duration_fmt": body.get("duration_fmt", "0:00"),
        "source": body.get("source", "youtube"),
        "cover_url": body.get("cover_url"),
        "channel": body.get("channel") or active_channel,
    }, ensure_ascii=False)
    await r.rpush(_BCAST_QUEUE_KEY, track_data)
    _fire_task(_broadcast_append_voice_chat_queue(r, active_channel, [track_data]))
    _fire_task(_broadcast_wake_voice_chat_if_idle(r, [track_data], queue_len_before=queue_len_before))

    await _notify_broadcast("queue_updated", {
        "track_count": await r.llen(_BCAST_QUEUE_KEY),
    })
    return await _get_broadcast_state()


@router.delete("/api/broadcast/tracks/{video_id}")
async def broadcast_remove_track(video_id: str, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    r = await _get_redis()

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    removed_index: int | None = None
    for index, raw in enumerate(queue_raw):
        try:
            t = json.loads(raw)
            if t.get("video_id") == video_id:
                removed_index = index
                await r.lrem(_BCAST_QUEUE_KEY, 1, raw)
                break
        except Exception:
            pass

    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    next_idx = current_idx
    mapping: dict[str, str] = {}
    if removed_index is not None:
        if queue_len <= 0:
            mapping = {"current_idx": "0", "seek_pos": "0", "action": "idle"}
            next_idx = 0
        else:
            if removed_index < current_idx:
                next_idx = current_idx - 1
            else:
                next_idx = _clamp_broadcast_index(current_idx, queue_len)
            mapping["current_idx"] = str(_clamp_broadcast_index(next_idx, queue_len))
            if removed_index == current_idx:
                mapping["seek_pos"] = "0"
        if mapping:
            await r.hset(_BCAST_STATE_KEY, mapping=mapping)
        active_channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
        _fire_task(_broadcast_rebuild_voice_chat_queue(
            r,
            active_channel,
            include_current=removed_index == current_idx,
        ))
        if removed_index == current_idx:
            _fire_task(_broadcast_publish_voice_chat_command(r, "skip" if queue_len > 0 else "stop"))

    await _notify_broadcast("queue_updated", {
        "track_count": queue_len,
        "current_idx": _clamp_broadcast_index(next_idx, queue_len),
    })
    return await _get_broadcast_state()


@router.post("/api/broadcast/reorder")
async def broadcast_reorder(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    body = await request.json()
    from_pos = int(body.get("from_position", 0))
    to_pos = int(body.get("to_position", 0))

    r = await _get_redis()
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    if from_pos < 0 or from_pos >= len(queue_raw) or to_pos < 0 or to_pos >= len(queue_raw):
        raise HTTPException(400, "Invalid positions")

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)

    items = list(queue_raw)
    item = items.pop(from_pos)
    items.insert(to_pos, item)
    next_idx = _clamp_broadcast_index(
        _reorder_broadcast_index(current_idx, from_pos, to_pos),
        len(items),
    )

    pipe = r.pipeline()
    pipe.delete(_BCAST_QUEUE_KEY)
    for it in items:
        pipe.rpush(_BCAST_QUEUE_KEY, it)
    pipe.hset(_BCAST_STATE_KEY, mapping={"current_idx": str(next_idx)})
    await pipe.execute()

    active_channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
    _fire_task(_broadcast_rebuild_voice_chat_queue(r, active_channel))

    await _notify_broadcast("queue_updated", {
        "track_count": len(items),
        "current_idx": next_idx,
    })
    return await _get_broadcast_state()


@router.post("/api/broadcast/skip")
async def broadcast_skip(user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    r = await _get_redis()

    now = datetime.now(timezone.utc).isoformat()

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    if queue_len <= 0:
        await r.hset(_BCAST_STATE_KEY, mapping={"current_idx": "0", "seek_pos": "0", "action": "idle", "updated_at": now})
        return await _get_broadcast_state()

    new_idx = min(current_idx + 1, max(queue_len - 1, 0))

    await r.hset(_BCAST_STATE_KEY, mapping={
        "current_idx": str(new_idx),
        "seek_pos": "0",
        "action": "play",
        "updated_at": now,
    })

    track_raw = await r.lindex(_BCAST_QUEUE_KEY, new_idx)
    track = json.loads(track_raw) if track_raw else {}

    await _notify_broadcast("next", {
        "position": new_idx,
        "track": track,
    })
    # Send track audio to group chats
    dj_name = await r.hget(_BCAST_STATE_KEY, "dj_name") or "DJ"
    _fire_task(_broadcast_send_track_to_chats(track, dj_name))
    _fire_task(_broadcast_rebuild_voice_chat_queue(
        r,
        await r.hget(_BCAST_STATE_KEY, "channel") or "tequila",
        include_current=True,
    ))
    _fire_task(_broadcast_publish_voice_chat_command(r, "skip"))
    return await _get_broadcast_state()


@router.post("/api/broadcast/playback")
async def broadcast_playback(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    body = await request.json()
    action = body.get("action", "play")
    seek_pos = float(body.get("seek_pos", 0))

    r = await _get_redis()
    now = datetime.now(timezone.utc).isoformat()
    previous_current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)

    mapping = {"action": action, "updated_at": now}
    if seek_pos > 0:
        mapping["seek_pos"] = str(seek_pos)
    if "current_idx" in body:
        mapping["current_idx"] = str(int(body["current_idx"]))

    await r.hset(_BCAST_STATE_KEY, mapping=mapping)
    current_idx, queue_len = await _normalize_broadcast_state(r)
    effective_action = action if queue_len > 0 else "idle"
    effective_seek_pos = seek_pos if queue_len > 0 else 0

    await _notify_broadcast("playback_sync", {
        "action": effective_action,
        "seek_pos": effective_seek_pos,
        "current_idx": current_idx,
    })
    _fire_task(_broadcast_rebuild_voice_chat_queue(
        r,
        await r.hget(_BCAST_STATE_KEY, "channel") or "tequila",
        include_current="current_idx" in body,
    ))
    target_idx = int(body["current_idx"]) if "current_idx" in body else previous_current_idx
    if queue_len > 0 and target_idx != previous_current_idx:
        _fire_task(_broadcast_publish_voice_chat_command(r, "skip"))
    elif action in {"pause", "stop"}:
        _fire_task(_broadcast_publish_voice_chat_command(r, action))
    return await _get_broadcast_state()


@router.post("/api/broadcast/advance")
async def broadcast_advance(user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    r = await _get_redis()

    now = datetime.now(timezone.utc).isoformat()

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    if queue_len <= 0:
        await r.hset(_BCAST_STATE_KEY, mapping={"current_idx": "0", "seek_pos": "0", "action": "idle", "updated_at": now})
        return await _get_broadcast_state()

    new_idx = current_idx + 1

    # Auto-refill if running low
    if queue_len - new_idx < 5:
        channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
        existing = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
        exclude = []
        for raw in existing:
            try:
                exclude.append(json.loads(raw).get("video_id", ""))
            except Exception:
                pass
        try:
            added_tracks = await _load_channel_to_broadcast(r, channel, 20, exclude)
            _fire_task(_broadcast_append_voice_chat_queue(r, channel, added_tracks))
        except Exception as e:
            logger.error("Broadcast auto-refill failed: %s", e)
        queue_len = await r.llen(_BCAST_QUEUE_KEY)

    # Wrap around if at end
    if new_idx >= queue_len:
        new_idx = 0

    await r.hset(_BCAST_STATE_KEY, mapping={
        "current_idx": str(new_idx),
        "seek_pos": "0",
        "action": "play",
        "updated_at": now,
    })

    track_raw = await r.lindex(_BCAST_QUEUE_KEY, new_idx)
    track = json.loads(track_raw) if track_raw else {}

    await _notify_broadcast("next", {
        "position": new_idx,
        "track": track,
    })
    # Send track audio to group chats
    dj_name = await r.hget(_BCAST_STATE_KEY, "dj_name") or "DJ"
    _fire_task(_broadcast_send_track_to_chats(track, dj_name))

    return await _get_broadcast_state()


@router.get("/api/broadcast/events")
async def broadcast_events(
    request: Request,
    x_telegram_init_data: str | None = Header(None),
    token: str | None = Query(None),
):
    init_data = x_telegram_init_data or token
    if not init_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = verify_init_data(init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    await _get_or_create_webapp_user(user)

    if len(_broadcast_subscribers) >= _MAX_BROADCAST_SUBSCRIBERS:
        raise HTTPException(status_code=503, detail="Broadcast at capacity")

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    _broadcast_subscribers.append(queue)

    await _notify_broadcast("listener_count", {
        "count": len(_broadcast_subscribers),
    })

    async def event_generator():
        try:
            state = await _get_broadcast_state()
            state["is_dj"] = _is_broadcast_dj(user)
            yield f"data: {json.dumps({'event': 'connected', 'data': state}, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                _broadcast_subscribers.remove(queue)
            except ValueError:
                pass
            await _notify_broadcast("listener_count", {
                "count": len(_broadcast_subscribers),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/broadcast/channels")
async def broadcast_channels(user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    from bot.models.base import async_session as _as
    from bot.models.track import Track as TrackModel
    from sqlalchemy import select, func

    async with _as() as session:
        result = await session.execute(
            select(TrackModel.channel, func.count())
            .where(TrackModel.channel.isnot(None), TrackModel.file_id.isnot(None))
            .group_by(TrackModel.channel)
            .order_by(func.count().desc())
        )
        channels = [{"label": r[0], "track_count": r[1]} for r in result.all()]
    return {"channels": channels}


@router.post("/api/broadcast/import-channel")
async def broadcast_import_channel(request: Request, user: dict = Depends(get_current_user)):
    await _require_broadcast_admin(user)
    body = await request.json()
    channel_ref = body.get("channel_ref", "").strip()
    label = body.get("label", "").strip().lower() or channel_ref.lstrip("@").lower()

    if not channel_ref:
        raise HTTPException(400, "channel_ref required (e.g. @my_music_channel)")
    if len(channel_ref) > 128:
        raise HTTPException(400, "channel_ref too long")
    import re as _re
    if not _re.match(r'^@?[a-zA-Z0-9_]+$', channel_ref):
        raise HTTPException(400, "Invalid channel_ref format")

    _fire_task(_import_channel_tracks(user, channel_ref, label))
    return {"status": "importing", "channel": channel_ref, "label": label}


# ── Voice messages ───────────────────────────────────────────────────
_VOICE_DIR = Path(__file__).resolve().parent.parent / "static" / "voice"
_VOICE_DIR.mkdir(parents=True, exist_ok=True)
_MAX_VOICE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/api/broadcast/voice")
async def broadcast_voice(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """DJ uploads a voice message that plays for all listeners over the music."""
    await _require_broadcast_admin(user)

    r = await _get_redis()
    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        raise HTTPException(400, "No active broadcast")

    data = await file.read()
    if len(data) > _MAX_VOICE_SIZE:
        raise HTTPException(413, "Voice message too large (max 5 MB)")

    ts = int(_time.time() * 1000)
    ext = "webm"
    if file.content_type and "ogg" in file.content_type:
        ext = "ogg"
    elif file.content_type and "mp4" in file.content_type:
        ext = "m4a"

    filename = f"dj_{ts}.{ext}"
    filepath = _VOICE_DIR / filename
    filepath.write_bytes(data)

    voice_url = f"/voice/{filename}"

    await _notify_broadcast("voice", {
        "url": voice_url,
        "dj_name": user.get("first_name", "DJ"),
        "duration": None,
    })

    return {"status": "ok", "url": voice_url}
