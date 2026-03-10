"""
achievements.py — Badge system.

Defines badges, checks conditions, awards them.
Called after key events: play, like, playlist creation, etc.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User

logger = logging.getLogger(__name__)

# ── Badge definitions ───────────────────────────────────────────────────

BADGES = {
    "first_play": {
        "name": {"ru": "🎵 Первый трек", "en": "🎵 First Track", "kg": "🎵 Биринчи ыр"},
        "desc": {
            "ru": "Скачал свой первый трек",
            "en": "Downloaded your first track",
            "kg": "Биринчи ырыңды жүктөдүң",
        },
    },
    "meloman_10": {
        "name": {"ru": "🎧 Меломан", "en": "🎧 Melomaniac", "kg": "🎧 Меломан"},
        "desc": {
            "ru": "Послушал 10 треков",
            "en": "Listened to 10 tracks",
            "kg": "10 ыр уктуң",
        },
    },
    "meloman_100": {
        "name": {"ru": "🎶 Аудиофил", "en": "🎶 Audiophile", "kg": "🎶 Аудиофил"},
        "desc": {
            "ru": "Послушал 100 треков",
            "en": "Listened to 100 tracks",
            "kg": "100 ыр уктуң",
        },
    },
    "meloman_500": {
        "name": {"ru": "👑 Легенда", "en": "👑 Legend", "kg": "👑 Легенда"},
        "desc": {
            "ru": "Послушал 500 треков",
            "en": "Listened to 500 tracks",
            "kg": "500 ыр уктуң",
        },
    },
    "first_playlist": {
        "name": {"ru": "📋 Куратор", "en": "📋 Curator", "kg": "📋 Куратор"},
        "desc": {
            "ru": "Создал свой первый плейлист",
            "en": "Created your first playlist",
            "kg": "Биринчи плейлистиңди түздүң",
        },
    },
    "first_like": {
        "name": {"ru": "❤️ Ценитель", "en": "❤️ Appreciator", "kg": "❤️ Баалоочу"},
        "desc": {
            "ru": "Добавил трек в любимое",
            "en": "Added a track to favorites",
            "kg": "Ырды сүйүктүүгө кошту",
        },
    },
    "explorer": {
        "name": {"ru": "🗺️ Исследователь", "en": "🗺️ Explorer", "kg": "🗺️ Изилдөөчү"},
        "desc": {
            "ru": "Слушал 5 разных жанров",
            "en": "Listened to 5 different genres",
            "kg": "5 түрдүү жанр уктуң",
        },
    },
    "night_owl": {
        "name": {"ru": "🦉 Ночная сова", "en": "🦉 Night Owl", "kg": "🦉 Түнкү байкуш"},
        "desc": {
            "ru": "Слушал музыку после полуночи 5 раз",
            "en": "Listened to music after midnight 5 times",
            "kg": "5 жолу түн жарымынан кийин музыка уктуң",
        },
    },
    "streak_7": {
        "name": {"ru": "🔥 7 дней подряд", "en": "🔥 7-Day Streak", "kg": "🔥 7 күн катары"},
        "desc": {
            "ru": "Слушал музыку 7 дней подряд",
            "en": "Listened to music 7 days in a row",
            "kg": "7 күн катары музыка уктуң",
        },
    },
    "referral_3": {
        "name": {"ru": "🤝 Амбассадор", "en": "🤝 Ambassador", "kg": "🤝 Амбассадор"},
        "desc": {
            "ru": "Пригласил 3 друзей",
            "en": "Invited 3 friends",
            "kg": "3 досуңду чакырдың",
        },
    },
}


async def check_and_award_badges(
    user_id: int, event: str
) -> list[str]:
    """Check badge conditions after an event and award new badges.

    event: 'play', 'like', 'playlist_create', 'referral'
    Returns list of newly awarded badge IDs.
    """
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return []

        current_badges = user.badges or []
        new_badges: list[str] = []

        if event == "play":
            # Count total plays
            result = await session.execute(
                select(func.count(ListeningHistory.id)).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                )
            )
            play_count = result.scalar() or 0

            if "first_play" not in current_badges and play_count >= 1:
                new_badges.append("first_play")
            if "meloman_10" not in current_badges and play_count >= 10:
                new_badges.append("meloman_10")
            if "meloman_100" not in current_badges and play_count >= 100:
                new_badges.append("meloman_100")
            if "meloman_500" not in current_badges and play_count >= 500:
                new_badges.append("meloman_500")

            # Night owl: plays between 00:00-05:00
            if "night_owl" not in current_badges:
                result = await session.execute(
                    select(func.count(ListeningHistory.id)).where(
                        ListeningHistory.user_id == user_id,
                        ListeningHistory.action == "play",
                        func.extract("hour", ListeningHistory.created_at).between(0, 4),
                    )
                )
                night_count = result.scalar() or 0
                if night_count >= 5:
                    new_badges.append("night_owl")

            # Explorer: 5 different genres
            if "explorer" not in current_badges:
                result = await session.execute(
                    select(func.count(func.distinct(Track.genre))).where(
                        Track.genre.isnot(None),
                        Track.id.in_(
                            select(ListeningHistory.track_id).where(
                                ListeningHistory.user_id == user_id,
                                ListeningHistory.track_id.isnot(None),
                            )
                        ),
                    )
                )
                genre_count = result.scalar() or 0
                if genre_count >= 5:
                    new_badges.append("explorer")

            # 7-day streak
            if "streak_7" not in current_badges:
                now = datetime.now(timezone.utc)
                streak = 0
                for day_offset in range(7):
                    day_start = (now - timedelta(days=day_offset)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    day_end = day_start + timedelta(days=1)
                    result = await session.execute(
                        select(func.count(ListeningHistory.id)).where(
                            ListeningHistory.user_id == user_id,
                            ListeningHistory.action == "play",
                            ListeningHistory.created_at >= day_start,
                            ListeningHistory.created_at < day_end,
                        )
                    )
                    if (result.scalar() or 0) > 0:
                        streak += 1
                    else:
                        break
                if streak >= 7:
                    new_badges.append("streak_7")

        elif event == "like":
            if "first_like" not in current_badges:
                new_badges.append("first_like")

        elif event == "playlist_create":
            if "first_playlist" not in current_badges:
                new_badges.append("first_playlist")

        elif event == "referral":
            if "referral_3" not in current_badges and (user.referral_count or 0) >= 3:
                new_badges.append("referral_3")

        # Award new badges
        if new_badges:
            updated = current_badges + new_badges
            await session.execute(
                update(User).where(User.id == user_id).values(badges=updated)
            )
            await session.commit()

        return new_badges


def get_badge_display(badge_id: str, lang: str) -> tuple[str, str]:
    """Return (name, description) for a badge in the given language."""
    badge = BADGES.get(badge_id)
    if not badge:
        return (badge_id, "")
    name = badge["name"].get(lang, badge["name"].get("ru", badge_id))
    desc = badge["desc"].get(lang, badge["desc"].get("ru", ""))
    return (name, desc)
