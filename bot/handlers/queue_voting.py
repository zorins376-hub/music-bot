"""
queue_voting.py — Collective party DJ: users vote for next track in a group.

Flow:
1. User: /partyqueue add <artist - title>  → suggest a candidate
2. Bot: shows live tally with vote buttons under each candidate
3. After voting period — bot picks winner, downloads and plays it
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

router = Router()

_QUEUE_TTL = 3600   # 1 hour queue lifespan
_MAX_CANDIDATES = 6
_VOTE_PREFIX = "pq:vote"   # callback prefix


def _queue_key(chat_id: int) -> str:
    return f"pqueue:{chat_id}"


def _msg_key(chat_id: int) -> str:
    return f"pqmsg:{chat_id}"


async def _get_queue(chat_id: int) -> list[dict]:
    from bot.services.cache import cache
    raw = await cache.redis.get(_queue_key(chat_id))
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


async def _save_queue(chat_id: int, queue: list[dict]) -> None:
    from bot.services.cache import cache
    await cache.redis.setex(_queue_key(chat_id), _QUEUE_TTL, json.dumps(queue, ensure_ascii=False))


def _render(queue: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🎉 <b>Очередь на следующий трек</b>", ""]
    if not queue:
        lines.append("<i>Пусто. Предложи трек: /partyqueue add Исполнитель - Название</i>")
        return chr(10).join(lines), InlineKeyboardMarkup(inline_keyboard=[])
    sorted_q = sorted(queue, key=lambda c: -len(c.get("votes", [])))
    rows = []
    for i, cand in enumerate(sorted_q, 1):
        votes = len(cand.get("votes", []))
        title = cand.get("title", "")
        lines.append(f"<b>{i}.</b> {title}  ·  👍 {votes}")
        rows.append([
            InlineKeyboardButton(text=f"👍 {votes}", callback_data=f"{_VOTE_PREFIX}:{cand['id']}"),
            InlineKeyboardButton(text="✕", callback_data=f"pq:rm:{cand['id']}"),
        ])
    rows.append([
        InlineKeyboardButton(text="▶ Сыграть победителя", callback_data="pq:play"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="pq:refresh"),
    ])
    return chr(10).join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("partyqueue", "pq"))
async def cmd_partyqueue(message: Message) -> None:
    """Manage party queue: /partyqueue [add <track> | show | clear]"""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("🗳 Очередь работает только в группах.")
        return

    args = (message.text or "").split(maxsplit=2)
    sub = args[1].lower() if len(args) > 1 else "show"
    payload = args[2] if len(args) > 2 else ""

    if sub == "clear":
        from bot.services.cache import cache
        await cache.redis.delete(_queue_key(message.chat.id))
        await message.answer("🗳 Очередь очищена.")
        return

    queue = await _get_queue(message.chat.id)

    if sub == "add" and payload:
        if len(queue) >= _MAX_CANDIDATES:
            await message.answer(f"🗳 В очереди уже {_MAX_CANDIDATES} треков, голосуйте чтобы освободить место.")
            return
        cid = uuid.uuid4().hex[:8]
        queue.append({
            "id": cid,
            "title": payload[:80],
            "by_uid": message.from_user.id,
            "by_name": message.from_user.first_name or "",
            "votes": [message.from_user.id],  # auto-vote for own suggestion
            "added_at": int(time.time()),
        })
        await _save_queue(message.chat.id, queue)

    text, kb = _render(queue)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith(_VOTE_PREFIX))
async def cb_vote(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    cid = callback.data.split(":")[2]
    queue = await _get_queue(chat_id)
    if not queue:
        await callback.answer("Очередь пуста")
        return
    uid = callback.from_user.id
    target = next((c for c in queue if c["id"] == cid), None)
    if not target:
        await callback.answer("Трек не найден")
        return
    votes = target.setdefault("votes", [])
    if uid in votes:
        votes.remove(uid)
        await callback.answer("👎 Голос убран")
    else:
        votes.append(uid)
        await callback.answer("👍 Голос засчитан")
    await _save_queue(chat_id, queue)
    text, kb = _render(queue)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("pq:rm:"))
async def cb_remove(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    cid = callback.data.split(":")[2]
    queue = await _get_queue(chat_id)
    target = next((c for c in queue if c["id"] == cid), None)
    if not target:
        await callback.answer("Не найден")
        return
    if callback.from_user.id != target.get("by_uid"):
        await callback.answer("Удалить может только тот кто добавил", show_alert=True)
        return
    queue = [c for c in queue if c["id"] != cid]
    await _save_queue(chat_id, queue)
    text, kb = _render(queue)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Удалено")


@router.callback_query(lambda c: c.data == "pq:refresh")
async def cb_refresh(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    queue = await _get_queue(callback.message.chat.id)
    text, kb = _render(queue)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(lambda c: c.data == "pq:play")
async def cb_play_winner(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    queue = await _get_queue(chat_id)
    if not queue:
        await callback.answer("Очередь пуста")
        return
    winner = max(queue, key=lambda c: len(c.get("votes", [])))
    if not winner.get("votes"):
        await callback.answer("Ещё нет голосов — пусть проголосуют")
        return
    title = winner["title"]
    # Remove winner from queue
    queue = [c for c in queue if c["id"] != winner["id"]]
    await _save_queue(chat_id, queue)
    text, kb = _render(queue)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await callback.answer(f"▶ Играю: {title[:50]}")
    # Trigger search/download
    from bot.handlers.search import _do_search
    await _do_search(callback.message, title)
