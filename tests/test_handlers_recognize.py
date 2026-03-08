"""
Тесты для bot/handlers/recognize.py — Shazam-распознавание.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.recognize import _cleanup, _MAX_FILE_SIZE, _MIN_DURATION


class TestCleanup:
    def test_cleans_existing_files(self, tmp_path):
        f1 = tmp_path / "a.ogg"
        f2 = tmp_path / "b.wav"
        f1.write_bytes(b"audio")
        f2.write_bytes(b"wav")
        _cleanup(f1, f2)
        assert not f1.exists()
        assert not f2.exists()

    def test_handles_none(self):
        _cleanup(None, None)  # Should not raise

    def test_handles_nonexistent(self, tmp_path):
        _cleanup(tmp_path / "nonexistent.wav")  # Should not raise


class TestConstants:
    def test_max_file_size(self):
        assert _MAX_FILE_SIZE == 20 * 1024 * 1024

    def test_min_duration(self):
        assert _MIN_DURATION == 5


@pytest.mark.asyncio
class TestHandleVoice:
    async def test_too_short_voice(self):
        from bot.handlers.recognize import handle_voice

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.voice = MagicMock()
        msg.voice.duration = 2  # less than _MIN_DURATION
        msg.voice.file_size = 1000
        msg.voice.file_id = "file_id"
        msg.answer = AsyncMock()

        with patch("bot.handlers.recognize.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_voice(msg)

        msg.answer.assert_called_once()

    async def test_too_large_voice(self):
        from bot.handlers.recognize import handle_voice

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.voice = MagicMock()
        msg.voice.duration = 10
        msg.voice.file_size = _MAX_FILE_SIZE + 1
        msg.voice.file_id = "file_id"
        msg.answer = AsyncMock()

        with patch("bot.handlers.recognize.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_voice(msg)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleAudio:
    async def test_too_short_audio(self):
        from bot.handlers.recognize import handle_audio

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.audio = MagicMock()
        msg.audio.duration = 2
        msg.audio.file_size = 1000
        msg.audio.file_id = "file_id"
        msg.answer = AsyncMock()

        with patch("bot.handlers.recognize.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_audio(msg)

        msg.answer.assert_called_once()

    async def test_too_large_audio(self):
        from bot.handlers.recognize import handle_audio

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.audio = MagicMock()
        msg.audio.duration = 30
        msg.audio.file_size = _MAX_FILE_SIZE + 1
        msg.audio.file_id = "file_id"
        msg.answer = AsyncMock()

        with patch("bot.handlers.recognize.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_audio(msg)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleVideoNote:
    async def test_too_short_video_note(self):
        from bot.handlers.recognize import handle_video_note

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.video_note = MagicMock()
        msg.video_note.duration = 3
        msg.video_note.file_size = 1000
        msg.video_note.file_id = "file_id"
        msg.answer = AsyncMock()

        with patch("bot.handlers.recognize.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_video_note(msg)

        msg.answer.assert_called_once()
