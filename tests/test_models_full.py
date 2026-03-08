"""
Полные тесты моделей: User, Track, ListeningHistory, Payment, Playlist, PlaylistTrack.
"""
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.models.user import User
from bot.models.track import Track, ListeningHistory, Payment
from bot.models.playlist import Playlist, PlaylistTrack


# ═══════════════════════════════════ User Model ═══════════════════════════

@pytest.mark.asyncio
class TestUserModel:
    async def test_defaults(self, db_session):
        u = User(id=10001, username="defuser", first_name="Def")
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)

        assert u.language == "ru"
        assert u.quality == "192"
        assert u.is_premium is False
        assert u.is_banned is False
        assert u.captcha_passed is False
        assert u.request_count == 0
        assert u.onboarded is False
        assert u.fav_genres is None
        assert u.fav_artists is None
        assert u.fav_vibe is None
        assert u.avg_bpm is None
        assert u.premium_until is None
        assert u.created_at is not None
        assert u.last_active is not None

    async def test_json_fields(self, db_session):
        u = User(
            id=10002,
            username="jsonuser",
            first_name="Json",
            fav_genres=["rock", "pop"],
            fav_artists=["Queen", "ABBA"],
            fav_vibe="chill",
            avg_bpm=120,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)

        assert u.fav_genres == ["rock", "pop"]
        assert u.fav_artists == ["Queen", "ABBA"]
        assert u.fav_vibe == "chill"
        assert u.avg_bpm == 120

    async def test_premium_with_until(self, db_session):
        until = datetime.now(timezone.utc) + timedelta(days=30)
        u = User(id=10003, username="premuser", first_name="Prem", is_premium=True, premium_until=until)
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)

        assert u.is_premium is True
        assert u.premium_until is not None

    async def test_banned_user(self, db_session):
        u = User(id=10004, username="banned", first_name="Ban", is_banned=True)
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        assert u.is_banned is True

    async def test_captcha_passed(self, db_session):
        u = User(id=10005, username="captcha", first_name="Cap", captcha_passed=True)
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        assert u.captcha_passed is True

    async def test_different_languages(self, db_session):
        for lang_code, uid in [("en", 10006), ("kg", 10007)]:
            u = User(id=uid, username=f"lang_{lang_code}", first_name="L", language=lang_code)
            db_session.add(u)
            await db_session.commit()
            await db_session.refresh(u)
            assert u.language == lang_code

    async def test_quality_options(self, db_session):
        for q, uid in [("128", 10008), ("320", 10009)]:
            u = User(id=uid, username=f"q_{q}", first_name="Q", quality=q)
            db_session.add(u)
            await db_session.commit()
            await db_session.refresh(u)
            assert u.quality == q


# ═══════════════════════════════════ Track Model ═══════════════════════════

@pytest.mark.asyncio
class TestTrackModel:
    async def test_defaults(self, db_session):
        t = Track(source_id="test_defaults_1", source="youtube", title="T", artist="A")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        assert t.downloads == 0
        assert t.channel is None
        assert t.genre is None
        assert t.bpm is None
        assert t.file_id is None
        assert t.created_at is not None

    async def test_channel_track(self, db_session):
        t = Track(
            source_id="tg_chan_1",
            source="channel",
            channel="tequila",
            title="Channel Track",
            artist="DJ",
            duration=300,
            file_id="AgACAgQAA...",
            genre="house",
            bpm=128,
        )
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        assert t.source == "channel"
        assert t.channel == "tequila"
        assert t.genre == "house"
        assert t.bpm == 128
        assert t.file_id == "AgACAgQAA..."

    async def test_vk_track(self, db_session):
        t = Track(source_id="vk_111_222", source="vk", title="VK Song", artist="VK Artist", duration=180)
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)
        assert t.source == "vk"

    async def test_soundcloud_track(self, db_session):
        t = Track(source_id="sc_xyz", source="soundcloud", title="SC Song", artist="SC Artist")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)
        assert t.source == "soundcloud"

    async def test_source_id_uniqueness(self, db_session):
        t1 = Track(source_id="unique_check_1", source="youtube", title="T1", artist="A1")
        db_session.add(t1)
        await db_session.commit()

        t2 = Track(source_id="unique_check_1", source="youtube", title="T2", artist="A2")
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()


# ═══════════════════════════════════ ListeningHistory ════════════════════

