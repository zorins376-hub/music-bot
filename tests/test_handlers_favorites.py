from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_user(user_id=111, lang="ru"):
    user = MagicMock()
    user.id = user_id
    user.language = lang
    return user


def _make_track(track_id: int):
    tr = MagicMock()
    tr.id = track_id
    tr.title = f"Track {track_id}"
    tr.artist = f"Artist {track_id}"
    tr.duration = 180
    return tr


@pytest.mark.asyncio
@patch("bot.handlers.favorites.get_favorite_tracks", new_callable=AsyncMock)
async def test_send_favorites_paginates_and_shows_nav(mock_get_tracks):
    from bot.handlers.favorites import send_favorites

    mock_get_tracks.return_value = [_make_track(i) for i in range(1, 24)]

    msg = AsyncMock()
    msg.answer = AsyncMock()

    await send_favorites(msg, user_id=1, lang="ru", page=0, edit=False)

    msg.answer.assert_called_once()
    _, kwargs = msg.answer.call_args
    kb = kwargs["reply_markup"]
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "▷" in texts
    assert "◁" not in texts


@pytest.mark.asyncio
@patch("bot.handlers.favorites.send_favorites", new_callable=AsyncMock)
@patch("bot.handlers.favorites.get_or_create_user", new_callable=AsyncMock)
async def test_cb_favorites_page_uses_requested_page(mock_get_user, mock_send):
    from bot.handlers.favorites import cb_favorites_page

    mock_get_user.return_value = _make_user(user_id=77)

    callback = AsyncMock()
    callback.data = "favpg:2"
    callback.from_user = MagicMock(id=77)
    callback.answer = AsyncMock()
    callback.message = AsyncMock()

    await cb_favorites_page(callback)

    callback.answer.assert_called_once()
    mock_send.assert_awaited_once_with(callback.message, 77, "ru", page=2, edit=True)


@pytest.mark.asyncio
@patch("bot.handlers.favorites.send_favorites", new_callable=AsyncMock)
@patch("bot.handlers.favorites.track_event", new_callable=AsyncMock)
@patch("bot.handlers.favorites.remove_favorite_track", new_callable=AsyncMock)
@patch("bot.handlers.favorites.get_or_create_user", new_callable=AsyncMock)
async def test_remove_favorite_refreshes_list(mock_get_user, mock_remove, mock_track_event, mock_send):
    from bot.callbacks import FavoriteCb
    from bot.handlers.favorites import handle_favorite_action

    mock_get_user.return_value = _make_user(user_id=55)
    mock_remove.return_value = True

    callback = AsyncMock()
    callback.from_user = MagicMock(id=55)
    callback.answer = AsyncMock()
    callback.message = AsyncMock()

    data = FavoriteCb(tid=123, act="del")
    await handle_favorite_action(callback, data)

    callback.answer.assert_called_once()
    mock_track_event.assert_awaited_once_with(55, "favorite_remove", track_id=123)
    mock_send.assert_awaited_once_with(callback.message, 55, "ru", page=0, edit=True)
