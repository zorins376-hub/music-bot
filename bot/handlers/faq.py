"""
faq.py — FAQ section with comprehensive bot guide.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import get_or_create_user
from bot.i18n import t

router = Router()

_SECTIONS = [
    ("search", "◈"),
    ("group", "💬"),
    ("inline", "◎"),
    ("recognize", "🎙"),
    ("charts", "🏆"),
    ("radio", "📻"),
    ("recommend", "◈"),
    ("playlist", "▸"),
    ("video", "🎦"),
    ("quality", "≡"),
    ("premium", "◇"),
    ("profile", "◉"),
    ("commands", "⌘"),
]


def _faq_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(_SECTIONS), 2):
        row = []
        for section, icon in _SECTIONS[i : i + 2]:
            label = t(lang, f"faq_{section}_title").replace("<b>", "").replace("</b>", "")
            row.append(InlineKeyboardButton(text=label, callback_data=f"faq:{section}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "faq_back"), callback_data="faq:back")]]
    )


@router.message(Command("faq"))
async def cmd_faq(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    await message.answer(
        t(lang, "faq_title") + t(lang, "faq_sections"),
        reply_markup=_faq_keyboard(lang),
        parse_mode="HTML",
    )


async def send_faq(message: Message, lang: str) -> None:
    """Send FAQ menu — used from main-menu callback."""
    await message.answer(
        t(lang, "faq_title") + t(lang, "faq_sections"),
        reply_markup=_faq_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("faq:"))
async def handle_faq(callback: CallbackQuery) -> None:
    section = callback.data.split(":")[1]
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if section == "back":
        await callback.message.edit_text(
            t(lang, "faq_title") + t(lang, "faq_sections"),
            reply_markup=_faq_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    key = f"faq_{section}_text"
    text = t(lang, key)
    if text == key:
        await callback.answer()
        return

    title = t(lang, f"faq_{section}_title")
    await callback.message.edit_text(
        f"{title}\n\n{text}",
        reply_markup=_back_button(lang),
        parse_mode="HTML",
    )
    await callback.answer()
