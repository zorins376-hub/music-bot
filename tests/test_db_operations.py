"""
Тесты bot/db.py — все функции: is_admin, get_or_create_user, upsert_track,
increment_request_count, record_listening_event, get_user_stats, search_local_tracks.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import select, update

from bot.models.user import User
from bot.models.track import Track, ListeningHistory


def _tg_user(user_id=9001, username="dbtest", first_name="DBTest"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    u.is_bot = False
    return u


# ═══════════════════════════════════ is_admin ═════════════════════════════

class TestIsAdmin:
    def test_admin_by_id(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = [111, 222]
            s.ADMIN_USERNAMES = []
            assert is_admin(111) is True

    def test_not_admin(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = [111]
            s.ADMIN_USERNAMES = ["admin1"]
            assert is_admin(999, "random") is False

    def test_admin_by_username(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = []
            s.ADMIN_USERNAMES = ["SuperAdmin"]
            assert is_admin(999, "superadmin") is True  # case insensitive

    def test_admin_by_username_case_insensitive(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = []
            s.ADMIN_USERNAMES = ["TestAdmin"]
            assert is_admin(1, "TESTADMIN") is True
            assert is_admin(1, "testadmin") is True
            assert is_admin(1, "TestAdmin") is True

    def test_none_username(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = []
            s.ADMIN_USERNAMES = ["admin"]
            assert is_admin(999, None) is False

    def test_empty_admin_lists(self):
        from bot.db import is_admin
        with patch("bot.db.settings") as s:
            s.ADMIN_IDS = []
            s.ADMIN_USERNAMES = []
            assert is_admin(1, "anyone") is False


# ═══════════════════════════════════ get_or_create_user ════════════════════

@pytest.mark.asyncio
class TestGetOrCreateUser:
    async def test_creates_new_user(self, db_session):
        """Новый пользователь создаётся с правильными полями."""
        tg = _tg_user(50001, "newuser", "New")

        with patch("bot.db.async_session") as mock_sm, \
             patch("bot.db.is_admin", return_value=False):
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_or_create_user
            user = await get_or_create_user(tg)

        assert user.id == 50001
        assert user.username == "newuser"
        assert user.first_name == "New"
        assert user.is_premium is False

    async def test_creates_admin_as_premium(self, db_session):
        """Админ при создании получает is_premium=True."""
        tg = _tg_user(50002, "adminuser", "Admin")

        with patch("bot.db.async_session") as mock_sm, \
             patch("bot.db.is_admin", return_value=True), \
             patch("bot.db.settings") as s:
            s.ADMIN_IDS = [50002]
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_or_create_user
            user = await get_or_create_user(tg)

        assert user.is_premium is True

    async def test_returns_existing_user(self, db_session):
        """Второй вызов возвращает существующего пользователя."""
        existing = User(id=50003, username="existing", first_name="E")
        db_session.add(existing)
        await db_session.commit()

        tg = _tg_user(50003, "existing", "E")

        with patch("bot.db.async_session") as mock_sm, \
             patch("bot.db.is_admin", return_value=False):
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_or_create_user
            user = await get_or_create_user(tg)

        assert user.id == 50003

    async def test_keeps_manual_premium_without_expiry(self, db_session):
        """Ручной Premium от админа без premium_until не должен сниматься."""
        existing = User(
            id=50004,
            username="vipuser",
            first_name="VIP",
            is_premium=True,
            premium_until=None,
        )
        db_session.add(existing)
        await db_session.commit()

        tg = _tg_user(50004, "vipuser", "VIP")

        with patch("bot.db.async_session") as mock_sm, \
             patch("bot.db.is_admin", return_value=False):
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_or_create_user
            user = await get_or_create_user(tg)

        assert user.is_premium is True

        refreshed = await db_session.get(User, 50004)
        assert refreshed is not None
        assert refreshed.is_premium is True


# ═══════════════════════════════════ upsert_track ═════════════════════════

@pytest.mark.asyncio
class TestUpsertTrack:
    async def test_creates_new_track(self, db_session):
        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import upsert_track
            track = await upsert_track(
                source_id="upsert_new_1",
                title="New Song",
                artist="New Artist",
                duration=200,
                source="youtube",
            )

        assert track.source_id == "upsert_new_1"
        assert track.title == "New Song"
        assert track.downloads == 1

    async def test_updates_existing_track(self, db_session):
        t = Track(source_id="upsert_exist_1", source="youtube", title="Old", artist="A", downloads=5)
        db_session.add(t)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import upsert_track
            track = await upsert_track(
                source_id="upsert_exist_1",
                title="Old",
                artist="A",
                file_id="NEW_FILE_ID",
            )

        assert track.downloads == 6
        assert track.file_id == "NEW_FILE_ID"

    async def test_upsert_with_channel(self, db_session):
        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import upsert_track
            track = await upsert_track(
                source_id="upsert_chan_1",
                title="Channel Track",
                artist="DJ",
                source="channel",
                channel="tequila",
                genre="house",
                bpm=128,
            )

        assert track.channel == "tequila"
        assert track.genre == "house"
        assert track.bpm == 128


# ═══════════════════════════════════ increment_request_count ═══════════════

@pytest.mark.asyncio
class TestIncrementRequestCount:
    async def test_increments_count(self, db_session):
        u = User(id=60001, username="inc", first_name="Inc", request_count=5)
        db_session.add(u)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import increment_request_count
            await increment_request_count(60001)

        result = await db_session.execute(select(User).where(User.id == 60001))
        user = result.scalar_one()
        assert user.request_count == 6

    async def test_does_not_raise_on_error(self, db_session):
        """Ошибка логируется, но не выбрасывается."""
        with patch("bot.db.async_session", side_effect=Exception("DB error")):
            from bot.db import increment_request_count
            await increment_request_count(99999)  # Should not raise


# ═══════════════════════════════════ record_listening_event ════════════════

@pytest.mark.asyncio
class TestRecordListeningEvent:
    async def test_records_event(self, db_session):
        u = User(id=70001, username="listen", first_name="L")
        db_session.add(u)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import record_listening_event
            await record_listening_event(
                user_id=70001,
                query="test song",
                action="play",
                source="search",
                listen_duration=120,
            )

        result = await db_session.execute(
            select(ListeningHistory).where(ListeningHistory.user_id == 70001)
        )
        entry = result.scalar_one()
        assert entry.action == "play"
        assert entry.source == "search"
        assert entry.listen_duration == 120

    async def test_does_not_raise_on_error(self):
        with patch("bot.db.async_session", side_effect=Exception("DB error")):
            from bot.db import record_listening_event
            await record_listening_event(user_id=99999, query="test")


# ═══════════════════════════════════ get_user_stats ═══════════════════════

@pytest.mark.asyncio
class TestGetUserStats:
    async def test_empty_stats(self, db_session):
        u = User(id=80001, username="empty", first_name="E")
        db_session.add(u)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_user_stats
            stats = await get_user_stats(80001)

        assert stats["total"] == 0
        assert stats["week"] == 0
        assert stats["top_artist"] is None

    async def test_stats_with_history(self, db_session):
        u = User(id=80002, username="stats", first_name="S")
        db_session.add(u)
        await db_session.commit()

        t = Track(source_id="stats_track_1", source="youtube", title="Song", artist="Artist1")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        for _ in range(3):
            db_session.add(ListeningHistory(user_id=80002, track_id=t.id, action="play"))
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import get_user_stats
            stats = await get_user_stats(80002)

        assert stats["total"] == 3
        assert stats["week"] == 3
        assert stats["top_artist"] == "Artist1"


# ═══════════════════════════════════ search_local_tracks ═══════════════════

@pytest.mark.asyncio
class TestSearchLocalTracks:
    async def test_search_by_title(self, db_session):
        t = Track(source_id="local_search_1", source="youtube", title="Bohemian Rhapsody", artist="Queen", downloads=10)
        db_session.add(t)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import search_local_tracks
            results = await search_local_tracks("Bohemian")

        assert len(results) >= 1
        assert any(r.title == "Bohemian Rhapsody" for r in results)

    async def test_search_by_artist(self, db_session):
        t = Track(source_id="local_search_2", source="youtube", title="Song", artist="SpecialArtist123", downloads=5)
        db_session.add(t)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import search_local_tracks
            results = await search_local_tracks("SpecialArtist123")

        assert len(results) >= 1

    async def test_channel_tracks_prioritized(self, db_session):
        """Треки из TEQUILA/FULLMOON идут первыми."""
        t1 = Track(source_id="prio_ext", source="youtube", title="TestPriority", artist="A", downloads=100, channel=None)
        t2 = Track(source_id="prio_teq", source="channel", title="TestPriority", artist="A", downloads=1, channel="tequila")
        db_session.add(t1)
        db_session.add(t2)
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import search_local_tracks
            results = await search_local_tracks("TestPriority")

        assert len(results) >= 2
        assert results[0].channel == "tequila"

    async def test_search_no_results(self, db_session):
        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import search_local_tracks
            results = await search_local_tracks("zzznonexistenttrackzzz")

        assert results == []

    async def test_search_respects_limit(self, db_session):
        for i in range(10):
            db_session.add(Track(
                source_id=f"limit_test_{i}", source="youtube",
                title="LimitTestTrack", artist="A", downloads=i
            ))
        await db_session.commit()

        with patch("bot.db.async_session") as mock_sm:
            mock_sm.return_value.__aenter__ = lambda s: db_session.__aenter__()
            mock_sm.return_value.__aexit__ = lambda s, *a: db_session.__aexit__(*a)

            from bot.db import search_local_tracks
            results = await search_local_tracks("LimitTestTrack", limit=3)

        assert len(results) <= 3
