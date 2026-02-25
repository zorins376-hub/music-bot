"""
conftest.py — общие фикстуры для всех тестов.
"""
import os
import pytest

# Устанавливаем минимальный env до импорта settings
os.environ.setdefault("BOT_TOKEN", "1234567890:AAFakeTokenForTestingPurposesOnly000")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "fakeredis://")
os.environ.setdefault("YANDEX_MUSIC_TOKEN", "")
os.environ.setdefault("VK_TOKEN", "")


import fakeredis.aioredis as fakeredis
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.base import Base


# ── In-memory SQLite engine ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest.fixture(scope="session")
async def db_tables(engine):
    """Create all tables once per session."""
    from bot.models.user import User  # noqa
    from bot.models.track import Track, ListeningHistory, Payment  # noqa
    from bot.models.playlist import Playlist, PlaylistTrack  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session(engine, db_tables) -> AsyncSession:
    """Yield a fresh session and roll back after each test."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ── Fake Redis ─────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cache_with_fake_redis(fake_redis, monkeypatch):
    """Returns a Cache instance backed by fakeredis."""
    from bot.services.cache import Cache
    c = Cache()
    c._redis = fake_redis
    return c


# ── Telegram mock objects ──────────────────────────────────────────────────

def make_tg_user(user_id: int = 111, username: str = "testuser", first_name: str = "Test"):
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = first_name
    user.is_bot = False
    return user


def make_message(text: str = "test", user_id: int = 111, chat_type: str = "private"):
    msg = AsyncMock()
    msg.from_user = make_tg_user(user_id)
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.type = chat_type
    msg.chat.id = -100123 if chat_type != "private" else user_id
    msg.successful_payment = None
    msg.answer = AsyncMock()
    msg.answer_audio = AsyncMock()
    msg.answer_invoice = AsyncMock()
    msg.bot = AsyncMock()
    return msg


def make_callback(data: str = "test", user_id: int = 111):
    cb = AsyncMock()
    cb.from_user = make_tg_user(user_id)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = make_message(user_id=user_id)
    return cb
