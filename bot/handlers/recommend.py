"""
recommend.py — AI DJ «По вашему вкусу» + Onboarding.

Onboarding: 3 вопроса для новых пользователей (стиль, вайб, артисты).
Recommendations: на основе истории + профиля пользователя.
"""
import secrets

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, func, select, update

from bot.db import get_or_create_user, record_listening_event
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User
from bot.services.cache import cache
from bot.services.downloader import search_tracks

router = Router()

# ── Onboarding states ───────────────────────────────────────────────────

class OnboardState(StatesGroup):
    waiting_artists = State()


_GENRE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="▪ Электро", callback_data="ob_genre:electro"),
            InlineKeyboardButton(text="▪ Хип-хоп", callback_data="ob_genre:hiphop"),
            InlineKeyboardButton(text="♪ Pop", callback_data="ob_genre:pop"),
        ],
        [
            InlineKeyboardButton(text="▪ Rock", callback_data="ob_genre:rock"),
            InlineKeyboardButton(text="▪ R&B", callback_data="ob_genre:rnb"),
            InlineKeyboardButton(text="◑ Lo-fi", callback_data="ob_genre:lofi"),
        ],
        [
            InlineKeyboardButton(text="▪ Latin", callback_data="ob_genre:latin"),
            InlineKeyboardButton(text="▪ Классика", callback_data="ob_genre:classical"),
        ],
    ]
)

_VIBE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="◑ Ночной / Deep", callback_data="ob_vibe:deep"),
            InlineKeyboardButton(text="▸ Энергичный", callback_data="ob_vibe:energy"),
        ],
        [
            InlineKeyboardButton(text="○ Спокойный", callback_data="ob_vibe:chill"),
            InlineKeyboardButton(text="✧ Микс", callback_data="ob_vibe:mix"),
        ],
    ]
)


@router.callback_query(lambda c: c.data == "action:recommend")
async def handle_recommend(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    # If user not onboarded and no history — start onboarding
    if not user.onboarded:
        async with async_session() as session:
            result = await session.execute(
                select(func.count(ListeningHistory.id))
                .where(
                    ListeningHistory.user_id == user.id,
                    ListeningHistory.action == "play",
                )
            )
            play_count = result.scalar() or 0

        if play_count < 3:
            await callback.message.answer(
                t(lang, "onboard_q1"),
                reply_markup=_GENRE_KEYBOARD,
                parse_mode="HTML",
            )
            return

    # Show recommendations
    await _show_recommendations(callback.message, user)


@router.callback_query(lambda c: c.data and c.data.startswith("ob_genre:"))
async def handle_genre_select(callback: CallbackQuery, state: FSMContext) -> None:
    genre = callback.data.split(":")[1]
    await callback.answer()

    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        current = await session.get(User, user.id)
        genres = current.fav_genres or []
        if genre not in genres:
            genres.append(genre)
        await session.execute(
            update(User).where(User.id == user.id).values(fav_genres=genres)
        )
        await session.commit()

    await callback.message.edit_text(
        t(lang, "onboard_q2"),
        reply_markup=_VIBE_KEYBOARD,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("ob_vibe:"))
async def handle_vibe_select(callback: CallbackQuery, state: FSMContext) -> None:
    vibe = callback.data.split(":")[1]
    await callback.answer()

    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(fav_vibe=vibe)
        )
        await session.commit()

    await callback.message.edit_text(
        t(lang, "onboard_q3"),
        parse_mode="HTML",
    )
    await state.set_state(OnboardState.waiting_artists)


@router.message(OnboardState.waiting_artists)
async def handle_artists_input(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    # Parse comma-separated artists (max 5)
    raw = message.text or ""
    artists = [a.strip() for a in raw.split(",") if a.strip()][:5]

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(
                fav_artists=artists if artists else None,
                onboarded=True,
            )
        )
        await session.commit()

    await state.clear()
    await message.answer(t(lang, "onboard_done"), parse_mode="HTML")


async def _show_recommendations(message: Message, user: User) -> None:
    lang = user.language

    async with async_session() as session:
        # Recommendations based on user's most played tracks
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
        personal_rows = result.all()

        # If user has genres set, also find popular tracks in those genres
        genre_tracks = []
        if user.fav_genres:
            genre_result = await session.execute(
                select(Track)
                .where(Track.genre.in_(user.fav_genres))
                .order_by(Track.downloads.desc())
                .limit(5)
            )
            genre_tracks = genre_result.scalars().all()

    # Build combined track list
    all_tracks: list[dict] = []
    seen_ids: set[str] = set()

    for track, _cnt in personal_rows:
        if track.source_id not in seen_ids:
            seen_ids.add(track.source_id)
            all_tracks.append({
                "video_id": track.source_id,
                "title": track.title or "Unknown",
                "uploader": track.artist or "Unknown",
                "duration": track.duration or 0,
                "duration_fmt": _fmt_dur(track.duration),
                "source": track.source or "youtube",
                "file_id": track.file_id,
            })

    for track in genre_tracks:
        if track.source_id not in seen_ids and len(all_tracks) < 10:
            seen_ids.add(track.source_id)
            all_tracks.append({
                "video_id": track.source_id,
                "title": track.title or "Unknown",
                "uploader": track.artist or "Unknown",
                "duration": track.duration or 0,
                "duration_fmt": _fmt_dur(track.duration),
                "source": track.source or "youtube",
                "file_id": track.file_id,
            })

    # If nothing found in DB, search YouTube by fav artists/genres
    if not all_tracks and user.fav_artists:
        query = " ".join(user.fav_artists[:2])
        yt_results = await search_tracks(query, max_results=5, source="youtube")
        all_tracks.extend(yt_results)
    elif not all_tracks and user.fav_genres:
        genre_to_query = {
            "electro": "electronic music mix",
            "hiphop": "hip hop trending",
            "pop": "pop hits 2026",
            "rock": "rock music",
            "rnb": "r&b music",
            "lofi": "lo-fi chill beats",
            "latin": "latin music hits",
            "classical": "classical music",
        }
        genre_key = user.fav_genres[0] if user.fav_genres else "pop"
        query = genre_to_query.get(genre_key, "trending music")
        yt_results = await search_tracks(query, max_results=5, source="youtube")
        all_tracks.extend(yt_results)

    if not all_tracks:
        await message.answer(t(lang, "recommend_no_history"), parse_mode="HTML")
        return

    # Store in search cache so user can click and download
    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, all_tracks)
    await record_listening_event(
        user_id=user.id, action="search", source="recommend"
    )

    # Build clickable keyboard (import TrackCallback from search handler)
    from bot.handlers.search import TrackCallback

    buttons = []
    for i, tr in enumerate(all_tracks[:10]):
        dur = tr.get("duration_fmt", "?:??")
        label = f"♪ {tr['uploader']} — {tr['title'][:35]} ({dur})"
        buttons.append(
            [InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        f"{t(lang, 'recommend_header')}\n\n{t(lang, 'recommend_footer')}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


def _fmt_dur(seconds: int | None) -> str:
    if not seconds:
        return "?:??"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
