from datetime import datetime, timezone

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_rank_watchlist_candidates_merges_and_prioritizes_favorite():
    from bot.services.release_radar import _rank_watchlist_candidates

    rows = [
        ("  Daft   Punk ", 2.0, "history"),
        ("daft punk", 5.0, "favorite"),
        ("Justice", 3.0, "history"),
    ]

    ranked = _rank_watchlist_candidates(rows)

    assert ranked[0][1] == "daft punk"
    assert ranked[0][2] == 7.0
    assert ranked[0][3] == "favorite"
    assert ranked[1][1] == "justice"


@pytest.mark.asyncio
async def test_rebuild_watchlist_persists_history_and_favorites(db_session):
    from bot.models.artist_watchlist import ArtistWatchlist
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User
    from bot.services.release_radar import _rebuild_watchlist_for_users

    user = User(
        id=1001,
        username="u1",
        captcha_passed=True,
        release_radar_enabled=True,
        fav_artists=["Daft Punk"],
    )
    t1 = Track(source_id="yt:rr:1", source="youtube", artist="Daft Punk", title="Around The World")
    t2 = Track(source_id="yt:rr:2", source="youtube", artist="Justice", title="Genesis")

    db_session.add_all([user, t1, t2])
    await db_session.commit()

    db_session.add_all(
        [
            ListeningHistory(user_id=user.id, track_id=t1.id, action="play"),
            ListeningHistory(user_id=user.id, track_id=t1.id, action="play"),
            ListeningHistory(user_id=user.id, track_id=t2.id, action="play"),
            ListeningHistory(user_id=user.id, track_id=t2.id, action="play"),
            ListeningHistory(user_id=user.id, track_id=t2.id, action="play"),
        ]
    )
    await db_session.commit()

    await _rebuild_watchlist_for_users(db_session, [user])

    result = await db_session.execute(
        select(ArtistWatchlist).where(ArtistWatchlist.user_id == user.id).order_by(ArtistWatchlist.weight.desc())
    )
    rows = result.scalars().all()

    assert len(rows) == 2
    by_name = {r.normalized_name: r for r in rows}
    assert "daft punk" in by_name
    assert by_name["daft punk"].weight == 7.0
    assert by_name["daft punk"].source == "favorite"
    assert "justice" in by_name
    assert by_name["justice"].weight == 3.0


@pytest.mark.asyncio
async def test_rebuild_watchlist_replaces_existing_rows(db_session):
    from bot.models.artist_watchlist import ArtistWatchlist
    from bot.models.user import User
    from bot.services.release_radar import _rebuild_watchlist_for_users

    user = User(
        id=1002,
        username="u2",
        captcha_passed=True,
        release_radar_enabled=True,
        fav_artists=[],
    )
    db_session.add(user)
    await db_session.commit()

    db_session.add(
        ArtistWatchlist(
            user_id=user.id,
            artist_name="Old Artist",
            normalized_name="old artist",
            source="history",
            weight=1.0,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    await _rebuild_watchlist_for_users(db_session, [user])

    result = await db_session.execute(select(ArtistWatchlist).where(ArtistWatchlist.user_id == user.id))
    rows = result.scalars().all()
    assert rows == []
