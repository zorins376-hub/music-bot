from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

router = Router()


def _radar_keyboard(lang: str, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "radar_disable_btn") if enabled else t(lang, "radar_enable_btn"),
                    callback_data="radar:toggle",
                )
            ]
        ]
    )


@router.message(Command("radar"))
async def cmd_radar(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    status = t(lang, "radar_status_on") if user.release_radar_enabled else t(lang, "radar_status_off")
    await message.answer(
        t(lang, "radar_header", status=status),
        reply_markup=_radar_keyboard(lang, user.release_radar_enabled),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "radar:toggle")
async def cb_radar_toggle(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    new_value = not bool(user.release_radar_enabled)

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(release_radar_enabled=new_value)
        )
        await session.commit()

    status = t(lang, "radar_status_on") if new_value else t(lang, "radar_status_off")
    await callback.answer(t(lang, "radar_updated"))
    await callback.message.edit_text(
        t(lang, "radar_header", status=status),
        reply_markup=_radar_keyboard(lang, new_value),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "radar:disable")
async def cb_radar_disable(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(release_radar_enabled=False)
        )
        await session.commit()

    await callback.answer(t(lang, "radar_updated"))
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        t(lang, "radar_header", status=t(lang, "radar_status_off")),
        reply_markup=_radar_keyboard(lang, False),
        parse_mode="HTML",
    )
