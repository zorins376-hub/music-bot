from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import FavoriteCb
from bot.db import add_favorite_track, get_favorite_tracks, get_or_create_user, remove_favorite_track
from bot.i18n import t

router = Router()


def _fmt_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "?:??"
    return f"{seconds // 60}:{seconds % 60:02d}"


async def send_favorites(message: Message, user_id: int, lang: str) -> None:
    tracks = await get_favorite_tracks(user_id, limit=30)
    if not tracks:
        await message.answer(t(lang, "favorites_empty"))
        return

    lines = [t(lang, "favorites_title", count=len(tracks)), ""]
    keyboard_rows = []
    for i, track in enumerate(tracks[:20], 1):
        title = (track.title or "?")[:35]
        artist = (track.artist or "?")[:25]
        lines.append(f"{i}. {artist} — {title} ({_fmt_duration(track.duration)})")
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"💔 {artist[:20]} — {title[:18]}",
                callback_data=FavoriteCb(tid=track.id, act="del").pack(),
            )
        ])

    if len(tracks) > 20:
        lines.append(t(lang, "favorites_more", count=len(tracks) - 20))

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


@router.message(Command("favorites"))
async def cmd_favorites(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await send_favorites(message, user.id, user.language)


@router.callback_query(FavoriteCb.filter())
async def handle_favorite_action(callback: CallbackQuery, callback_data: FavoriteCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if callback_data.act == "add":
        added = await add_favorite_track(user.id, callback_data.tid)
        await callback.answer(t(lang, "fav_added" if added else "fav_exists"), show_alert=False)
        if added:
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
