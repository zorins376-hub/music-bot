import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool

from bot.config import settings

_logger = logging.getLogger(__name__)

_is_pg = settings.DATABASE_URL.startswith("postgresql")
_is_local_pg = _is_pg and ("localhost" in settings.DATABASE_URL or "postgres:" in settings.DATABASE_URL)
_engine_kwargs: dict = {"echo": False}

if _is_pg:
    if _is_local_pg:
        # VPS local PostgreSQL: use connection pooling for performance
        _engine_kwargs.update(
            poolclass=AsyncAdaptedQueuePool,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,  # check connection health before use
            connect_args={
                "command_timeout": settings.DB_COMMAND_TIMEOUT,
                "timeout": settings.DB_CONNECT_TIMEOUT,
            },
        )
        _logger.info(
            "DB: local PostgreSQL pool (size=%d, overflow=%d)",
            settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW,
        )
    else:
        # Supabase PgBouncer: NullPool (PgBouncer handles pooling)
        _engine_kwargs.update(
            poolclass=NullPool,
            connect_args={
                "statement_cache_size": 0,  # required for PgBouncer
                "command_timeout": settings.DB_COMMAND_TIMEOUT,
                "timeout": settings.DB_CONNECT_TIMEOUT,
            },
        )
        _logger.info("DB: Supabase PgBouncer mode (NullPool)")

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
    from bot.models.favorite import FavoriteTrack  # noqa: F401
    from bot.models.release_notification import ReleaseNotification  # noqa: F401
    from bot.models.admin_log import AdminLog  # noqa: F401
    from bot.models.blocked_track import BlockedTrack  # noqa: F401
    from bot.models.promo_code import PromoCode, PromoActivation  # noqa: F401
    from bot.models.sponsored import SponsoredCampaign, SponsoredEvent  # noqa: F401
    from bot.models.dmca_appeal import DmcaAppeal  # noqa: F401
    from bot.models.daily_mix import DailyMix, DailyMixTrack  # noqa: F401
    from bot.models.share_link import ShareLink  # noqa: F401
    from bot.models.artist_watchlist import ArtistWatchlist  # noqa: F401
    from bot.models.family_plan import FamilyPlan, FamilyMember, FamilyInvite  # noqa: F401
    from bot.models.party import PartyChatMessage, PartyEvent, PartyMember, PartyPlaybackState, PartyReaction, PartySession, PartyTrack, PartyTrackVote  # noqa: F401

    _text = __import__("sqlalchemy").text

    async def _run_migration(conn, stmt: str) -> bool:
        """Run a single migration inside a savepoint. Returns True on success."""
        try:
            await conn.execute(_text("SAVEPOINT mig"))
            await conn.execute(_text(stmt))
            await conn.execute(_text("RELEASE SAVEPOINT mig"))
            return True
        except Exception:
            try:
                await conn.execute(_text("ROLLBACK TO SAVEPOINT mig"))
            except Exception:
                pass
            return False

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
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_version VARCHAR(20)",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS welcome_sent BOOLEAN DEFAULT false",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS release_radar_enabled BOOLEAN DEFAULT true",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badges JSONB",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS xp INTEGER DEFAULT 0",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 1",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 0",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_play_date DATE",
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
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS cover_url VARCHAR(500)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS album VARCHAR(500)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS release_year INTEGER",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS label VARCHAR(255)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS isrc VARCHAR(20)",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS explicit BOOLEAN",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS popularity INTEGER",
                        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS language VARCHAR(10)",
                        "ALTER TABLE tracks ALTER COLUMN genre TYPE VARCHAR(100)",
                        # BlockedTrack columns
                        "ALTER TABLE blocked_tracks ADD COLUMN IF NOT EXISTS alternative_source_id VARCHAR(100)",
                    ]
                    for stmt in _alter_stmts:
                        await _run_migration(conn, stmt)
                # Create pg_trgm extension and trigram indexes for PostgreSQL
                if _is_pg:
                    # Check if pg_trgm is available
                    result = await conn.execute(
                        _text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                    )
                    has_trgm = result.scalar() is not None
                    if not has_trgm:
                        # Try to create it (requires superuser or extension owner)
                        has_trgm = await _run_migration(
                            conn, "CREATE EXTENSION IF NOT EXISTS pg_trgm"
                        )
                        if not has_trgm:
                            _logger.warning(
                                "pg_trgm extension not available — trigram indexes skipped"
                            )
                    if has_trgm:
                        for stmt in (
                            "CREATE INDEX IF NOT EXISTS ix_tracks_title_trgm ON tracks USING gin (title gin_trgm_ops)",
                            "CREATE INDEX IF NOT EXISTS ix_tracks_artist_trgm ON tracks USING gin (artist gin_trgm_ops)",
                        ):
                            await _run_migration(conn, stmt)
                    # Regular btree indexes (don't need pg_trgm)
                    for stmt in (
                        "CREATE INDEX IF NOT EXISTS ix_users_created_at ON users (created_at)",
                        "CREATE INDEX IF NOT EXISTS ix_users_last_active ON users (last_active)",
                        "CREATE INDEX IF NOT EXISTS ix_tracks_created_at ON tracks (created_at)",
                        "CREATE INDEX IF NOT EXISTS ix_tracks_genre ON tracks (genre)",
                        "CREATE INDEX IF NOT EXISTS ix_tracks_release_year ON tracks (release_year)",
                        "CREATE INDEX IF NOT EXISTS ix_tracks_artist ON tracks (artist)",
                        "CREATE INDEX IF NOT EXISTS ix_lh_action_created ON listening_history (action, created_at DESC)",
                        "CREATE INDEX IF NOT EXISTS ix_payments_created_at ON payments (created_at)",
                        "CREATE INDEX IF NOT EXISTS ix_party_events_party_created ON party_events (party_id, created_at DESC)",
                    ):
                        await _run_migration(conn, stmt)
                    if has_trgm:
                        await _run_migration(
                            conn,
                            "CREATE INDEX IF NOT EXISTS ix_tracks_artist_title_trgm "
                            "ON tracks USING gin ((lower(coalesce(artist, '') || ' ' || coalesce(title, ''))) gin_trgm_ops)"
                        )
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
