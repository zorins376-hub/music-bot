"""
Тесты для bot/handlers/video.py — видео поиск и скачивание.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestCmdVideo:
    async def test_no_query_shows_prompt(self):
        from bot.handlers.video import cmd_video

        user = MagicMock()
        user.language = "ru"
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.text = "/video"
        msg.answer = AsyncMock()

        with patch("bot.handlers.video.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await cmd_video(msg)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleVideoButton:
    async def test_prompts_for_query(self):
        from bot.handlers.video import handle_video_button

        user = MagicMock()
        user.language = "ru"
        cb = AsyncMock()
        cb.from_user = MagicMock(id=100, username="t", first_name="T")
        cb.data = "action:video"
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()

        with patch("bot.handlers.video.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_video_button(cb)

        cb.answer.assert_called_once()
        # edit_text is tried first; answer is fallback
        assert cb.message.edit_text.called or cb.message.answer.called
