"""
weekly_recap.py — Weekly listening recap for users.

Sends a personalized recap every Monday at 10:00 UTC with:
- Total plays this week
- Top 5 artists
- Top 3 genres
- Most played track
- Listening streak
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

_RECAP_HOUR = 10  # UTC Monday morning
_RECAP_WEEKDAY = 0  # Monday


async def start_weekly_recap_scheduler(bot) -> None:
    """Start the background weekly recap loop. Call from on_startup."""
    asyncio.create_task(_recap_loop(bot))


async def _recap_loop(bot) -> None:
    """Run forever, sending weekly recaps on Mondays at 10:00 UTC."""
    while True:
        now = datetime.now(timezone.utc)
        # Calculate next Monday 10:00 UTC
        days_until_monday = (_RECAP_WEEKDAY - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= _RECAP_HOUR:
            days_until_monday = 7
        target = (now + timedelta(days=days_until_monday)).replace(
            hour=_RECAP_HOUR, minute=0, second=0, microsecond=0,
        )
        wait_seconds = (target - now).total_seconds()
        logger.info("Weekly recap next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _send_recaps(bot)
        except Exception as e:
            logger.error("Weekly recap failed: %s", e)


async def _send_recaps(bot) -> None:
    """Build and send weekly recap to active users."""
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.models.track import ListeningHistory, Track
    from bot.i18n import t

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    async with async_session() as session:
        # Get users who played at least 3 tracks this week
        active_users_r = await session.execute(
            select(
                ListeningHistory.user_id,
                func.count(ListeningHistory.id).label("cnt"),
            )
            .where(
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
            )
            .group_by(ListeningHistory.user_id)
            .having(func.count(ListeningHistory.id) >= 3)
        )
        active_users = [(row[0], row[1]) for row in active_users_r.all()]

    if not active_users:
        logger.info("Weekly recap: no active users")
        return

    logger.info("Weekly recap: sending to %d users", len(active_users))
    sent = 0

    for user_id, play_count in active_users:
        try:
            recap_text = await _build_recap_for_user(user_id, play_count, week_ago)
            if recap_text:
                await bot.send_message(user_id, recap_text, parse_mode="HTML")
                sent += 1
        except Exception as e:
            logger.debug("Recap send failed for %s: %s", user_id, e)
        await asyncio.sleep(0.05)

    logger.info("Weekly recap done: sent=%d", sent)


async def _build_recap_for_user(user_id: int, play_count: int, since: datetime) -> str | None:
    """Build the recap message for a single user."""
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.models.track import ListeningHistory, Track
    from bot.i18n import t

    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return None
        lang = user.language or "ru"

        # Top 5 artists
        top_artists_r = await session.execute(
            select(Track.artist, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= since,
                Track.artist.isnot(None),
                Track.artist != "",
            )
            .group_by(Track.artist)
            .order_by(func.count().desc())
            .limit(5)
        )
        top_artists = [(row[0], row[1]) for row in top_artists_r.all()]

        # Most played track
        top_track_r = await session.execute(
            select(Track.artist, Track.title, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= since,
            )
            .group_by(Track.id, Track.artist, Track.title)
            .order_by(func.count().desc())
            .limit(1)
        )
        top_track = top_track_r.first()

        # Top genres
        top_genres_r = await session.execute(
            select(Track.genre, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= since,
                Track.genre.isnot(None),
                Track.genre != "",
            )
            .group_by(Track.genre)
            .order_by(func.count().desc())
            .limit(3)
        )
        top_genres = [(row[0], row[1]) for row in top_genres_r.all()]

    lines = [t(lang, "recap_header")]
    lines.append(t(lang, "recap_total", count=play_count))
    lines.append("")

    if top_track:
        lines.append(t(lang, "recap_top_track", artist=top_track[0] or "?", title=top_track[1] or "?", count=top_track[2]))

    if top_artists:
        lines.append("")
        lines.append(t(lang, "recap_top_artists"))
        for i, (artist, cnt) in enumerate(top_artists, 1):
            lines.append(f"  {i}. {artist} ({cnt})")

    if top_genres:
        lines.append("")
        lines.append(t(lang, "recap_top_genres"))
        for genre, cnt in top_genres:
            lines.append(f"  ▸ {genre} ({cnt})")

    lines.append("")
    lines.append(t(lang, "recap_footer"))

    return "\n".join(lines)
