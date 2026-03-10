from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.release_notification import ReleaseNotification
from bot.models.user import User
from bot.services.analytics import track_event

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


def _radar_quick_keyboard(lang: str, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "radar_disable_btn") if enabled else t(lang, "radar_enable_btn"),
                    callback_data="radar:disable" if enabled else "radar:enable",
                ),
                InlineKeyboardButton(
                    text=t(lang, "radar_open_btn"),
                    callback_data="radar:open",
                ),
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
    if not new_value:
        await track_event(user.id, "release_opt_out")


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
    await callback.message.edit_reply_markup(
        reply_markup=_radar_quick_keyboard(lang, False)
    )
    await track_event(user.id, "release_opt_out")


@router.callback_query(lambda c: c.data == "radar:enable")
async def cb_radar_enable(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(release_radar_enabled=True)
        )
        await session.commit()

    await callback.answer(t(lang, "radar_updated"))
    await callback.message.edit_reply_markup(
        reply_markup=_radar_quick_keyboard(lang, True)
    )


@router.callback_query(lambda c: c.data == "radar:open")
async def cb_radar_open(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    status = t(lang, "radar_status_on") if user.release_radar_enabled else t(lang, "radar_status_off")

    async with async_session() as session:
        await session.execute(
            update(ReleaseNotification)
            .where(
                ReleaseNotification.user_id == user.id,
                ReleaseNotification.opened_at.is_(None),
            )
            .values(opened_at=datetime.now(timezone.utc))
        )
        await session.commit()

    await callback.answer()
    await track_event(user.id, "release_open")
    await callback.message.answer(
        t(lang, "radar_header", status=status),
        reply_markup=_radar_keyboard(lang, user.release_radar_enabled),
        parse_mode="HTML",
    )
