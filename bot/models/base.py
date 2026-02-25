from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings

_is_pg = settings.DATABASE_URL.startswith("postgresql")
_engine_kwargs: dict = {"echo": False}
if _is_pg:
    _engine_kwargs.update(
        pool_size=3,        # Supabase free tier PgBouncer: keep small
        max_overflow=7,     # max 10 total connections
        pool_timeout=15,    # fail fast instead of queueing forever
        pool_recycle=300,
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,
            "command_timeout": 15,  # per-query timeout
        },
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    from bot.models.user import User  # noqa: F401
    from bot.models.track import Track, ListeningHistory, Payment  # noqa: F401
    from bot.models.playlist import Playlist, PlaylistTrack  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
