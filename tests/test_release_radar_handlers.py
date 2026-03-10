from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback


def _make_user(user_id=111, lang="ru", enabled=True):
    user = MagicMock()
    user.id = user_id
    user.language = lang
    user.release_radar_enabled = enabled
    return user


@pytest.mark.asyncio
@patch("bot.handlers.release_radar.track_event", new_callable=AsyncMock)
@patch("bot.handlers.release_radar.async_session")
@patch("bot.handlers.release_radar.get_or_create_user", new_callable=AsyncMock)
async def test_cb_radar_open_marks_opened_and_tracks_event(mock_get_user, mock_sess, mock_track):
    from bot.handlers.release_radar import cb_radar_open

    mock_get_user.return_value = _make_user()

    session = AsyncMock()
    mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

    callback = make_callback(data="radar:open", user_id=111)

    await cb_radar_open(callback)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    callback.answer.assert_called_once()
    callback.message.answer.assert_called_once()
    mock_track.assert_awaited_once_with(111, "release_open")


def test_next_radar_target_every_6_hours():
    from bot.services.release_radar import _next_radar_target

    now = datetime(2026, 3, 10, 10, 15, tzinfo=timezone.utc)
    target = _next_radar_target(now)
    assert target == datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    now2 = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)
    target2 = _next_radar_target(now2)
    assert target2 == datetime(2026, 3, 11, 0, 0, tzinfo=timezone.utc)
