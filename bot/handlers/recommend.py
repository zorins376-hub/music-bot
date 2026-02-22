"""
recommend.py — AI DJ «По вашему вкусу».

MVP: показывает топ-треки пользователя из истории.
v1.2: полноценная ML-система на scikit-learn / LightFM.
"""
from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import desc, func, select

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track

router = Router()


@router.callback_query(lambda c: c.data == "action:recommend")
async def handle_recommend(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    # MVP: рекомендации на основе популярных треков пользователя
    async with async_session() as session:
        # Треки которые пользователь слушал чаще всего
        result = await session.execute(
            select(Track, func.count(ListeningHistory.id).label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
            .group_by(Track.id)
            .order_by(desc("cnt"))
            .limit(5)
        )
        rows = result.all()

    if not rows:
        await callback.message.answer(t(lang, "recommend_no_history"), parse_mode="HTML")
        return

    lines = [t(lang, "recommend_header")]
    for i, (track, cnt) in enumerate(rows, 1):
        name = f"{track.artist} — {track.title}" if track.artist else track.title or "Unknown"
        lines.append(f"{i}. {name}")

    lines.append(f"\n{t(lang, 'recommend_footer')}")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
