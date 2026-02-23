from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User as TgUser
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc, select

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track

router = Router()

_TOP_PERIOD_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data="top:today"),
            InlineKeyboardButton(text="📆 Неделя", callback_data="top:week"),
            InlineKeyboardButton(text="🏆 Все время", callback_data="top:all"),
        ]
    ]
)


async def _show_top(message: Message, tg_user: TgUser, period: str = "week") -> None:
    user = await get_or_create_user(tg_user)
    lang = user.language

    now = datetime.now(timezone.utc)
    if period == "today":
        since = now - timedelta(days=1)
        period_label = t(lang, "top_period_today")
    elif period == "week":
        since = now - timedelta(weeks=1)
        period_label = t(lang, "top_period_week")
    else:
        since = None
        period_label = t(lang, "top_period_all")

    async with async_session() as session:
        query = select(Track).where(Track.downloads > 0)
        if since:
            query = query.where(Track.created_at >= since)
        query = query.order_by(desc(Track.downloads)).limit(10)
        result = await session.execute(query)
        tracks = result.scalars().all()

    if not tracks:
        await message.answer(t(lang, "top_empty"))
        return

    lines = [f"{t(lang, 'top_header')} ({period_label})"]
    for i, track in enumerate(tracks, 1):
        name = f"{track.artist} — {track.title}" if track.artist else track.title or "Unknown"
        lines.append(f"{i}. {name} ({track.downloads} скач.)")

    await message.answer(
        "\n".join(lines),
        reply_markup=_TOP_PERIOD_KEYBOARD,
        parse_mode="HTML",
    )


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    async with async_session() as session:
        result = await session.execute(
            select(ListeningHistory)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
            .order_by(desc(ListeningHistory.created_at))
            .limit(10)
        )
        records = result.scalars().all()

    if not records:
        await message.answer(t(lang, "history_empty"))
        return

    lines = [t(lang, "history_header")]
    for i, rec in enumerate(records, 1):
        label = rec.query or f"Track #{rec.track_id}"
        lines.append(f"{i}. {label}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    await _show_top(message, message.from_user)


@router.callback_query(lambda c: c.data and c.data.startswith("top:"))
async def handle_top_period(callback: CallbackQuery) -> None:
    period = callback.data.split(":")[1]
    if period not in ("today", "week", "all"):
        await callback.answer()
        return
    await callback.answer()
    await _show_top(callback.message, callback.from_user, period=period)
