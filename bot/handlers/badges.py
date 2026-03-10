"""badges.py handler — View and display user badges."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User
from bot.services.achievements import BADGES, get_badge_display

router = Router()


async def _show_badges(user_id: int, lang: str) -> str:
    """Build badges display text."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        badges = user.badges if user else []

    if not badges:
        return t(lang, "badges_empty")

    lines = [t(lang, "badges_header", count=len(badges))]
    for badge_id in badges:
        name, desc = get_badge_display(badge_id, lang)
        lines.append(f"\n{name}\n<i>{desc}</i>")

    return "\n".join(lines)


@router.message(Command("badges"))
async def cmd_badges(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    text = await _show_badges(user.id, user.language)
    await message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "action:badges")
async def handle_badges_btn(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    text = await _show_badges(user.id, user.language)
    await callback.message.answer(text, parse_mode="HTML")
