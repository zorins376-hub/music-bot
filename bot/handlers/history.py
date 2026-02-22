from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, User as TgUser
from sqlalchemy import desc, select

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track

router = Router()


async def _show_top(message: Message, tg_user: TgUser) -> None:
    user = await get_or_create_user(tg_user)
    lang = user.language

    async with async_session() as session:
        result = await session.execute(
            select(Track)
            .where(Track.downloads > 0)
            .order_by(desc(Track.downloads))
            .limit(10)
        )
        tracks = result.scalars().all()

    if not tracks:
        await message.answer(t(lang, "top_empty"))
        return

    lines = [t(lang, "top_header")]
    for i, track in enumerate(tracks, 1):
        name = f"{track.artist} — {track.title}" if track.artist else track.title or "Unknown"
        lines.append(f"{i}. {name} ({track.downloads} скач.)")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    async with async_session() as session:
        result = await session.execute(
            select(ListeningHistory)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
            .order_by(desc(ListeningHistory.created_at))
            .limit(10)
        )
        records = result.scalars().all()

    if not records:
        await message.answer(t(lang, "history_empty"))
        return

    lines = [t(lang, "history_header")]
    for i, rec in enumerate(records, 1):
        label = rec.query or f"Track #{rec.track_id}"
        lines.append(f"{i}. {label}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    await _show_top(message, message.from_user)
