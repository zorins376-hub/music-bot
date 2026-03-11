"""
party.py — Party Playlists: совместные плейлисты для групповых чатов.

Commands:
  /party           — создать пати-сессию (в ЛС или группе)
  /party <code>    — показать ссылку на пати
  party:close:<code> — закрыть пати (только создатель)
"""
import logging
import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select

from bot.config import settings
from bot.db import get_or_create_user
from bot.models.base import async_session
from bot.models.party import PartySession

logger = logging.getLogger(__name__)

router = Router()


def _party_keyboard(invite_code: str, lang: str = "ru") -> InlineKeyboardMarkup:
    """Generate keyboard with party link and close button."""
    rows = []
    if settings.TMA_URL:
        party_url = f"{settings.TMA_URL.rstrip('/')}?startapp=party_{invite_code}"
        rows.append([
            InlineKeyboardButton(
                text="🎉 Открыть Party",
                web_app=WebAppInfo(url=party_url),
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="❌ Закрыть Party",
            callback_data=f"party:close:{invite_code}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("party"))
async def cmd_party(message: Message) -> None:
    """Create or show a party session."""
    user = await get_or_create_user(message.from_user)

    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        # Show existing party
        code = args[1].strip()
        async with async_session() as session:
            result = await session.execute(
                select(PartySession).where(
                    PartySession.invite_code == code,
                    PartySession.is_active == True,
                )
            )
            party = result.scalar_one_or_none()

        if not party:
            await message.answer("❌ Пати не найдена или уже закрыта.")
            return

        await message.answer(
            f"🎉 <b>{party.name}</b>\n\n"
            f"Код: <code>{party.invite_code}</code>\n"
            f"Отправь ссылку друзьям — они смогут добавлять треки!",
            reply_markup=_party_keyboard(party.invite_code),
            parse_mode="HTML",
        )
        return

    # Create new party
    code = secrets.token_urlsafe(8)[:10]
    name_parts = message.text.split(maxsplit=1)
    name = "Party 🎉"

    chat_id = None
    if message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id
        name = f"Party: {message.chat.title or '🎉'}"

    async with async_session() as session:
        # Limit to 3 active parties per user
        from sqlalchemy.sql import func
        count_result = await session.execute(
            select(func.count()).where(
                PartySession.creator_id == user.id,
                PartySession.is_active == True,
            )
        )
        if (count_result.scalar() or 0) >= 3:
            await message.answer(
                "⚠️ У тебя уже 3 активных пати. Закрой одну, чтобы создать новую."
            )
            return

        party = PartySession(
            invite_code=code,
            creator_id=user.id,
            chat_id=chat_id,
            name=name[:100],
        )
        session.add(party)
        await session.commit()
        await session.refresh(party)

    text = (
        f"🎉 <b>{party.name}</b>\n\n"
        f"Party создана! Код: <code>{party.invite_code}</code>\n\n"
        f"Открой плеер и добавляй треки вместе с друзьями.\n"
        f"Каждый может добавить треки, а ты — DJ 🎧"
    )

    await message.answer(
        text,
        reply_markup=_party_keyboard(party.invite_code),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("party:close:"))
async def cb_close_party(callback: CallbackQuery) -> None:
    """Close a party session."""
    code = callback.data.split(":", 2)[2]
    user = await get_or_create_user(callback.from_user)

    async with async_session() as session:
        result = await session.execute(
            select(PartySession).where(
                PartySession.invite_code == code,
                PartySession.is_active == True,
            )
        )
        party = result.scalar_one_or_none()

        if not party:
            await callback.answer("Пати уже закрыта", show_alert=True)
            return

        if party.creator_id != user.id:
            await callback.answer("Только DJ может закрыть пати", show_alert=True)
            return

        party.is_active = False
        await session.commit()

    await callback.answer("🎉 Пати закрыта!")
    try:
        await callback.message.edit_text(
            f"🏁 <b>{party.name}</b> — завершена!\n\nСпасибо за пати 🎶",
            parse_mode="HTML",
        )
    except Exception:
        pass
