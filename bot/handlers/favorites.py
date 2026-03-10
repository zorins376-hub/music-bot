from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import FavoriteCb
from bot.db import add_favorite_track, get_favorite_tracks, get_or_create_user, remove_favorite_track
from bot.i18n import t
from bot.services.analytics import track_event

router = Router()
_FAVORITES_PAGE_SIZE = 10


def _fmt_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "?:??"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _favorites_page_kb(tracks, page: int, lang: str) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(tracks) + _FAVORITES_PAGE_SIZE - 1) // _FAVORITES_PAGE_SIZE)
    start = page * _FAVORITES_PAGE_SIZE
    end = start + _FAVORITES_PAGE_SIZE

    keyboard_rows = []
    for track in tracks[start:end]:
        title = (track.title or "?")[:18]
        artist = (track.artist or "?")[:20]
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"💔 {artist} — {title}",
                callback_data=FavoriteCb(tid=track.id, act="del").pack(),
            )
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◁", callback_data=f"favpg:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="▷", callback_data=f"favpg:{page + 1}"))
    if nav_row:
        keyboard_rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


async def send_favorites(message: Message, user_id: int, lang: str, page: int = 0, edit: bool = False) -> None:
    tracks = await get_favorite_tracks(user_id, limit=100)
    if not tracks:
        if edit:
            await message.edit_text(t(lang, "favorites_empty"))
        else:
            await message.answer(t(lang, "favorites_empty"))
        return

    total_pages = max(1, (len(tracks) + _FAVORITES_PAGE_SIZE - 1) // _FAVORITES_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    start = page * _FAVORITES_PAGE_SIZE
    end = start + _FAVORITES_PAGE_SIZE

    lines = [t(lang, "favorites_title", count=len(tracks)), ""]
    for i, track in enumerate(tracks[start:end], start + 1):
        title = (track.title or "?")[:35]
        artist = (track.artist or "?")[:25]
        lines.append(f"{i}. {artist} — {title} ({_fmt_duration(track.duration)})")

    if total_pages > 1:
        lines.append("")
        lines.append(f"{page + 1}/{total_pages}")

    kb = _favorites_page_kb(tracks, page, lang)

    if edit:
        await message.edit_text("\n".join(lines), reply_markup=kb)
    else:
        await message.answer("\n".join(lines), reply_markup=kb)


@router.message(Command("favorites"))
async def cmd_favorites(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await send_favorites(message, user.id, user.language)


@router.callback_query(lambda c: isinstance(c.data, str) and c.data.startswith("favpg:"))
async def cb_favorites_page(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    page = 0
    try:
        page = int((callback.data or "favpg:0").split(":", 1)[1])
    except Exception:
        page = 0
    await callback.answer()
    await send_favorites(callback.message, user.id, user.language, page=page, edit=True)


@router.callback_query(FavoriteCb.filter())
async def handle_favorite_action(callback: CallbackQuery, callback_data: FavoriteCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if callback_data.act == "add":
        added = await add_favorite_track(user.id, callback_data.tid)
        await callback.answer(t(lang, "fav_added" if added else "fav_exists"), show_alert=False)
        if added:
            await track_event(user.id, "favorite_add", track_id=callback_data.tid)
            try:
                from bot.services.achievements import check_and_award_badges
                await check_and_award_badges(user.id, "like")
            except Exception:
                pass
            try:
                from bot.services.leaderboard import add_xp, XP_LIKE
                await add_xp(user.id, XP_LIKE)
            except Exception:
                pass
        return

    removed = await remove_favorite_track(user.id, callback_data.tid)
    await callback.answer(t(lang, "fav_removed" if removed else "favorites_empty"), show_alert=False)
    if removed:
        await track_event(user.id, "favorite_remove", track_id=callback_data.tid)
        await send_favorites(callback.message, user.id, user.language, page=0, edit=True)
