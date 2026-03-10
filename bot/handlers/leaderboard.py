"""
leaderboard.py handler — /leaderboard command and callback.

Shows top-50 users by XP (weekly and all-time).
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router()


async def _build_leaderboard(user_id: int, lang: str, period: str = "weekly") -> tuple[str, InlineKeyboardMarkup]:
    from bot.services.leaderboard import get_leaderboard, get_user_rank, xp_for_next_level
    from sqlalchemy import select

    entries = await get_leaderboard(period, limit=50)
    my_rank = await get_user_rank(user_id, period)

    # Fetch user names for top entries
    user_ids = [uid for uid, _ in entries[:20]]
    names: dict[int, str] = {}
    if user_ids:
        async with async_session() as session:
            result = await session.execute(
                select(User.id, User.first_name, User.username).where(User.id.in_(user_ids))
            )
            for row in result.all():
                names[row[0]] = row[1] or row[2] or str(row[0])

    period_label = t(lang, "lb_weekly") if period == "weekly" else t(lang, "lb_alltime")
    lines = [f"🏆 <b>{t(lang, 'lb_header')}</b> — {period_label}\n"]

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (uid, score) in enumerate(entries[:20], 1):
        name = names.get(uid, str(uid))
        medal = medals.get(i, f"{i}.")
        marker = " ◄" if uid == user_id else ""
        lines.append(f"{medal} {name} — {int(score)} XP{marker}")

    if my_rank:
        lines.append(f"\n{t(lang, 'lb_your_rank', rank=my_rank)}")

    # Get user's XP info
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user:
        cur, nxt = xp_for_next_level(user.xp or 0)
        lines.append(t(lang, "lb_your_xp", xp=user.xp or 0, level=user.level or 1))
        progress = min(100, int(((user.xp or 0) - cur) / max(1, nxt - cur) * 100))
        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
        lines.append(f"[{bar}] {progress}%")
        if user.streak_days:
            lines.append(t(lang, "lb_streak", days=user.streak_days))

    other_period = "alltime" if period == "weekly" else "weekly"
    other_label = t(lang, "lb_alltime") if period == "weekly" else t(lang, "lb_weekly")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 {other_label}", callback_data=f"lb:{other_period}")]
    ])

    return "\n".join(lines), kb


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    text, kb = await _build_leaderboard(user.id, user.language, "weekly")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "action:leaderboard")
async def handle_leaderboard_button(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    text, kb = await _build_leaderboard(user.id, user.language, "weekly")
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("lb:"))
async def handle_lb_period(callback: CallbackQuery) -> None:
    period = callback.data.split(":")[1]
    if period not in ("weekly", "alltime"):
        await callback.answer()
        return
    user = await get_or_create_user(callback.from_user)
    text, kb = await _build_leaderboard(user.id, user.language, period)
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
