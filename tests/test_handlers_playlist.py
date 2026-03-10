"""Tests for bot/handlers/playlist.py — CRUD, play, shuffle, add/remove tracks."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message, make_tg_user


def _make_user(lang="ru", user_id=1):
    u = MagicMock()
    u.id = user_id
    u.language = lang
    return u


def _make_playlist(pl_id=1, user_id=1, name="My Playlist"):
    pl = MagicMock()
    pl.id = pl_id
    pl.user_id = user_id
    pl.name = name
    return pl


def _make_track(track_id=1, title="Song", artist="Artist", duration=200, file_id="fid123"):
    tr = MagicMock()
    tr.id = track_id
    tr.title = title
    tr.artist = artist
    tr.duration = duration
    tr.file_id = file_id
    tr.source_id = f"src_{track_id}"
    return tr


# ── Constants ────────────────────────────────────────────────────────────

class TestConstants:
    def test_max_playlists(self):
        from bot.handlers.playlist import MAX_PLAYLISTS
        assert MAX_PLAYLISTS == 20

    def test_max_tracks_per_playlist(self):
        from bot.handlers.playlist import MAX_TRACKS_PER_PLAYLIST
        assert MAX_TRACKS_PER_PLAYLIST == 50


# ── _playlists_keyboard ─────────────────────────────────────────────────

class TestPlaylistsKeyboard:
    def test_keyboard_with_playlists(self):
        from bot.handlers.playlist import _playlists_keyboard
        pls = [_make_playlist(i, name=f"PL {i}") for i in range(3)]
        kb = _playlists_keyboard(pls, "ru")
        # 3 playlist buttons + 1 create button
        assert len(kb.inline_keyboard) == 4
        assert "PL 0" in kb.inline_keyboard[0][0].text
        assert "PL 2" in kb.inline_keyboard[2][0].text

    def test_keyboard_empty(self):
        from bot.handlers.playlist import _playlists_keyboard
        kb = _playlists_keyboard([], "ru")
        assert len(kb.inline_keyboard) == 1  # only create button


# ── _playlist_view_kb ────────────────────────────────────────────────────

class TestPlaylistViewKb:
    def test_view_with_tracks(self):
        from bot.handlers.playlist import _playlist_view_kb
        pt = MagicMock()
        pt.id = 10
        tr = _make_track()
        tracks = [(pt, tr)]
        kb = _playlist_view_kb(1, tracks, "ru", page=0)
        # play all/shuffle row + track row + delete/back row
        assert len(kb.inline_keyboard) >= 3

    def test_view_empty_tracks(self):
        from bot.handlers.playlist import _playlist_view_kb
        kb = _playlist_view_kb(1, [], "ru", page=0)
        # only delete/back row (no play all/shuffle when empty)
        assert len(kb.inline_keyboard) >= 1

    def test_view_pagination(self):
        from bot.handlers.playlist import _playlist_view_kb
        pt = MagicMock()
        pt.id = 10
        tr = _make_track()
        tracks = [(pt, tr)] * 15  # more than 10
        kb = _playlist_view_kb(1, tracks, "ru", page=0)
        # should have navigation button for next page
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "▷" in texts

    def test_view_page_2_has_prev(self):
        from bot.handlers.playlist import _playlist_view_kb
        pt = MagicMock()
        pt.id = 10
        tr = _make_track()
        tracks = [(pt, tr)] * 15
        kb = _playlist_view_kb(1, tracks, "ru", page=1)
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "◁" in texts


# ── cmd_playlist ─────────────────────────────────────────────────────────

class TestCmdPlaylist:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._show_playlists", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_cmd_playlist(self, mock_goc, mock_show):
        from bot.handlers.playlist import cmd_playlist
        mock_goc.return_value = _make_user()
        msg = make_message("/playlist")
        await cmd_playlist(msg)
        mock_show.assert_called_once_with(msg, 1, "ru", edit=False)


# ── cb_playlist (callback) ──────────────────────────────────────────────

class TestCbPlaylist:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._show_playlists", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_cb_playlist(self, mock_goc, mock_show):
        from bot.handlers.playlist import cb_playlist
        mock_goc.return_value = _make_user()
        cb = make_callback("action:playlist")
        await cb_playlist(cb)
        cb.answer.assert_called_once()
        mock_show.assert_called_once()


# ── Create playlist ──────────────────────────────────────────────────────

class TestCreatePlaylist:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_create_at_limit(self, mock_goc, mock_sess):
        from bot.handlers.playlist import cb_create_start, MAX_PLAYLISTS
        mock_goc.return_value = _make_user()
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=MAX_PLAYLISTS)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        state = AsyncMock()
        await cb_create_start(cb, state)
        cb.answer.assert_called()
        state.set_state.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._show_playlists", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_create_playlist_name(self, mock_goc, mock_sess, mock_show):
        from bot.handlers.playlist import create_playlist_name
        mock_goc.return_value = _make_user()
        session = AsyncMock()
        session.add = MagicMock()
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        msg = make_message("My New Playlist")
        msg.text = "My New Playlist"
        state = AsyncMock()
        await create_playlist_name(msg, state)
        state.clear.assert_called_once()
        msg.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_create_playlist_empty_name(self, mock_goc):
        from bot.handlers.playlist import create_playlist_name
        mock_goc.return_value = _make_user()
        msg = make_message("")
        msg.text = ""
        state = AsyncMock()
        await create_playlist_name(msg, state)
        state.clear.assert_not_called()


# ── Delete playlist ──────────────────────────────────────────────────────

class TestDeletePlaylist:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_delete_confirm_shows_keyboard(self, mock_goc):
        from bot.handlers.playlist import cb_delete_confirm, PlCb
        mock_goc.return_value = _make_user()
        cb = make_callback()
        cb_data = PlCb(act="del", id=1)
        await cb_delete_confirm(cb, cb_data)
        cb.answer.assert_called()
        cb.message.edit_text.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._show_playlists", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_delete_exec(self, mock_goc, mock_sess, mock_show):
        from bot.handlers.playlist import cb_delete_exec, PlCb
        user = _make_user()
        mock_goc.return_value = user
        pl = _make_playlist(user_id=1)
        session = AsyncMock()
        session.get = AsyncMock(return_value=pl)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        cb_data = PlCb(act="delcf", id=1)
        await cb_delete_exec(cb, cb_data)
        session.delete.assert_called_once_with(pl)

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_delete_not_owner(self, mock_goc, mock_sess):
        from bot.handlers.playlist import cb_delete_exec, PlCb
        mock_goc.return_value = _make_user(user_id=1)
        pl = _make_playlist(user_id=999)  # different owner
        session = AsyncMock()
        session.get = AsyncMock(return_value=pl)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        cb_data = PlCb(act="delcf", id=1)
        await cb_delete_exec(cb, cb_data)
        cb.answer.assert_called()
        session.delete.assert_not_called()


# ── Play track from playlist ─────────────────────────────────────────────

class TestPlayTrack:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_play_track_with_file_id(self, mock_goc, mock_sess):
        from bot.handlers.playlist import cb_play_track, PlCb
        mock_goc.return_value = _make_user()
        tr = _make_track()
        session = AsyncMock()
        session.get = AsyncMock(return_value=tr)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        cb_data = PlCb(act="play", id=1, tid=1)
        await cb_play_track(cb, cb_data)
        cb.message.answer_audio.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_play_track_no_file_id(self, mock_goc, mock_sess):
        from bot.handlers.playlist import cb_play_track, PlCb
        mock_goc.return_value = _make_user()
        tr = _make_track(file_id=None)
        session = AsyncMock()
        session.get = AsyncMock(return_value=tr)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        cb_data = PlCb(act="play", id=1, tid=1)
        await cb_play_track(cb, cb_data)
        cb.message.answer.assert_called()  # "no file" message


# ── Remove track ─────────────────────────────────────────────────────────

class TestRemoveTrack:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.cb_view", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.async_session")
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_remove_track(self, mock_goc, mock_sess, mock_view):
        from bot.handlers.playlist import cb_remove_track, PlCb
        mock_goc.return_value = _make_user()
        pt = MagicMock()
        pt.playlist_id = 1
        pl = _make_playlist()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda cls, id: pt if id == 10 else pl)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback()
        cb_data = PlCb(act="rm", id=1, tid=10)
        await cb_remove_track(cb, cb_data)
        session.delete.assert_called_once_with(pt)


# ── PlCb callback data ──────────────────────────────────────────────────

class TestPlCbCallbackData:
    def test_pack_unpack(self):
        from bot.handlers.playlist import PlCb
        cb = PlCb(act="view", id=5, tid=10, p=2)
        packed = cb.pack()
        assert "view" in packed
        unpacked = PlCb.unpack(packed)
        assert unpacked.act == "view"
        assert unpacked.id == 5
        assert unpacked.tid == 10
        assert unpacked.p == 2

    def test_defaults(self):
        from bot.handlers.playlist import PlCb
        cb = PlCb(act="list")
        assert cb.id == 0
        assert cb.tid == 0
        assert cb.p == 0


# ── AddToPlCb ────────────────────────────────────────────────────────────

class TestAddToPlCb:
    def test_pack_unpack(self):
        from bot.handlers.playlist import AddToPlCb
        cb = AddToPlCb(tid=42, pid=5)
        packed = cb.pack()
        unpacked = AddToPlCb.unpack(packed)
        assert unpacked.tid == 42
        assert unpacked.pid == 5

    def test_default_pid(self):
        from bot.handlers.playlist import AddToPlCb
        cb = AddToPlCb(tid=42)
        assert cb.pid == 0


# ── /playlist export ────────────────────────────────────────────────────

class TestPlaylistExportCommand:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._export_playlist_by_name", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_cmd_playlist_export_calls_export_by_name(self, mock_goc, mock_export):
        from bot.handlers.playlist import cmd_playlist
        mock_goc.return_value = _make_user(user_id=10)
        msg = make_message("/playlist export My Mix")
        msg.text = "/playlist export My Mix"

        await cmd_playlist(msg)

        mock_export.assert_awaited_once_with(msg, 10, "ru", "My Mix")

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist._show_playlists", new_callable=AsyncMock)
    @patch("bot.handlers.playlist.get_or_create_user", new_callable=AsyncMock)
    async def test_cmd_playlist_export_requires_name(self, mock_goc, mock_show):
        from bot.handlers.playlist import cmd_playlist
        mock_goc.return_value = _make_user(user_id=10)
        msg = make_message("/playlist export")
        msg.text = "/playlist export"

        await cmd_playlist(msg)

        msg.answer.assert_called_once()
        mock_show.assert_not_called()


class TestExportPlaylistByName:
    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    async def test_export_playlist_by_name_sends_document(self, mock_sess):
        from bot.handlers.playlist import _export_playlist_by_name

        pl = _make_playlist(pl_id=5, user_id=1, name="My Mix")
        tr = _make_track(track_id=1, title="Song", artist="Artist", duration=120)

        scalar_result = MagicMock()
        scalar_result.scalars.return_value.all.return_value = [tr]

        session = AsyncMock()
        session.scalar = AsyncMock(return_value=pl)
        session.execute = AsyncMock(return_value=scalar_result)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        msg = make_message("/playlist export My Mix")
        msg.answer_document = AsyncMock()

        await _export_playlist_by_name(msg, user_id=1, lang="ru", playlist_name="My Mix")

        msg.answer_document.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.playlist.async_session")
    async def test_export_playlist_by_name_not_found(self, mock_sess):
        from bot.handlers.playlist import _export_playlist_by_name

        session = AsyncMock()
        session.scalar = AsyncMock(return_value=None)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        msg = make_message("/playlist export Unknown")
        await _export_playlist_by_name(msg, user_id=1, lang="ru", playlist_name="Unknown")

        msg.answer.assert_called_once()