@pytest.mark.asyncio
class TestListeningHistoryModel:
    async def test_create_entry(self, db_session):
        u = User(id=20001, username="hist", first_name="H")
        db_session.add(u)
        await db_session.commit()

        entry = ListeningHistory(user_id=20001, query="test query", action="play", source="search")
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        assert entry.id is not None
        assert entry.action == "play"
        assert entry.source == "search"
        assert entry.query == "test query"
        assert entry.track_id is None

    async def test_actions(self, db_session):
        u = User(id=20002, username="actions", first_name="A")
        db_session.add(u)
        await db_session.commit()

        for action in ("play", "skip", "like", "dislike", "search"):
            entry = ListeningHistory(user_id=20002, action=action)
            db_session.add(entry)
        await db_session.commit()

        result = await db_session.execute(
            select(ListeningHistory).where(ListeningHistory.user_id == 20002)
        )
        entries = result.scalars().all()
        assert len(entries) == 5

    async def test_with_track_linked(self, db_session):
        u = User(id=20003, username="linked", first_name="L")
        db_session.add(u)
        await db_session.commit()

        t = Track(source_id="linked_track_1", source="youtube", title="Linked", artist="A")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        entry = ListeningHistory(user_id=20003, track_id=t.id, action="play")
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        assert entry.track_id == t.id

    async def test_listen_duration(self, db_session):
        u = User(id=20004, username="dur", first_name="D")
        db_session.add(u)
        await db_session.commit()

        entry = ListeningHistory(user_id=20004, action="play", listen_duration=180)
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)
        assert entry.listen_duration == 180


# ═══════════════════════════════════ Payment Model ════════════════════════

@pytest.mark.asyncio
class TestPaymentModel:
    async def test_create(self, db_session):
        u = User(id=30001, username="payer", first_name="P")
        db_session.add(u)
        await db_session.commit()

        p = Payment(user_id=30001, amount=150, currency="XTR", payload="premium_30d")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)

        assert p.id is not None
        assert p.amount == 150
        assert p.currency == "XTR"
        assert p.payload == "premium_30d"
        assert p.created_at is not None

    async def test_default_currency(self, db_session):
        u = User(id=30002, username="defcur", first_name="DC")
        db_session.add(u)
        await db_session.commit()

        p = Payment(user_id=30002, amount=100)
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)
        assert p.currency == "XTR"


# ═══════════════════════════════════ Playlist Models ═══════════════════════

@pytest.mark.asyncio
class TestPlaylistModel:
    async def test_create_playlist(self, db_session):
        u = User(id=40001, username="pl", first_name="PL")
        db_session.add(u)
        await db_session.commit()

        pl = Playlist(user_id=40001, name="My Favs")
        db_session.add(pl)
        await db_session.commit()
        await db_session.refresh(pl)

        assert pl.id is not None
        assert pl.name == "My Favs"
        assert pl.user_id == 40001
        assert pl.created_at is not None

    async def test_multiple_playlists_per_user(self, db_session):
        u = User(id=40002, username="multi_pl", first_name="MP")
        db_session.add(u)
        await db_session.commit()

        for name in ("Rock", "Pop", "Jazz"):
            db_session.add(Playlist(user_id=40002, name=name))
        await db_session.commit()

        result = await db_session.execute(
            select(Playlist).where(Playlist.user_id == 40002)
        )
        playlists = result.scalars().all()
        assert len(playlists) == 3

    async def test_playlist_track_linking(self, db_session):
        u = User(id=40003, username="pt", first_name="PT")
        db_session.add(u)
        await db_session.commit()

        pl = Playlist(user_id=40003, name="Test PL")
        db_session.add(pl)
        await db_session.commit()
        await db_session.refresh(pl)

        t = Track(source_id="pl_track_1", source="youtube", title="Song", artist="Art")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        pt = PlaylistTrack(playlist_id=pl.id, track_id=t.id, position=0)
        db_session.add(pt)
        await db_session.commit()
        await db_session.refresh(pt)

        assert pt.playlist_id == pl.id
        assert pt.track_id == t.id
        assert pt.position == 0

    async def test_playlist_track_unique_constraint(self, db_session):
        u = User(id=40004, username="uniq_pt", first_name="UP")
        db_session.add(u)
        await db_session.commit()

        pl = Playlist(user_id=40004, name="Uniq PL")
        db_session.add(pl)
        await db_session.commit()
        await db_session.refresh(pl)

        t = Track(source_id="uniq_pt_track", source="youtube", title="S", artist="A")
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)

        pt1 = PlaylistTrack(playlist_id=pl.id, track_id=t.id, position=0)
        db_session.add(pt1)
        await db_session.commit()

        pt2 = PlaylistTrack(playlist_id=pl.id, track_id=t.id, position=1)
        db_session.add(pt2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()
