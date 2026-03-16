"""
challenges.py — Weekly challenge system.

Generates rotating weekly challenges, tracks progress via DB queries.
Challenges reset every Monday. No separate storage needed — progress
is computed from existing listening history + favorites + playlists.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from bot.models.base import async_session
from bot.models.favorite import FavoriteTrack
from bot.models.playlist import Playlist
from bot.models.track import ListeningHistory, Track
from bot.models.user import User

logger = logging.getLogger(__name__)

# ── Challenge definitions ────────────────────────────────────────────────
# Each challenge has: id, title (ru/en), target count, XP reward,
# and a query function that returns current progress.

WEEKLY_CHALLENGES = [
    {
        "id": "play_20",
        "title": {"ru": "Послушай 20 треков", "en": "Listen to 20 tracks"},
        "icon": "🎵",
        "target": 20,
        "xp_reward": 15,
    },
    {
        "id": "new_artists_3",
        "title": {"ru": "Открой 3 новых артиста", "en": "Discover 3 new artists"},
        "icon": "🗺️",
        "target": 3,
        "xp_reward": 20,
    },
    {
        "id": "favorites_5",
        "title": {"ru": "Добавь 5 треков в любимое", "en": "Add 5 tracks to favorites"},
        "icon": "❤️",
        "target": 5,
        "xp_reward": 10,
    },
    {
        "id": "genres_3",
        "title": {"ru": "Послушай 3 разных жанра", "en": "Listen to 3 genres"},
        "icon": "🎭",
        "target": 3,
        "xp_reward": 15,
    },
    {
        "id": "night_listen",
        "title": {"ru": "Послушай музыку после полуночи", "en": "Listen after midnight"},
        "icon": "🦉",
        "target": 1,
        "xp_reward": 10,
    },
    {
        "id": "playlist_create",
        "title": {"ru": "Создай плейлист", "en": "Create a playlist"},
        "icon": "📋",
        "target": 1,
        "xp_reward": 10,
    },
    {
        "id": "play_50",
        "title": {"ru": "Послушай 50 треков", "en": "Listen to 50 tracks"},
        "icon": "🔥",
        "target": 50,
        "xp_reward": 30,
    },
    {
        "id": "streak_3",
        "title": {"ru": "Слушай 3 дня подряд", "en": "Listen 3 days in a row"},
        "icon": "⚡",
        "target": 3,
        "xp_reward": 15,
    },
]


def _week_boundaries() -> tuple[datetime, datetime]:
    """Get current week's start (Monday 00:00 UTC) and end (Sunday 23:59 UTC)."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def _week_label() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def _pick_challenges_for_week() -> list[dict]:
    """Pick 4 challenges for the current week (deterministic based on week number)."""
    now = datetime.now(timezone.utc)
    week_num = now.isocalendar()[1]
    # Rotate through challenges, always pick 4
    n = len(WEEKLY_CHALLENGES)
    indices = [(week_num * 3 + i) % n for i in range(4)]
    # Ensure no duplicates
    seen = set()
    result = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(WEEKLY_CHALLENGES[idx])
    # Fill if needed
    for i in range(n):
        if len(result) >= 4:
            break
        if i not in seen:
            seen.add(i)
            result.append(WEEKLY_CHALLENGES[i])
    return result[:4]


async def _get_progress(user_id: int, challenge_id: str, week_start: datetime, week_end: datetime) -> int:
    """Query current progress for a challenge from existing data."""
    async with async_session() as session:
        if challenge_id == "play_20" or challenge_id == "play_50":
            result = await session.execute(
                select(func.count()).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                    ListeningHistory.created_at >= week_start,
                    ListeningHistory.created_at < week_end,
                )
            )
            return result.scalar() or 0

        elif challenge_id == "new_artists_3":
            # Artists listened to this week that weren't listened to before
            this_week = select(func.distinct(Track.artist)).join(
                ListeningHistory, ListeningHistory.track_id == Track.id
            ).where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_start,
                ListeningHistory.created_at < week_end,
                Track.artist.isnot(None),
            ).scalar_subquery()

            before = select(func.distinct(Track.artist)).join(
                ListeningHistory, ListeningHistory.track_id == Track.id
            ).where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at < week_start,
                Track.artist.isnot(None),
            ).scalar_subquery()

            # Count this week's artists not in before-set
            result = await session.execute(
                select(func.count(func.distinct(Track.artist))).join(
                    ListeningHistory, ListeningHistory.track_id == Track.id
                ).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                    ListeningHistory.created_at >= week_start,
                    ListeningHistory.created_at < week_end,
                    Track.artist.isnot(None),
                    Track.artist.notin_(
                        select(Track.artist).join(
                            ListeningHistory, ListeningHistory.track_id == Track.id
                        ).where(
                            ListeningHistory.user_id == user_id,
                            ListeningHistory.action == "play",
                            ListeningHistory.created_at < week_start,
                            Track.artist.isnot(None),
                        )
                    ),
                )
            )
            return result.scalar() or 0

        elif challenge_id == "favorites_5":
            result = await session.execute(
                select(func.count()).where(
                    FavoriteTrack.user_id == user_id,
                    FavoriteTrack.created_at >= week_start,
                    FavoriteTrack.created_at < week_end,
                )
            )
            return result.scalar() or 0

        elif challenge_id == "genres_3":
            result = await session.execute(
                select(func.count(func.distinct(Track.genre))).join(
                    ListeningHistory, ListeningHistory.track_id == Track.id
                ).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                    ListeningHistory.created_at >= week_start,
                    ListeningHistory.created_at < week_end,
                    Track.genre.isnot(None),
                )
            )
            return result.scalar() or 0

        elif challenge_id == "night_listen":
            result = await session.execute(
                select(func.count()).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                    ListeningHistory.created_at >= week_start,
                    ListeningHistory.created_at < week_end,
                    func.extract("hour", ListeningHistory.created_at).between(0, 4),
                )
            )
            return min(1, result.scalar() or 0)

        elif challenge_id == "playlist_create":
            result = await session.execute(
                select(func.count()).where(
                    Playlist.user_id == user_id,
                    Playlist.created_at >= week_start,
                    Playlist.created_at < week_end,
                )
            )
            return min(1, result.scalar() or 0)

        elif challenge_id == "streak_3":
            user = await session.get(User, user_id)
            return min(3, user.streak_days if user else 0)

    return 0


async def get_user_challenges(user_id: int) -> dict:
    """Get active challenges with progress for a user."""
    challenges = _pick_challenges_for_week()
    week_start, week_end = _week_boundaries()

    result = []
    for ch in challenges:
        progress = await _get_progress(user_id, ch["id"], week_start, week_end)
        completed = progress >= ch["target"]
        result.append({
            "id": ch["id"],
            "title": ch["title"],
            "icon": ch["icon"],
            "target": ch["target"],
            "progress": min(progress, ch["target"]),
            "completed": completed,
            "xp_reward": ch["xp_reward"],
        })

    return {
        "challenges": result,
        "week": _week_label(),
        "week_end": week_end.isoformat(),
    }
