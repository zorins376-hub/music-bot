import logging

from aiogram.types import User as TgUser
from datetime import datetime, timedelta, timezone
from sqlalchemy import case, desc, or_, select, text, update
from sqlalchemy.sql import func

from bot.config import settings

logger = logging.getLogger(__name__)
from bot.models.base import async_session
from bot.models.admin_log import AdminLog
from bot.models.favorite import FavoriteTrack
from bot.models.track import ListeningHistory, Track
from bot.models.user import User


def is_admin(user_id: int, username: str | None = None) -> bool:
    """Check if user is admin by ID or username."""
    if user_id in settings.ADMIN_IDS:
        return True
    if username and username.lower() in [u.lower() for u in settings.ADMIN_USERNAMES]:
        return True
    return False


async def persist_admin_id(user_id: int) -> None:
    """Save admin user_id to Redis for persistence across restarts."""
    try:
        from bot.services.cache import cache
        await cache.redis.sadd("bot:admin_ids", str(user_id))
    except Exception as e:
        logger.debug("persist_admin_id failed: %s", e)


async def load_admin_ids_from_redis() -> None:
    """Load persisted admin IDs from Redis into settings.ADMIN_IDS on startup."""
    try:
        from bot.services.cache import cache
        stored = await cache.redis.smembers("bot:admin_ids")
        if stored:
            for sid in stored:
                try:
                    uid = int(sid)
                    if uid not in settings.ADMIN_IDS:
                        settings.ADMIN_IDS.append(uid)
                except (ValueError, TypeError):
                    pass
            logger.info("Loaded %d admin IDs from Redis", len(stored))
    except Exception as e:
        logger.debug("load_admin_ids_from_redis failed: %s", e)


async def get_or_create_user(tg_user: TgUser) -> User:
    admin = is_admin(tg_user.id, tg_user.username)
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == tg_user.id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                is_premium=admin,
                is_admin=admin,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Calculate all updates in one single query
            expired_premium = (
                not admin
                and user.is_premium
                and user.premium_until is not None
                and user.premium_until < now
            )
            # BUG-005: premium=True but no expiry and not admin → revoke
            orphaned_premium = (
                not admin
                and user.is_premium
                and user.premium_until is None
            )
            update_values: dict = {
                "username": tg_user.username,
                "first_name": tg_user.first_name,
                "last_active": now,
            }
            # Sync admin flag from config → DB
            if admin and not user.is_admin:
                update_values["is_admin"] = True
            if not admin and user.is_admin:
                update_values["is_admin"] = False
            if admin and not user.is_premium:
                update_values["is_premium"] = True
            if expired_premium or orphaned_premium:
                update_values["is_premium"] = False

            await session.execute(
                update(User).where(User.id == tg_user.id).values(**update_values)
            )
            await session.commit()

            # Reflect changes on the in-memory object
            if "is_premium" in update_values:
                user.is_premium = update_values["is_premium"]
            if "is_admin" in update_values:
                user.is_admin = update_values["is_admin"]

        # Keep in-memory list in sync for fast checks elsewhere
        if user.is_admin and tg_user.id not in settings.ADMIN_IDS:
            settings.ADMIN_IDS.append(tg_user.id)
            await persist_admin_id(tg_user.id)

        return user


async def increment_request_count(user_id: int) -> None:
    try:
        async with async_session() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(request_count=User.request_count + 1)
            )
            await session.commit()
    except Exception as e:
        logger.warning("increment_request_count failed for %s: %s", user_id, e)


