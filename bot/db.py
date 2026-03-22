import logging
import asyncio

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


def _fire_and_log_task(coro, context: str) -> None:
    task = asyncio.create_task(coro)

    def _on_done(done: asyncio.Task) -> None:
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.debug("Background task failed (%s): %s", context, exc)

    task.add_done_callback(_on_done)


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
    return await get_or_create_user_raw(tg_user.id, tg_user.username, tg_user.first_name)


async def get_or_create_user_raw(
    user_id: int, username: str | None, first_name: str | None = ""
) -> User:
    """Shared user upsert — used by both bot middleware and webapp API."""
    from sqlalchemy.exc import IntegrityError

    admin = is_admin(user_id, username)
    now = datetime.now(timezone.utc)
    touch_interval = timedelta(seconds=60)

    for attempt in range(3):
        try:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if user is None:
                    user = User(
                        id=user_id,
                        username=username,
                        first_name=first_name,
                        is_premium=admin,
                        is_admin=admin,
                    )
                    session.add(user)
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
                        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
                        if user is None:
                            raise
                        return user
                    await session.refresh(user)
                    # Mirror new user to Supabase
                    try:
                        from bot.services.supabase_mirror import mirror_user
                        mirror_user(user.id, username=user.username, first_name=user.first_name,
                                    is_premium=user.is_premium, is_admin=user.is_admin)
                    except Exception:
                        logger.debug("mirror_user failed for new user %s", user.id, exc_info=True)
                else:
                    changed = False
                    if user.username != username:
                        user.username = username
                        changed = True
                    if user.first_name != first_name:
                        user.first_name = first_name
                        changed = True
                    if user.is_admin != admin:
                        user.is_admin = admin
                        changed = True

                    if user.last_active is None or (now - user.last_active) >= touch_interval:
                        user.last_active = now
                        changed = True

                    expired_premium = (
                        not admin
                        and user.is_premium
                        and user.premium_until is not None
                        and user.premium_until < now
                    )
                    if admin and not user.is_premium:
                        user.is_premium = True
                        changed = True
                    if expired_premium:
                        user.is_premium = False
                        changed = True

                    if changed:
                        try:
                            await session.commit()
                        except Exception:
                            await session.rollback()
                            raise
                    # Mirror user update to Supabase
                    try:
                        from bot.services.supabase_mirror import mirror_user
                        mirror_user(user_id, username=username, first_name=first_name,
                                    is_premium=user.is_premium, is_admin=user.is_admin)
                    except Exception:
                        logger.debug("mirror_user failed for updated user %s", user_id, exc_info=True)

                # Keep in-memory list in sync for fast checks elsewhere
                if user.is_admin and user_id not in settings.ADMIN_IDS:
                    settings.ADMIN_IDS.append(user_id)
                    await persist_admin_id(user_id)
                    logger.info("Admin ID added at runtime: user_id=%s username=%s", user_id, username)

                return user
        except IntegrityError:
            if attempt < 2:
                continue
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt < 2:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            logger.error("get_or_create_user_raw failed after 3 attempts: %s", exc)
            raise

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
            lh = ListeningHistory(
                    user_id=user_id,
                    track_id=track_id,
                    query=query,
                    action=action,
                    source=source,
                    listen_duration=listen_duration,
            )
            session.add(lh)
            await session.commit()
            await session.refresh(lh)
            # Mirror to Supabase REST (fire-and-forget)
            try:
                from bot.services.supabase_mirror import mirror_listening_event
                mirror_listening_event(
                    event_id=lh.id, user_id=user_id, action=action,
                    track_id=track_id, query=query, source=source,
                    listen_duration=listen_duration,
                )
            except Exception:
                logger.debug("mirror_listening_event failed for user %s", user_id, exc_info=True)
        # Mirror event to Supabase AI (fire-and-forget)
        try:
            from bot.config import settings as _s
            if _s.SUPABASE_AI_ENABLED and action in ("play", "skip", "like", "dislike"):
                import asyncio
                from bot.services.supabase_ai import supabase_ai
                # Build track dict from track_id if available
                track_info = {}
                if track_id:
                    async with async_session() as s2:
                        from bot.models.track import Track as _T
                        t = await s2.get(_T, track_id)
                        if t:
                            track_info = {
                                "source_id": t.source_id,
                                "title": t.title,
                                "artist": t.artist,
                                "genre": t.genre,
                                "bpm": t.bpm,
                                "duration": t.duration,
                                "file_id": t.file_id,
                                "source": t.source,
                            }
                if track_info.get("source_id"):
                    _fire_and_log_task(
                        supabase_ai.ingest_event(
                            event=action,
                            user_id=user_id,
                            track=track_info,
                            listen_duration=listen_duration,
                            source=source,
                            query=query,
                        ),
                        context=f"supabase_ai.ingest_event user={user_id} action={action}",
                    )
        except Exception:
            logger.debug("Supabase AI ingest scheduling failed for user %s", user_id, exc_info=True)
        # Check badges on play events (fire-and-forget)
        if action == "play":
            try:
                from bot.services.achievements import check_and_award_badges
                await check_and_award_badges(user_id, "play")
            except Exception:
                logger.debug("check_and_award_badges failed for user %s", user_id, exc_info=True)
            # XP + streak update
            try:
                from bot.services.leaderboard import add_xp, XP_PLAY
                await add_xp(user_id, XP_PLAY)
                await _update_streak_and_xp(user_id, XP_PLAY)
            except Exception:
                logger.debug("XP update failed for user %s", user_id, exc_info=True)
            # Auto-update profile every 10 plays
            try:
                play_count = await _get_user_play_count(user_id)
                if play_count > 0 and play_count % 10 == 0:
                    from recommender.profile_updater import trigger_profile_update
                    await trigger_profile_update(user_id)
            except Exception:
                logger.debug("profile update trigger failed for user %s", user_id, exc_info=True)
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
    cover_url: str | None = None,
    album: str | None = None,
    release_year: int | None = None,
    label: str | None = None,
    isrc: str | None = None,
    explicit: bool | None = None,
    popularity: int | None = None,
    language: str | None = None,
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
                cover_url=cover_url,
                album=album,
                release_year=release_year,
                label=label,
                isrc=isrc,
                explicit=explicit,
                popularity=popularity,
                language=language,
                downloads=1,
            )
            session.add(track)
        else:
            update_vals: dict = {
                "file_id": file_id or track.file_id,
                "downloads": Track.downloads + 1,
            }
            # Fill in missing metadata from richer sources
            _fill = {
                "cover_url": cover_url,
                "title": title,
                "artist": artist,
                "duration": duration,
                "genre": genre,
                "album": album,
                "release_year": release_year,
                "label": label,
                "isrc": isrc,
                "language": language,
            }
            for field, value in _fill.items():
                if value and not getattr(track, field, None):
                    update_vals[field] = value
            if explicit is not None and track.explicit is None:
                update_vals["explicit"] = explicit
            if popularity is not None and (track.popularity is None or popularity > (track.popularity or 0)):
                update_vals["popularity"] = popularity
            await session.execute(
                update(Track)
                .where(Track.source_id == source_id)
                .values(**update_vals)
            )
        await session.commit()
        await session.refresh(track)
        # Mirror track to Supabase
        try:
            from bot.services.supabase_mirror import mirror_track
            mirror_track(
                track.id, track.source_id, track.source or "youtube",
                title=track.title, artist=track.artist,
                genre=track.genre, duration=track.duration,
                cover_url=track.cover_url, album=track.album,
            )
        except Exception:
            logger.debug("mirror_track failed for track %s", track.id, exc_info=True)
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


async def get_random_popular_track() -> "Track | None":
    """Return a random track from top-100 most downloaded (for 'play random' intent)."""
    async with async_session() as session:
        result = await session.execute(
            select(Track)
            .where(Track.file_id.isnot(None))
            .order_by(func.random())
            .limit(1)
        )
        return result.scalars().first()


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
        fav = FavoriteTrack(user_id=user_id, track_id=track_id)
        session.add(fav)
        await session.commit()
        await session.refresh(fav)
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_favorite_add
            mirror_favorite_add(fav.id, user_id, track_id)
        except Exception:
            logger.debug("mirror_favorite_add failed for user %s track %s", user_id, track_id, exc_info=True)
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
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_favorite_remove
            mirror_favorite_remove(user_id, track_id)
        except Exception:
            logger.debug("mirror_favorite_remove failed for user %s track %s", user_id, track_id, exc_info=True)
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
