"""Tests for new features: AI Playlist, Import, Achievements, DMCA filter."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════ AI Playlist Service ════════════════

class TestAiPlaylistFallback:
    """Test keyword-based playlist generation (no OpenAI key)."""

    def test_genre_extraction(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("рок плейлист для вечера")
        assert len(queries) > 0
        assert any("rock" in q.lower() for q in queries)

    def test_mood_extraction(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("грустная музыка")
        assert len(queries) > 0
        assert any("sad" in q.lower() for q in queries)

    def test_artist_extraction(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("что-то похожее на Drake")
        assert len(queries) > 0
        assert any("drake" in q.lower() for q in queries)

    def test_combined_genre_mood(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("энергичный рок")
        assert len(queries) > 0

    def test_raw_prompt_fallback(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("кайф под звёзды ночью")
        assert len(queries) > 0

    def test_empty_prompt(self):
        from bot.services.ai_playlist import _generate_queries_fallback
        queries = _generate_queries_fallback("")
        # May return empty or generic queries
        assert isinstance(queries, list)

    @pytest.mark.asyncio
    async def test_generate_ai_playlist_no_openai(self):
        """Test full pipeline without OpenAI key."""
        mock_tracks = [
            {"video_id": "abc123", "title": "Test Track", "uploader": "Artist",
             "duration": 200, "duration_fmt": "3:20", "source": "youtube"},
        ]
        with patch("bot.services.ai_playlist.settings") as mock_settings, \
             patch("bot.services.ai_playlist.search_tracks", new_callable=AsyncMock) as mock_search:
            mock_settings.OPENAI_API_KEY = None
            mock_search.return_value = mock_tracks
            from bot.services.ai_playlist import generate_ai_playlist
            result = await generate_ai_playlist("грустный рок", max_tracks=5)
            assert len(result) > 0
            mock_search.assert_called()

    @pytest.mark.asyncio
    async def test_deduplication(self):
        """Test that duplicate tracks are filtered."""
        same_track = {"video_id": "same123", "title": "Same", "uploader": "Same",
                      "duration": 200, "duration_fmt": "3:20", "source": "youtube"}
        with patch("bot.services.ai_playlist.settings") as mock_settings, \
             patch("bot.services.ai_playlist.search_tracks", new_callable=AsyncMock) as mock_search:
            mock_settings.OPENAI_API_KEY = None
            mock_search.return_value = [same_track]
            from bot.services.ai_playlist import generate_ai_playlist
            result = await generate_ai_playlist("поп музыка", max_tracks=10)
            # Even though multiple queries, same video_id should appear once
            ids = [t["video_id"] for t in result]
            assert len(ids) == len(set(ids))


# ═══════════════════════════════════ Playlist Import ════════════════

class TestPlaylistImport:

    def test_detect_spotify_url(self):
        from bot.services.playlist_import import detect_playlist_url
        assert detect_playlist_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M") == "spotify"

    def test_detect_yandex_url(self):
        from bot.services.playlist_import import detect_playlist_url
        assert detect_playlist_url("https://music.yandex.ru/users/user123/playlists/1000") == "yandex"

    def test_detect_invalid_url(self):
        from bot.services.playlist_import import detect_playlist_url
        assert detect_playlist_url("https://example.com/playlist") is None

    def test_detect_spotify_intl_url(self):
        from bot.services.playlist_import import detect_playlist_url
        assert detect_playlist_url("https://open.spotify.com/intl-ru/playlist/37i9dQZF1DXcBWI") == "spotify"

    def test_detect_plain_text(self):
        from bot.services.playlist_import import detect_playlist_url
        assert detect_playlist_url("hello world") is None


# ═══════════════════════════════════ DMCA Filter ════════════════

class TestDmcaFilter:

    def test_filter_blocked_empty(self):
        from bot.services.dmca_filter import filter_blocked, _blocked_ids
        _blocked_ids.clear()
        tracks = [{"video_id": "abc"}, {"video_id": "def"}]
        result = filter_blocked(tracks)
        assert len(result) == 2

    def test_filter_blocked_removes(self):
        from bot.services.dmca_filter import filter_blocked, _blocked_ids
        _blocked_ids.clear()
        _blocked_ids.add("blocked1")
        tracks = [
            {"video_id": "ok1"},
            {"video_id": "blocked1"},
            {"video_id": "ok2"},
        ]
        result = filter_blocked(tracks)
        assert len(result) == 2
        assert all(t["video_id"] != "blocked1" for t in result)

    def test_is_blocked(self):
        from bot.services.dmca_filter import is_blocked, _blocked_ids
        _blocked_ids.clear()
        _blocked_ids.add("id123")
        assert is_blocked("id123") is True
        assert is_blocked("other") is False


# ═══════════════════════════════════ Achievements ════════════════

class TestAchievements:

    def test_badge_definitions_complete(self):
        from bot.services.achievements import BADGES
        for badge_id, badge in BADGES.items():
            assert "name" in badge
            assert "desc" in badge
            for lang in ("ru", "en", "kg"):
                assert lang in badge["name"], f"{badge_id} missing name for {lang}"
                assert lang in badge["desc"], f"{badge_id} missing desc for {lang}"

    def test_get_badge_display(self):
        from bot.services.achievements import get_badge_display
        name, desc = get_badge_display("first_play", "ru")
        assert "Первый" in name
        assert desc

    def test_get_badge_display_en(self):
        from bot.services.achievements import get_badge_display
        name, desc = get_badge_display("first_play", "en")
        assert "First" in name

    def test_get_badge_display_unknown(self):
        from bot.services.achievements import get_badge_display
        name, desc = get_badge_display("nonexistent", "ru")
        assert name == "nonexistent"


# ═══════════════════════════════════ AI Playlist Handler ════════════════

class TestAiPlaylistHandler:

    @pytest.mark.asyncio
    async def test_handle_ai_playlist_cmd(self):
        """Test /ai_playlist command enters waiting state."""
        from bot.handlers.ai_playlist import handle_ai_playlist_cmd
        message = AsyncMock()
        message.text = "/ai_playlist"
        message.from_user = MagicMock(id=123, username="test", first_name="Test",
                                       language_code="ru", is_bot=False)
        state = AsyncMock()
        user = MagicMock(language="ru", id=123, is_premium=False, onboarded=True)
        with patch("bot.handlers.ai_playlist.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_ai_playlist_cmd(message, state)
            message.answer.assert_called_once()
            state.set_state.assert_called_once()


# ═══════════════════════════════════ Import Handler ════════════════

class TestImportHandler:

    @pytest.mark.asyncio
    async def test_handle_import_cmd(self):
        """Test /import_playlist command enters waiting state."""
        from bot.handlers.import_playlist import handle_import_cmd
        message = AsyncMock()
        message.text = "/import_playlist"
        message.from_user = MagicMock(id=123, username="test", first_name="Test",
                                       language_code="ru", is_bot=False)
        state = AsyncMock()
        user = MagicMock(language="ru", id=123)
        with patch("bot.handlers.import_playlist.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_import_cmd(message, state)
            message.answer.assert_called_once()
            state.set_state.assert_called_once()


# ═══════════════════════════════════ Badges Handler ════════════════

class TestBadgesHandler:

    @pytest.mark.asyncio
    async def test_cmd_badges(self):
        """Test /badges command."""
        from bot.handlers.badges import cmd_badges
        message = AsyncMock()
        message.from_user = MagicMock(id=123, username="test", first_name="Test",
                                       language_code="ru", is_bot=False)
        user = MagicMock(language="ru", id=123, badges=None)
        with patch("bot.handlers.badges.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.badges.async_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=user)
            mock_session.return_value = mock_ctx
            await cmd_badges(message)
            message.answer.assert_called_once()


# ═══════════════════════════════════ i18n keys ════════════════

class TestI18nKeys:

    def test_new_keys_exist_ru(self):
        from bot.i18n import t
        keys = [
            "ai_playlist_prompt", "ai_playlist_generating",
            "ai_playlist_header", "ai_playlist_empty",
            "import_prompt", "import_detecting", "import_progress",
            "import_done", "import_empty", "import_invalid_url", "import_error",
            "badge_earned", "badges_header", "badges_empty",
        ]
        for key in keys:
            val = t("ru", key)
            assert val != key, f"Missing i18n key: {key} for ru"

    def test_new_keys_exist_en(self):
        from bot.i18n import t
        keys = [
            "ai_playlist_prompt", "ai_playlist_generating",
            "ai_playlist_header", "ai_playlist_empty",
            "import_prompt", "import_detecting",
            "badge_earned", "badges_header", "badges_empty",
        ]
        for key in keys:
            val = t("en", key)
            assert val != key, f"Missing i18n key: {key} for en"

    def test_new_keys_exist_kg(self):
        from bot.i18n import t
        keys = [
            "ai_playlist_prompt", "ai_playlist_generating",
            "ai_playlist_header", "ai_playlist_empty",
            "import_prompt", "badges_empty",
        ]
        for key in keys:
            val = t("kg", key)
            assert val != key, f"Missing i18n key: {key} for kg"


# ═══════════════════════════════════ BlockedTrack Model ════════════════

class TestBlockedTrackModel:

    def test_model_fields(self):
        from bot.models.blocked_track import BlockedTrack
        assert hasattr(BlockedTrack, "source_id")
        assert hasattr(BlockedTrack, "reason")
        assert hasattr(BlockedTrack, "blocked_by")
        assert hasattr(BlockedTrack, "created_at")
        assert BlockedTrack.__tablename__ == "blocked_tracks"
