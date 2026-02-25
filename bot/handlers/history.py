from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User as TgUser
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc, func, select

from bot.db import get_or_create_user, get_user_stats
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track

router = Router()


def _top_period_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"▫ {t(lang, 'top_period_today')}", callback_data="top:today"),
                InlineKeyboardButton(text=f"▪ {t(lang, 'top_period_week')}", callback_data="top:week"),
                InlineKeyboardButton(text=f"◆ {t(lang, 'top_period_all')}", callback_data="top:all"),
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

    # Count play events per track within the time period
    async with async_session() as session:
        q = (
            select(
                Track,
                func.count(ListeningHistory.id).label("play_count"),
            )
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(ListeningHistory.action == "play")
        )
        if since:
            q = q.where(ListeningHistory.created_at >= since)
        q = q.group_by(Track.id).order_by(desc("play_count")).limit(10)
        result = await session.execute(q)
        rows = result.all()

    if not rows:
        await message.answer(t(lang, "top_empty"))
        return

    lines = [f"{t(lang, 'top_header')} ({period_label})"]
    for i, (track, play_count) in enumerate(rows, 1):
        name = f"{track.artist} — {track.title}" if track.artist else track.title or "Unknown"
        lines.append(f"{i}. {name} ({play_count} {t(lang, 'downloads_count')})")

    await message.answer(
        "\n".join(lines),
        reply_markup=_top_period_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    async with async_session() as session:
        result = await session.execute(
            select(ListeningHistory, Track)
            .outerjoin(Track, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
            .order_by(desc(ListeningHistory.created_at))
            .limit(10)
        )
        rows = result.all()

    if not rows:
        await message.answer(t(lang, "history_empty"))
        return

    lines = [t(lang, "history_header")]
    for i, (rec, track) in enumerate(rows, 1):
        if track and (track.title or track.artist):
            label = f"{track.artist} — {track.title}" if track.artist else track.title
        else:
            label = rec.query or f"Track #{rec.track_id}"
        lines.append(f"{i}. {label}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    await _show_top(message, message.from_user)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    stats = await get_user_stats(user.id)

    lines = [t(lang, "my_stats_header")]
    lines.append(t(lang, "my_stats_total", count=stats["total"]))
    lines.append(t(lang, "my_stats_week", count=stats["week"]))
    if stats["top_artist"]:
        lines.append(t(lang, "my_stats_top_artist", artist=stats["top_artist"]))
    lines.append(
        t(lang, "my_stats_since", date=user.created_at.strftime("%d.%m.%Y"))
    )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("top:"))
async def handle_top_period(callback: CallbackQuery) -> None:
    period = callback.data.split(":")[1]
    if period not in ("today", "week", "all"):
        await callback.answer()
        return
    await callback.answer()
    await _show_top(callback.message, callback.from_user, period=period)
