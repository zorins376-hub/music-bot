from aiogram.types import User as TgUser
from datetime import datetime, timezone
from sqlalchemy import case, select, update
from sqlalchemy.sql import func

from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User


async def get_or_create_user(tg_user: TgUser) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == tg_user.id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            await session.execute(
                update(User)
                .where(User.id == tg_user.id)
                .values(
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    last_active=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        # Auto-revoke expired premium
        if user.is_premium and user.premium_until and user.premium_until < datetime.now(timezone.utc):
            await session.execute(
                update(User)
                .where(User.id == tg_user.id)
                .values(is_premium=False)
            )
            await session.commit()
            user.is_premium = False

        return user


async def increment_request_count(user_id: int) -> None:
    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(request_count=User.request_count + 1)
        )
        await session.commit()


async def record_listening_event(
    user_id: int,
    track_id: int | None = None,
    query: str | None = None,
    action: str = "play",
    source: str = "search",
    listen_duration: int | None = None,
) -> None:
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


async def search_local_tracks(query: str, limit: int = 5) -> list[Track]:
    """Search tracks in local DB (channels TEQUILA / FULLMOON first, then all)."""
    q = f"%{query}%"
    async with async_session() as session:
        # Priority: channel tracks first, then external
        result = await session.execute(
            select(Track)
            .where(
                (Track.title.ilike(q)) | (Track.artist.ilike(q))
            )
            .order_by(
                # channel tracks first (tequila/fullmoon), then external
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
