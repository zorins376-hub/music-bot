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
    from bot.models.admin_log import AdminLog  # noqa: F401

    last_exc: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Add columns that create_all won't add to existing tables
                if _is_pg:
                    _alter_stmts = [
                        # User columns added after initial deployment
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT false",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS captcha_passed BOOLEAN DEFAULT false",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS request_count INTEGER DEFAULT 0",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_genres JSONB",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_artists JSONB",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_vibe VARCHAR(50)",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_bpm INTEGER",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded BOOLEAN DEFAULT false",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_until TIMESTAMPTZ",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS flac_credits INTEGER DEFAULT 0",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_tracks INTEGER DEFAULT 0",
                        # ListeningHistory columns
                        "ALTER TABLE listening_history ADD COLUMN IF NOT EXISTS action VARCHAR(20) DEFAULT 'play'",
                        "ALTER TABLE listening_history ADD COLUMN IF NOT EXISTS listen_duration INTEGER",
                        "ALTER TABLE listening_history ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'search'",
                        # Track columns
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'youtube'",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS channel VARCHAR(50)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS artist VARCHAR(255)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS genre VARCHAR(50)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS bpm INTEGER",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS duration INTEGER",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS downloads INTEGER DEFAULT 0",
                    ]
                    for stmt in _alter_stmts:
                        try:
                            await conn.execute(__import__("sqlalchemy").text(stmt))
                        except Exception:
                            pass  # Column already exists or table doesn't exist yet
                # Create pg_trgm extension and trigram indexes for PostgreSQL
                if _is_pg:
                    await conn.execute(
                        __import__("sqlalchemy").text(
                            "CREATE EXTENSION IF NOT EXISTS pg_trgm"
                        )
                    )
                    for stmt in (
                        "CREATE INDEX IF NOT EXISTS ix_tracks_title_trgm ON tracks USING gin (title gin_trgm_ops)",
                        "CREATE INDEX IF NOT EXISTS ix_tracks_artist_trgm ON tracks USING gin (artist gin_trgm_ops)",
                    ):
                        await conn.execute(__import__("sqlalchemy").text(stmt))
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
