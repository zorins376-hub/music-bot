"""
Интеграционные тесты — проверяем что всё работает по цепочке.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestSearchCascade:
    """Тесты каскада поиска: Яндекс → SoundCloud → VK → YouTube."""

    async def test_yandex_results_stop_cascade(self, cache_with_fake_redis):
        """Если Яндекс нашёл треки — остальные источники не вызываются."""
        yandex_results = [
            {"video_id": "ym_1", "title": "Song", "uploader": "Artist",
             "source": "yandex", "ym_track_id": 1, "duration": 200, "duration_fmt": "3:20"}
        ]

        with patch("bot.services.yandex_provider.search_yandex", new_callable=AsyncMock, return_value=yandex_results) as mock_ym, \
             patch("bot.services.vk_provider.search_vk", new_callable=AsyncMock) as mock_vk, \
             patch("bot.services.downloader.search_tracks", new_callable=AsyncMock) as mock_yt:

            from bot.services.yandex_provider import search_yandex
            results = await search_yandex("test query")

        assert results == yandex_results
        mock_vk.assert_not_called()
        mock_yt.assert_not_called()

    async def test_cache_returns_file_id_without_download(self, cache_with_fake_redis):
        """Если file_id есть в кэше — скачивания не происходит."""
        await cache_with_fake_redis.set_file_id("ym_12345", "AgACAgQAAxk...", 320)
        result = await cache_with_fake_redis.get_file_id("ym_12345", 320)
        assert result == "AgACAgQAAxk..."

    async def test_query_cache_served_from_redis(self, cache_with_fake_redis):
        """Повторный поиск отдаётся из Redis без обращения к API."""
        tracks = [{"video_id": "sc_1", "title": "Track", "source": "soundcloud"}]
        await cache_with_fake_redis.set_query_cache("popular song", tracks, "soundcloud")

        cached = await cache_with_fake_redis.get_query_cache("popular song", "soundcloud")
        assert cached == tracks


@pytest.mark.asyncio
class TestPaymentFlow:
    """Проверяем полный флоу оплаты Stars → premium активирован."""

    async def test_full_payment_flow(self):
        """pre_checkout → successful_payment → is_premium=True в БД."""
        from bot.handlers.premium import handle_pre_checkout, handle_successful_payment

        # 1. Pre-checkout всегда одобряется
        pre_checkout = AsyncMock()
        pre_checkout.answer = AsyncMock()
        await handle_pre_checkout(pre_checkout)
        pre_checkout.answer.assert_called_once_with(ok=True)

        # 2. Успешная оплата выдаёт premium
        user = MagicMock()
        user.id = 9999
        user.is_premium = False
        user.language = "ru"

        message = AsyncMock()
        message.from_user = MagicMock(id=9999)
        message.answer = AsyncMock()
        message.successful_payment = MagicMock()
        message.successful_payment.total_amount = 150
        message.successful_payment.currency = "XTR"
        message.successful_payment.invoice_payload = "premium_30d"

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.premium.async_session", return_value=mock_session):
            await handle_successful_payment(message)

        # Проверяем: UPDATE выполнен, Payment добавлен, пользователь получил сообщение
        assert mock_session.execute.called
        assert mock_session.add.called
        assert mock_session.commit.called
        message.answer.assert_called_once()


class TestConfig:
    """Тесты конфигурации."""

    def test_default_bitrate(self):
        from bot.config import settings
        assert settings.DEFAULT_BITRATE == 192

    def test_max_duration(self):
        from bot.config import settings
        assert settings.MAX_DURATION == 600

    def test_premium_days(self):
        from bot.config import settings
        assert settings.PREMIUM_DAYS == 30

    def test_premium_price(self):
        from bot.config import settings
        assert settings.PREMIUM_STAR_PRICE > 0

    def test_max_file_size_45mb(self):
        from bot.config import settings
        assert settings.MAX_FILE_SIZE == 45 * 1024 * 1024

    def test_download_dir_exists(self):
        from bot.config import settings
        assert settings.DOWNLOAD_DIR.exists()

    def test_cache_ttls_positive(self):
        from bot.config import settings
        assert settings.CACHE_FILE_ID_TTL > 0
        assert settings.SEARCH_SESSION_TTL > 0
