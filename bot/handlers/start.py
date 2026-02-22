from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

router = Router()


def _main_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ TEQUILA LIVE", callback_data="radio:tequila"),
                InlineKeyboardButton(text="🌕 FULLMOON LIVE", callback_data="radio:fullmoon"),
            ],
            [
                InlineKeyboardButton(text="🔥 AUTO MIX", callback_data="radio:automix"),
                InlineKeyboardButton(text="🧠 По вашему вкусу", callback_data="action:recommend"),
            ],
            [
                InlineKeyboardButton(text="🔎 Найти трек", callback_data="action:search"),
                InlineKeyboardButton(text="📊 Топ сегодня", callback_data="action:top"),
            ],
            [
                InlineKeyboardButton(text="💎 Premium", callback_data="action:premium"),
            ],
        ]
    )


_LANG_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇰🇬 Кыргызча", callback_data="lang:kg"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        ]
    ]
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(
        t(user.language, "start_message", name=message.from_user.first_name or ""),
        reply_markup=_main_menu(user.language),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(t(user.language, "help_message"), parse_mode="HTML")


@router.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(
        t(user.language, "choose_lang"), reply_markup=_LANG_KEYBOARD
    )


@router.callback_query(lambda c: c.data and c.data.startswith("lang:"))
async def handle_lang_change(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[1]
    if lang not in ("ru", "kg", "en"):
        await callback.answer()
        return

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(language=lang)
        )
        await session.commit()

    await callback.answer()
    await callback.message.edit_text(t(lang, "lang_changed"))


@router.callback_query(lambda c: c.data == "action:search")
async def handle_search_button(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await callback.message.answer(t(user.language, "search_prompt"))


@router.callback_query(lambda c: c.data == "action:top")
async def handle_top_button(callback: CallbackQuery) -> None:
    from bot.handlers.history import _show_top
    await callback.answer()
    await _show_top(callback.message, callback.from_user)
