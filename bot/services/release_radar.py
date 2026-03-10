import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import TrackCallback
from bot.i18n import t
from bot.services.cache import cache

logger = logging.getLogger(__name__)

_RADAR_INTERVAL_HOURS = 6


async def start_release_radar_scheduler(bot) -> None:
    asyncio.create_task(_radar_loop(bot))


async def _radar_loop(bot) -> None:
    while True:
        now = datetime.now(timezone.utc)
        target = _next_radar_target(now)
        wait_seconds = (target - now).total_seconds()
        logger.info("Release radar next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _send_release_radar(bot)
        except Exception as e:
            logger.error("Release radar failed: %s", e)


def _next_radar_target(now: datetime) -> datetime:
    current = now.astimezone(timezone.utc)
    base = current.replace(minute=0, second=0, microsecond=0)
    next_hour = ((base.hour // _RADAR_INTERVAL_HOURS) + 1) * _RADAR_INTERVAL_HOURS
    if next_hour >= 24:
        return (base + timedelta(days=1)).replace(hour=0)
    return base.replace(hour=next_hour)


async def _send_release_radar(bot) -> None:
    from bot.models.artist_watchlist import ArtistWatchlist
    from bot.models.base import async_session
    from bot.models.release_notification import ReleaseNotification
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    from collections import defaultdict

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

        user_ids = [u.id for u in users]
        fresh_track_ids = [t.id for t in fresh_tracks]

        await _rebuild_watchlist_for_users(session, users)

        watchlist_r = await session.execute(
            select(ArtistWatchlist.user_id, ArtistWatchlist.normalized_name)
            .where(ArtistWatchlist.user_id.in_(user_ids))
            .order_by(ArtistWatchlist.weight.desc())
        )
        user_watchlist: dict[int, list[str]] = defaultdict(list)
        for row in watchlist_r.all():
            if len(user_watchlist[row[0]]) < 8 and row[1]:
                user_watchlist[row[0]].append(row[1])

        # Batch: existing notifications for all user+fresh_track combos
        existing_notif_r = await session.execute(
            select(ReleaseNotification.user_id, ReleaseNotification.track_id).where(
                ReleaseNotification.user_id.in_(user_ids),
                ReleaseNotification.track_id.in_(fresh_track_ids),
            )
        )
        existing_notifs: set[tuple[int, int]] = {
            (row[0], row[1]) for row in existing_notif_r.all()
        }

        sent_count = 0
        for user in users:
            preferred_artists: set[str] = set()
            if user.fav_artists:
                preferred_artists.update(
                    _normalize_artist_name(a)
                    for a in user.fav_artists
                    if isinstance(a, str) and a.strip()
                )
            preferred_artists.update(a for a in user_watchlist.get(user.id, []) if a)

            if not preferred_artists:
                continue

            candidates = []
            for track in fresh_tracks:
                artist = _normalize_artist_name(track.artist or "")
                if not artist:
                    continue
                if any(a in artist or artist in a for a in preferred_artists):
                    candidates.append(track)

            if not candidates:
                continue

            lang = user.language or "ru"
            lines = [
                t(lang, "radar_notify_title"),
                "",
                t(lang, "radar_notify_intro"),
            ]
            notify_tracks: list[dict] = []
            added = 0
            for track in candidates[:5]:
                if (user.id, track.id) in existing_notifs:
                    continue
                session.add(
                    ReleaseNotification(
                        user_id=user.id,
                        track_id=track.id,
                        artist=track.artist,
                        title=track.title,
                    )
                )
                existing_notifs.add((user.id, track.id))
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
            lines.append(t(lang, "radar_notify_footer"))
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
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(lang, "radar_disable_btn"),
                        callback_data="radar:disable",
                    ),
                    InlineKeyboardButton(
                        text=t(lang, "radar_open_btn"),
                        callback_data="radar:open",
                    ),
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(lang, "radar_mix_btn"),
                        callback_data="action:mix",
                    )
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(lang, "radar_favorites_btn"),
                        callback_data="action:favorites",
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


def _normalize_artist_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


async def _rebuild_watchlist_for_users(session, users) -> None:
    from bot.models.artist_watchlist import ArtistWatchlist
    from bot.models.track import ListeningHistory, Track

    user_ids = [u.id for u in users]
    if not user_ids:
        return

    top_artists_r = await session.execute(
        select(
            ListeningHistory.user_id,
            Track.artist,
            func.count(ListeningHistory.id).label("cnt"),
        )
        .join(ListeningHistory, ListeningHistory.track_id == Track.id)
        .where(
            ListeningHistory.user_id.in_(user_ids),
            ListeningHistory.action == "play",
            Track.artist.is_not(None),
        )
        .group_by(ListeningHistory.user_id, Track.artist)
        .order_by(ListeningHistory.user_id, func.count(ListeningHistory.id).desc())
    )

    from collections import defaultdict

    top_artists_map: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for user_id, artist, cnt in top_artists_r.all():
        if artist and len(top_artists_map[user_id]) < 8:
            top_artists_map[user_id].append((artist, float(cnt or 0)))

    for user in users:
        signal_rows = []
        for artist_name, cnt in top_artists_map.get(user.id, []):
            signal_rows.append((artist_name, cnt, "history"))

        if getattr(user, "fav_artists", None):
            for fav_artist in user.fav_artists:
                if isinstance(fav_artist, str) and fav_artist.strip():
                    signal_rows.append((fav_artist, 5.0, "favorite"))

        ranked = _rank_watchlist_candidates(signal_rows)

        await session.execute(delete(ArtistWatchlist).where(ArtistWatchlist.user_id == user.id))
        for artist_name, norm_name, weight, source in ranked[:8]:
            session.add(
                ArtistWatchlist(
                    user_id=user.id,
                    artist_name=artist_name,
                    normalized_name=norm_name,
                    weight=weight,
                    source=source,
                )
            )

    await session.commit()


def _rank_watchlist_candidates(rows: list[tuple[str, float, str]]) -> list[tuple[str, str, float, str]]:
    merged: dict[str, tuple[str, float, str]] = {}
    for artist_name, weight, source in rows:
        normalized = _normalize_artist_name(artist_name)
        if not normalized:
            continue
        current = merged.get(normalized)
        if current is None:
            merged[normalized] = (artist_name.strip(), weight, source)
        else:
            prev_name, prev_weight, prev_source = current
            new_weight = prev_weight + weight
            new_source = "favorite" if prev_source == "favorite" or source == "favorite" else "history"
            merged[normalized] = (prev_name, new_weight, new_source)

    ranked = [
        (name, normalized, weight, source)
        for normalized, (name, weight, source) in merged.items()
    ]
    ranked.sort(key=lambda x: x[2], reverse=True)
    return ranked