async def record_listening_event(
    user_id: int,
    track_id: int | None = None,
    query: str | None = None,
    action: str = "play",
    source: str = "search",
    listen_duration: int | None = None,
) -> None:
    try:
        async with async_session() as session:
            session.add(
                ListeningHistory(
                    user_id=user_id,
                    track_id=track_id,
                    query=query,
                    action=action,
                    source=source,
                    listen_duration=listen_duration,
                )
            )
            await session.commit()
        # Check badges on play events (fire-and-forget)
        if action == "play":
            try:
                from bot.services.achievements import check_and_award_badges
                await check_and_award_badges(user_id, "play")
            except Exception:
                pass
            # XP + streak update
            try:
                from bot.services.leaderboard import add_xp, XP_PLAY
                await add_xp(user_id, XP_PLAY)
                await _update_streak_and_xp(user_id, XP_PLAY)
            except Exception:
                pass
            # Auto-update profile every 10 plays
            try:
                play_count = await _get_user_play_count(user_id)
                if play_count > 0 and play_count % 10 == 0:
                    from recommender.profile_updater import trigger_profile_update
                    trigger_profile_update(user_id)
            except Exception:
                pass
    except Exception as e:
        logger.warning("record_listening_event failed for user %s: %s", user_id, e)


async def _get_user_play_count(user_id: int) -> int:
    """Get total play count for user (for profile update trigger)."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(ListeningHistory)
                .where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                )
            )
            return result.scalar() or 0
    except Exception:
        return 0


async def _update_streak_and_xp(user_id: int, xp_amount: int) -> None:
    """Update user's XP, level, and streak in the database."""
    from datetime import date
    from bot.services.leaderboard import calc_level

    try:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return
            today = date.today()
            new_xp = (user.xp or 0) + xp_amount
            new_level = calc_level(new_xp)

            vals: dict = {"xp": new_xp, "level": new_level}

            if user.last_play_date is None:
                vals["streak_days"] = 1
                vals["last_play_date"] = today
            elif user.last_play_date == today:
                pass  # Already played today
            elif (today - user.last_play_date).days == 1:
                vals["streak_days"] = (user.streak_days or 0) + 1
                vals["last_play_date"] = today
            else:
                vals["streak_days"] = 1  # Streak broken
                vals["last_play_date"] = today

            await session.execute(update(User).where(User.id == user_id).values(**vals))
            await session.commit()
    except Exception as e:
        logger.debug("_update_streak_and_xp failed: %s", e)


async def upsert_track(
    source_id: str,
    title: str | None = None,
    artist: str | None = None,
    duration: int | None = None,
    file_id: str | None = None,
    source: str = "youtube",
    channel: str | None = None,
    genre: str | None = None,
    bpm: int | None = None,
) -> Track:
    async with async_session() as session:
        result = await session.execute(
            select(Track).where(Track.source_id == source_id)
        )
        track = result.scalar_one_or_none()

        if track is None:
            track = Track(
                source_id=source_id,
                title=title,
                artist=artist,
                duration=duration,
                file_id=file_id,
                source=source,
                channel=channel,
                genre=genre,
                bpm=bpm,
                downloads=1,
            )
            session.add(track)
        else:
            await session.execute(
                update(Track)
                .where(Track.source_id == source_id)
                .values(
                    file_id=file_id or track.file_id,
                    downloads=Track.downloads + 1,
                )
            )
        await session.commit()
        await session.refresh(track)
        return track


