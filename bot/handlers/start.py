from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, update
from sqlalchemy.sql import func

from bot.db import get_or_create_user, is_admin
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory
from bot.models.user import User

router = Router()


def _main_menu(lang: str, admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="▸ TEQUILA LIVE", callback_data="radio:tequila"),
            InlineKeyboardButton(text="◑ FULLMOON LIVE", callback_data="radio:fullmoon"),
        ],
        [
            InlineKeyboardButton(text="✦ AUTO MIX", callback_data="radio:automix"),
            InlineKeyboardButton(text="◈ По вашему вкусу", callback_data="action:recommend"),
        ],
        [
            InlineKeyboardButton(text="◈ Найти трек", callback_data="action:search"),
            InlineKeyboardButton(text="◆ Топ сегодня", callback_data="action:top"),
        ],
        [
            InlineKeyboardButton(text="◇ Premium", callback_data="action:premium"),
            InlineKeyboardButton(text="◉ Профиль", callback_data="action:profile"),
        ],
    ]
    if admin:
        rows.append([
            InlineKeyboardButton(text="◆ Админ-панель", callback_data="action:admin"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    admin = is_admin(message.from_user.id, message.from_user.username)
    await message.answer(
        t(user.language, "start_message", name=message.from_user.first_name or ""),
        reply_markup=_main_menu(user.language, admin=admin),
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


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await _show_profile(message, message.from_user)


@router.callback_query(lambda c: c.data == "action:profile")
async def handle_profile_button(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_profile(callback.message, callback.from_user)


async def _show_profile(message: Message, tg_user) -> None:
    user = await get_or_create_user(tg_user)
    lang = user.language

    # Count user's played tracks
    async with async_session() as session:
        play_count = await session.scalar(
            select(func.count(ListeningHistory.id))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
        ) or 0

    admin = is_admin(tg_user.id, tg_user.username)

    lines = [t(lang, "profile_header")]
    lines.append(t(lang, "profile_name", name=tg_user.first_name or tg_user.username or str(tg_user.id)))

    if admin:
        lines.append(t(lang, "profile_status_admin"))
    elif user.is_premium and user.premium_until:
        lines.append(t(lang, "profile_status_premium", until=user.premium_until.strftime("%d.%m.%Y")))
    elif user.is_premium:
        lines.append(t(lang, "profile_status_premium", until="∞"))
    else:
        lines.append(t(lang, "profile_status_free"))

    lines.append(t(lang, "profile_quality", quality=user.quality))
    lines.append(t(lang, "profile_tracks", count=play_count))
    lines.append(t(lang, "profile_joined", date=user.created_at.strftime("%d.%m.%Y")))

    if user.fav_genres:
        lines.append(t(lang, "profile_genres", genres=", ".join(user.fav_genres)))
    if user.fav_vibe:
        lines.append(t(lang, "profile_vibe", vibe=user.fav_vibe))
    if user.fav_artists:
        lines.append(t(lang, "profile_artists", artists=", ".join(user.fav_artists)))

    await message.answer("\n".join(lines), parse_mode="HTML")
