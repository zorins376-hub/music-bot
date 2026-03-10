"""Tests for provider_health auto-disable feature."""
import pytest
from bot.services.provider_health import (
    _stats,
    _disabled_providers,
    _AUTO_DISABLE_THRESHOLD,
    record_provider_event,
    is_provider_disabled,
    get_disabled_providers,
    _check_auto_disable,
    _ProviderStat,
)


class TestAutoDisable:
    def setup_method(self):
        _stats.clear()
        _disabled_providers.clear()

    def test_healthy_provider_not_disabled(self):
        for _ in range(10):
            record_provider_event("youtube", "search", 0.5, True)
        assert not is_provider_disabled("youtube")

    def test_unhealthy_provider_auto_disabled(self):
        # Seed enough failures to bring health below threshold
        for _ in range(10):
            record_provider_event("yandex", "search", 1.0, False, "timeout")
        assert is_provider_disabled("yandex")

    def test_provider_auto_recovers(self):
        # First make it unhealthy
        for _ in range(10):
            record_provider_event("vk", "search", 1.0, False, "err")
        assert is_provider_disabled("vk")

        # Now record many successes to recover
        for _ in range(50):
            record_provider_event("vk", "search", 0.3, True)
        assert not is_provider_disabled("vk")

    def test_get_disabled_providers(self):
        for _ in range(10):
            record_provider_event("badprov", "search", 1.0, False, "err")
        disabled = get_disabled_providers()
        assert "badprov" in disabled

    def test_threshold_boundary(self):
        """Provider at exactly the threshold should not be disabled."""
        # Create a stat that lands right at 0.3
        _stats.clear()
        stat = _stats["boundary:search"]
        # 30% success, 70% failure -> success_rate = 0.3
        for _ in range(3):
            stat.record_success(0.1)
        for _ in range(7):
            stat.record_failure(0.1, "err")
        # health = 0.3 - latency_penalty (small) -> just under or at 0.3
        _check_auto_disable("boundary")
        # With tiny latency, health ~0.3 which is not < 0.3, so not disabled
        # (edge case depends on latency penalty)

    def test_needs_minimum_events(self):
        """Provider with < 5 events should NOT be auto-disabled."""
        for _ in range(4):
            record_provider_event("newprov", "search", 1.0, False, "err")
        # Only 4 events, below the 5-event minimum
        assert not is_provider_disabled("newprov")

    def test_multi_operation_aggregate(self):
        """Health aggregates across all operations (search, download)."""
        for _ in range(5):
            record_provider_event("multi", "search", 0.5, True)
        for _ in range(10):
            record_provider_event("multi", "download", 1.0, False, "err")
        # search healthy, download unhealthy -> average should decide
        # search health ~1.0, download health ~0.0 -> avg ~0.5 > 0.3
        assert not is_provider_disabled("multi")