async def get_user_stats(user_id: int) -> dict:
    """Return personal play statistics for a user (single optimized query)."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(weeks=1)
    async with async_session() as session:
        # Single query with scalar subqueries for total, week, and top artist
        total_sub = (
            select(func.count(ListeningHistory.id))
            .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            .correlate()
            .scalar_subquery()
        )
        week_sub = (
            select(func.count(ListeningHistory.id))
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
            )
            .correlate()
            .scalar_subquery()
        )
        top_sub = (
            select(Track.artist)
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.artist.isnot(None),
                Track.artist != "",
            )
            .group_by(Track.artist)
            .order_by(desc(func.count(ListeningHistory.id)))
            .limit(1)
            .correlate()
            .scalar_subquery()
        )
        row = (await session.execute(
            select(total_sub.label("total"), week_sub.label("week"), top_sub.label("top_artist"))
        )).first()

    return {
        "total": row.total if row else 0,
        "week": row.week if row else 0,
        "top_artist": row.top_artist if row else None,
    }


async def search_local_tracks(query: str, limit: int = 5) -> list[Track]:
    """Search tracks in local DB with fuzzy matching + transliteration."""
    from bot.models.base import _is_pg
    from bot.services.search_engine import (
        detect_script, normalize_query, transliterate_cyr_to_lat, transliterate_lat_to_cyr,
    )

    norm = normalize_query(query)
    queries = [norm]
    script = detect_script(norm)
    if script == "cyrillic":
        queries.append(transliterate_cyr_to_lat(norm))
    elif script == "latin":
        queries.append(transliterate_lat_to_cyr(norm))

    async with async_session() as session:
        if _is_pg:
            # PostgreSQL: use pg_trgm similarity for fuzzy matching
            combined = func.lower(func.concat(func.coalesce(Track.artist, ''), ' ', func.coalesce(Track.title, '')))
            conditions = []
            for q in queries:
                conditions.append(func.similarity(combined, q) > 0.15)
                conditions.append(combined.ilike(f"%{q}%"))
            result = await session.execute(
                select(Track)
                .where(or_(*conditions))
                .order_by(
                    case(
                        (Track.channel == "tequila", 0),
                        (Track.channel == "fullmoon", 1),
                        else_=2,
                    ),
                    func.similarity(combined, norm).desc(),
                    Track.downloads.desc(),
                )
                .limit(limit)
            )
        else:
            # SQLite fallback: ILIKE on all query variants
            conditions = []
            for q in queries:
                pat = f"%{q}%"
                conditions.append(Track.title.ilike(pat))
                conditions.append(Track.artist.ilike(pat))
            result = await session.execute(
                select(Track)
                .where(or_(*conditions))
                .order_by(
                    case(
                        (Track.channel == "tequila", 0),
                        (Track.channel == "fullmoon", 1),
                        else_=2,
                    ),
                    Track.downloads.desc(),
                )
                .limit(limit)
            )
        return list(result.scalars().all())


async def get_popular_titles(limit: int = 500) -> list[str]:
    """Return popular 'artist - title' strings for suggestion corpus."""
    async with async_session() as session:
        result = await session.execute(
            select(
                func.coalesce(Track.artist, ''),
                func.coalesce(Track.title, ''),
            )
            .order_by(Track.downloads.desc())
            .limit(limit)
        )
        return [
            f"{artist} - {title}".strip(" -")
            for artist, title in result.all()
            if artist or title
        ]


async def log_admin_action(
    admin_id: int, action: str, target_user_id: int | None = None, details: str | None = None,
) -> None:
    """Write an admin audit log entry."""
    async with async_session() as session:
        session.add(AdminLog(
            admin_id=admin_id,
            action=action,
            target_user_id=target_user_id,
            details=details,
        ))
        await session.commit()


async def add_favorite_track(user_id: int, track_id: int) -> bool:
    """Add track to favorites. Returns True if added, False if it already exists."""
    async with async_session() as session:
        exists = await session.scalar(
            select(func.count())
            .select_from(FavoriteTrack)
            .where(FavoriteTrack.user_id == user_id, FavoriteTrack.track_id == track_id)
        )
        if exists:
            return False
        session.add(FavoriteTrack(user_id=user_id, track_id=track_id))
        await session.commit()
        return True


async def remove_favorite_track(user_id: int, track_id: int) -> bool:
    """Remove track from favorites. Returns True if removed."""
    async with async_session() as session:
        result = await session.execute(
            select(FavoriteTrack).where(
                FavoriteTrack.user_id == user_id,
                FavoriteTrack.track_id == track_id,
            )
        )
        fav = result.scalar_one_or_none()
        if fav is None:
            return False
        await session.delete(fav)
        await session.commit()
        return True


async def get_favorite_tracks(user_id: int, limit: int = 50) -> list[Track]:
    """Return user's favorite tracks ordered by newest first."""
    async with async_session() as session:
        result = await session.execute(
            select(Track)
            .join(FavoriteTrack, FavoriteTrack.track_id == Track.id)
            .where(FavoriteTrack.user_id == user_id)
            .order_by(FavoriteTrack.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def get_admin_logs(limit: int = 20) -> list[AdminLog]:
    """Return the most recent admin log entries."""
    async with async_session() as session:
        result = await session.execute(
            select(AdminLog).order_by(AdminLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
