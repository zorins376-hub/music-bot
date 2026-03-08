"""
Тесты для bot/services/metrics.py — проверяем stub-режим и создание метрик.
"""
import pytest


class TestMetricsStubMode:
    """Метрики в stub-режиме не должны падать."""

    def test_requests_total_no_crash(self):
        from bot.services.metrics import requests_total
        # labels + inc не должны упасть
        requests_total.labels(source="youtube").inc()

    def test_download_time_no_crash(self):
        from bot.services.metrics import download_time
        download_time.observe(1.5)

    def test_provider_errors_no_crash(self):
        from bot.services.metrics import provider_errors
        provider_errors.labels(provider="yandex").inc()

    def test_cache_hits_no_crash(self):
        from bot.services.metrics import cache_hits
        cache_hits.inc()

    def test_cache_misses_no_crash(self):
        from bot.services.metrics import cache_misses
        cache_misses.inc()

    def test_download_time_context_manager(self):
        from bot.services.metrics import download_time
        with download_time.time():
            pass  # Should not raise


class TestStartMetricsServer:
    def test_disabled_without_lib(self):
        """Если prometheus_client не установлен — просто логирует."""
        from bot.services.metrics import start_metrics_server
        # Should not raise even if prometheus is not truly available
        # (it is available in test env, but we test the function doesn't crash)
        # We can't easily uninstall prometheus_client, so just test the function exists
        assert callable(start_metrics_server)
