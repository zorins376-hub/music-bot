"""Alembic env.py — async-friendly migration runner.

Usage:
  # Generate migration from model changes
  alembic revision --autogenerate -m "add ondelete cascade"

  # Apply migrations
  alembic upgrade head
  
  # Downgrade
  alembic downgrade -1
"""
import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so Alembic can see them
from bot.models.base import Base
from bot.models.user import User
from bot.models.track import Track
from bot.models.playlist import Playlist, PlaylistTrack
from bot.models.daily_mix import DailyMix, DailyMixTrack
from bot.models.favorite import FavoriteTrack
from bot.models.party import PartySession, PartyTrack
from bot.models.recommendation_log import RecommendationLog
from bot.models.admin_log import AdminLog
from bot.models.blocked_track import BlockedTrack
from bot.models.dmca_appeal import DMCAAppeal
from bot.models.share_link import ShareLink
from bot.models.family_plan import FamilyPlan, FamilyMember
from bot.models.promo_code import PromoCode, PromoCodeUsage
from bot.models.sponsored import SponsoredTrack
from bot.models.release_notification import ReleaseNotification
from bot.models.artist_watchlist import ArtistWatchlist

# Import settings for DB URL
from bot.config import settings

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate
target_metadata = Base.metadata


def get_sync_url() -> str:
    """Convert async URL to sync URL for Alembic."""
    url = str(settings.DATABASE_URL)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://")
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def get_async_url() -> str:
    """Get async database URL from settings."""
    return str(settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    
    This generates SQL statements without connecting to DB.
    """
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Actually run migrations in a transaction."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(
        get_async_url(),
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
