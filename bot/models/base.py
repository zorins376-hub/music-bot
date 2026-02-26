import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from bot.config import settings

_logger = logging.getLogger(__name__)

_is_pg = settings.DATABASE_URL.startswith("postgresql")
_engine_kwargs: dict = {"echo": False}
if _is_pg:
    # Supabase uses PgBouncer in transaction mode (port 6543).
    # SQLAlchemy's own pool + asyncpg = stale "ConnectionDoesNotExistError".
    # NullPool: every async_session() gets a fresh PgBouncer connection;
    # PgBouncer handles the actual server-side pool itself.
    _engine_kwargs.update(
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "command_timeout": 15,
            "timeout": 30,  # asyncpg connection timeout (default is 60s)
        },
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def init_db(retries: int = 5, delay: float = 5.0) -> None:
    """Create all tables, retrying on transient connection errors."""
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    from bot.models.user import User  # noqa: F401
    from bot.models.track import Track, ListeningHistory, Payment  # noqa: F401
    from bot.models.playlist import Playlist, PlaylistTrack  # noqa: F401

    last_exc: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                _logger.warning(
                    "init_db attempt %d/%d failed: %s — retrying in %.0fs",
                    attempt, retries, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                _logger.error("init_db failed after %d attempts: %s", retries, exc)
    raise RuntimeError(f"init_db failed after {retries} attempts") from last_exc
