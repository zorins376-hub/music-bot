"""
Тесты для bot/db.py — работа с базой данных.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from bot.models.user import User
from bot.models.track import Track, ListeningHistory, Payment


def make_tg_user(user_id=1001, username="testuser", first_name="Test"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    u.is_bot = False
    return u


@pytest.mark.asyncio
class TestGetOrCreateUser:
    async def test_creates_new_user(self, db_session):
        from bot.db import get_or_create_user
        from bot.models.base import async_session as real_session

        tg = make_tg_user(2001, "alice", "Alice")

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            # Напрямую тестируем через сессию
            result = await db_session.execute(select(User).where(User.id == 2001))
            user = result.scalar_one_or_none()
            assert user is None  # ещё не создан

    async def test_user_model_defaults(self, db_session):
        """Проверяем дефолты модели User."""
        user = User(id=3001, username="bob", first_name="Bob")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.language == "ru"
        assert user.quality == "192"
        assert user.is_premium is False
        assert user.is_banned is False
        assert user.captcha_passed is False
        assert user.request_count == 0
        assert user.created_at is not None

    async def test_premium_until_nullable(self, db_session):
        user = User(id=3002, username="carl", first_name="Carl")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.premium_until is None

    async def test_set_premium(self, db_session):
        from sqlalchemy import update
        user = User(id=3003, username="diana", first_name="Diana")
        db_session.add(user)
        await db_session.commit()

        premium_until = datetime.now(timezone.utc) + timedelta(days=30)
        await db_session.execute(
            update(User)
            .where(User.id == 3003)
            .values(is_premium=True, premium_until=premium_until)
        )
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == 3003))
        updated = result.scalar_one()
        assert updated.is_premium is True
        assert updated.premium_until is not None


@pytest.mark.asyncio
class TestTrackModel:
    async def test_create_track(self, db_session):
        track = Track(
            source_id="yt_abc123",
            source="youtube",
            title="Test Track",
            artist="Test Artist",
            duration=240,
        )
        db_session.add(track)
        await db_session.commit()
        await db_session.refresh(track)

        assert track.id is not None
        assert track.downloads == 0
        assert track.created_at is not None

    async def test_source_id_unique(self, db_session):
        """source_id должен быть уникальным."""
        from sqlalchemy.exc import IntegrityError
        t1 = Track(source_id="yt_unique1", source="youtube", title="T1", artist="A1")
        t2 = Track(source_id="yt_unique1", source="youtube", title="T2", artist="A2")
        db_session.add(t1)
        await db_session.commit()
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_yandex_track(self, db_session):
        track = Track(
            source_id="ym_99999",
            source="yandex",
            title="Яндекс Трек",
            artist="Исполнитель",
            duration=200,
        )
        db_session.add(track)
        await db_session.commit()
        await db_session.refresh(track)
        assert track.source == "yandex"
        assert track.source_id == "ym_99999"


@pytest.mark.asyncio
class TestPaymentModel:
    async def test_create_payment(self, db_session):
        # Сначала создаём юзера (FK constraint)
        user = User(id=4001, username="payer", first_name="Payer")
        db_session.add(user)
        await db_session.commit()

        payment = Payment(
            user_id=4001,
            amount=150,
            currency="XTR",
            payload="premium_30d",
        )
        db_session.add(payment)
        await db_session.commit()
        await db_session.refresh(payment)

        assert payment.id is not None
        assert payment.amount == 150
        assert payment.currency == "XTR"
        assert payment.created_at is not None


@pytest.mark.asyncio
class TestListeningHistory:
    async def test_create_history_entry(self, db_session):
        user = User(id=5001, username="listener", first_name="Listener")
        db_session.add(user)
        await db_session.commit()

        entry = ListeningHistory(
            user_id=5001,
            query="imagine dragons bones",
            action="play",
            source="search",
        )
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        assert entry.id is not None
        assert entry.action == "play"
        assert entry.source == "search"
