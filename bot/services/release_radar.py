import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import TrackCallback
from bot.services.cache import cache

logger = logging.getLogger(__name__)

_RADAR_HOUR = 12  # UTC


async def start_release_radar_scheduler(bot) -> None:
    asyncio.create_task(_radar_loop(bot))


async def _radar_loop(bot) -> None:
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=_RADAR_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Release radar next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _send_release_radar(bot)
        except Exception as e:
            logger.error("Release radar failed: %s", e)


async def _send_release_radar(bot) -> None:
    from bot.models.base import async_session
    from bot.models.release_notification import ReleaseNotification
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    async with async_session() as session:
        users_r = await session.execute(
            select(User).where(
                User.captcha_passed == True,
                User.release_radar_enabled == True,
            )
        )
        users = list(users_r.scalars().all())

        if not users:
            return

        tracks_r = await session.execute(
            select(Track).where(Track.created_at >= since).order_by(Track.created_at.desc()).limit(300)
        )
        fresh_tracks = list(tracks_r.scalars().all())
        if not fresh_tracks:
            return

        sent_count = 0
        for user in users:
            preferred_artists = set()
            if user.fav_artists:
                preferred_artists.update(a.strip().lower() for a in user.fav_artists if isinstance(a, str) and a.strip())

            top_artist_r = await session.execute(
                select(Track.artist, func.count(ListeningHistory.id).label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                .where(
                    ListeningHistory.user_id == user.id,
                    ListeningHistory.action == "play",
                    Track.artist.is_not(None),
                )
                .group_by(Track.artist)
                .order_by(func.count(ListeningHistory.id).desc())
                .limit(8)
            )
            preferred_artists.update(
                (row[0] or "").strip().lower() for row in top_artist_r.all() if row[0]
            )

            if not preferred_artists:
                continue

            candidates = []
            for track in fresh_tracks:
                artist = (track.artist or "").strip().lower()
                if not artist:
                    continue
                if any(a in artist or artist in a for a in preferred_artists):
                    candidates.append(track)

            if not candidates:
                continue

            lines = ["🆕 <b>Release Radar</b>", "", "Новые треки артистов, которых ты слушаешь:"]
            notify_tracks: list[dict] = []
            added = 0
            for track in candidates[:5]:
                already = await session.scalar(
                    select(func.count())
                    .select_from(ReleaseNotification)
                    .where(ReleaseNotification.user_id == user.id, ReleaseNotification.track_id == track.id)
                )
                if already:
                    continue
                session.add(
                    ReleaseNotification(
                        user_id=user.id,
                        track_id=track.id,
                        artist=track.artist,
                        title=track.title,
                    )
                )
                lines.append(f"• {track.artist or '?'} — {track.title or '?'}")
                notify_tracks.append(
                    {
                        "video_id": track.source_id,
                        "title": track.title or "Unknown",
                        "uploader": track.artist or "Unknown",
                        "duration": int(track.duration) if track.duration else None,
                        "duration_fmt": f"{track.duration // 60}:{track.duration % 60:02d}" if track.duration else "?:??",
                        "source": track.source or "youtube",
                    }
                )
                added += 1

            if added == 0:
                continue

            session_id = secrets.token_urlsafe(6)
            try:
                await cache.store_search(session_id, notify_tracks)
            except Exception:
                pass

            lines.append("")
            lines.append("/radar — включить/выключить уведомления")
            await session.commit()

            rows = []
            for i, tr in enumerate(notify_tracks[:5]):
                label = f"♪ {(tr.get('uploader') or '?')[:18]} — {(tr.get('title') or '?')[:20]}"
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=label,
                            callback_data=TrackCallback(sid=session_id, i=i).pack(),
                        )
                    ]
                )

            try:
                await bot.send_message(
                    user.id,
                    "\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass

        logger.info("Release radar sent to %d users", sent_count)
