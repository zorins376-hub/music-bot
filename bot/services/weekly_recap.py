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
    """Build and send weekly recap to active users (batch-optimized)."""
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.models.track import ListeningHistory, Track
    from bot.i18n import t
    from collections import defaultdict

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
        active_users = {row[0]: row[1] for row in active_users_r.all()}

    if not active_users:
        logger.info("Weekly recap: no active users")
        return

    user_ids = list(active_users.keys())
    logger.info("Weekly recap: sending to %d users", len(user_ids))

    # Batch queries for all active users at once
    async with async_session() as session:
        # Fetch user languages
        users_r = await session.execute(
            select(User.id, User.language).where(User.id.in_(user_ids))
        )
        user_langs = {row[0]: row[1] or "ru" for row in users_r.all()}

        # Top artists per user (batch: top 5 per user via window function)
        from sqlalchemy import literal_column
        top_artists_r = await session.execute(
            select(
                ListeningHistory.user_id,
                Track.artist,
                func.count().label("cnt"),
            )
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id.in_(user_ids),
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
                Track.artist.isnot(None),
                Track.artist != "",
            )
            .group_by(ListeningHistory.user_id, Track.artist)
            .order_by(ListeningHistory.user_id, func.count().desc())
        )
        # Group and limit to top 5 per user
        user_top_artists: dict[int, list[tuple]] = defaultdict(list)
        for row in top_artists_r.all():
            if len(user_top_artists[row[0]]) < 5:
                user_top_artists[row[0]].append((row[1], row[2]))

        # Top track per user (batch)
        top_tracks_r = await session.execute(
            select(
                ListeningHistory.user_id,
                Track.artist,
                Track.title,
                func.count().label("cnt"),
            )
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id.in_(user_ids),
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
            )
            .group_by(ListeningHistory.user_id, Track.id, Track.artist, Track.title)
            .order_by(ListeningHistory.user_id, func.count().desc())
        )
        user_top_track: dict[int, tuple] = {}
        for row in top_tracks_r.all():
            if row[0] not in user_top_track:
                user_top_track[row[0]] = (row[1], row[2], row[3])

        # Top genres per user (batch)
        top_genres_r = await session.execute(
            select(
                ListeningHistory.user_id,
                Track.genre,
                func.count().label("cnt"),
            )
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id.in_(user_ids),
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
                Track.genre.isnot(None),
                Track.genre != "",
            )
            .group_by(ListeningHistory.user_id, Track.genre)
            .order_by(ListeningHistory.user_id, func.count().desc())
        )
        user_top_genres: dict[int, list[tuple]] = defaultdict(list)
        for row in top_genres_r.all():
            if len(user_top_genres[row[0]]) < 3:
                user_top_genres[row[0]].append((row[1], row[2]))

    # Build and send recaps
    sent = 0
    for user_id in user_ids:
        try:
            lang = user_langs.get(user_id, "ru")
            play_count = active_users[user_id]

            lines = [t(lang, "recap_header")]
            lines.append(t(lang, "recap_total", count=play_count))
            lines.append("")

            top_track = user_top_track.get(user_id)
            if top_track:
                lines.append(t(lang, "recap_top_track", artist=top_track[0] or "?", title=top_track[1] or "?", count=top_track[2]))

            artists = user_top_artists.get(user_id, [])
            if artists:
                lines.append("")
                lines.append(t(lang, "recap_top_artists"))
                for i, (artist, cnt) in enumerate(artists, 1):
                    lines.append(f"  {i}. {artist} ({cnt})")

            genres = user_top_genres.get(user_id, [])
            if genres:
                lines.append("")
                lines.append(t(lang, "recap_top_genres"))
                for genre, cnt in genres:
                    lines.append(f"  ▸ {genre} ({cnt})")

            lines.append("")
            lines.append(t(lang, "recap_footer"))

            await bot.send_message(user_id, "\n".join(lines), parse_mode="HTML")

            # Send visual story card
            try:
                from bot.services.story_cards import generate_recap_card
                top_artist_names = [a for a, _ in artists]
                top_track_str = f"{top_track[0]} — {top_track[1]}" if top_track else ""
                card_bytes = generate_recap_card(
                    user_name=f"@{user_id}",
                    play_count=play_count,
                    top_artists=top_artist_names,
                    top_track=top_track_str,
                )
                if card_bytes:
                    from aiogram.types import BufferedInputFile
                    photo = BufferedInputFile(card_bytes, filename="recap.png")
                    await bot.send_photo(user_id, photo)
            except Exception as e:
                logger.debug("Story card send failed for %s: %s", user_id, e)

            sent += 1
        except Exception as e:
            logger.debug("Recap send failed for %s: %s", user_id, e)
        await asyncio.sleep(0.05)

    logger.info("Weekly recap done: sent=%d", sent)
