"""Tests for YouTube cookie validation and auth error detection."""
import pytest
from pathlib import Path


def _sample_netscape(*names: str) -> str:
    lines = ["# Netscape HTTP Cookie File", ""]
    for name in names:
        lines.append(
            f".youtube.com\tTRUE\t/\tTRUE\t1893456000\t{name}\tvalue_{name}"
        )
    return "\n".join(lines) + "\n"


class TestIsYoutubeAuthError:
    def test_bot_check(self):
        from bot.services.youtube_cookies import is_youtube_auth_error
        assert is_youtube_auth_error("Sign in to confirm you're not a bot")
        assert is_youtube_auth_error("HTTP Error 403: Forbidden")

    def test_normal_error(self):
        from bot.services.youtube_cookies import is_youtube_auth_error
        assert not is_youtube_auth_error("Video unavailable")


class TestIsYoutubeProxyError:
    def test_unable_to_connect(self):
        from bot.services.youtube_cookies import is_youtube_proxy_error
        assert is_youtube_proxy_error("ERROR: Unable to connect to proxy")

    def test_proxy_403(self):
        from bot.services.youtube_cookies import is_youtube_proxy_error
        assert is_youtube_proxy_error(
            "ERROR: [urllib] tunnel connection failed: 403 Forbidden via proxy"
        )

    def test_plain_yt_403_not_proxy(self):
        from bot.services.youtube_cookies import (
            is_youtube_auth_error,
            is_youtube_proxy_error,
        )
        err = "HTTP Error 403: Forbidden"
        assert not is_youtube_proxy_error(err)
        assert is_youtube_auth_error(err)


class TestProbeExtractProxyFailure:
    def test_proxy_403_returns_probe_failed(self, monkeypatch):
        from bot.services import youtube_cookies as yc

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download=False):
                raise Exception(
                    "ERROR: Unable to download webpage: HTTP Error 403: "
                    "Forbidden (caused by ProxyError); proxy 403 Forbidden"
                )

        monkeypatch.setattr(yc.yt_dlp, "YoutubeDL", FakeYDL)
        ok, err = yc._probe_extract(
            "https://www.youtube.com/watch?v=x",
            cookiefile=None,
            has_auth_cookies=False,
        )
        assert ok is False
        assert err
        assert "proxy" in err.lower()

    def test_unable_connect_proxy_returns_probe_failed(self, monkeypatch):
        from bot.services import youtube_cookies as yc

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download=False):
                raise Exception("ERROR: Unable to connect to proxy")

        monkeypatch.setattr(yc.yt_dlp, "YoutubeDL", FakeYDL)
        ok, err = yc._probe_extract(
            "https://www.youtube.com/watch?v=x",
            cookiefile=None,
            has_auth_cookies=False,
        )
        assert ok is False
        assert "Unable to connect to proxy" in err


class TestValidateCookieFile:
    def test_missing_file(self, tmp_path, monkeypatch):
        from bot.services import youtube_cookies as yc
        missing = tmp_path / "nope.txt"
        info = yc.validate_cookie_file(missing)
        assert info["exists"] is False
        assert info["valid"] is False

    def test_valid_auth_cookies(self, tmp_path):
        from bot.services.youtube_cookies import validate_cookie_file
        path = tmp_path / "cookies.txt"
        path.write_text(_sample_netscape("SAPISID", "SSID"), encoding="utf-8")
        info = validate_cookie_file(path)
        assert info["valid"] is True
        assert "SAPISID" in info["auth_cookies"]

    def test_no_auth_cookies(self, tmp_path):
        from bot.services.youtube_cookies import validate_cookie_file
        path = tmp_path / "cookies.txt"
        path.write_text(
            ".youtube.com\tTRUE\t/\tFALSE\t0\tVISITOR_INFO1_LIVE\tx\n",
            encoding="utf-8",
        )
        info = validate_cookie_file(path)
        assert info["valid"] is False
        assert info["error"]


class TestSaveCookiesContent:
    def test_rejects_without_auth(self, tmp_path, monkeypatch):
        from bot.services import youtube_cookies as yc
        path = tmp_path / "cookies.txt"
        monkeypatch.setattr(yc, "_COOKIES_PATH", path)
        raw = _sample_netscape("VISITOR_INFO1_LIVE").encode("utf-8")
        ok, msg = yc.save_cookies_content(raw)
        assert ok is False
        assert "auth" in msg.lower()

    def test_accepts_auth_cookies(self, tmp_path, monkeypatch):
        from bot.services import youtube_cookies as yc
        path = tmp_path / "cookies.txt"
        monkeypatch.setattr(yc, "_COOKIES_PATH", path)
        raw = _sample_netscape("SAPISID", "SSID").encode("utf-8")
        ok, msg = yc.save_cookies_content(raw)
        assert ok is True
        assert path.exists()


class TestClassifyDownloadError:
    def test_yt_auth_key(self):
        from bot.handlers.search import _classify_download_error
        assert _classify_download_error("HTTP Error 403: Forbidden") == "error_yt_auth"


class TestIsYoutubeRateLimitError:
    def test_rate_limited(self):
        from bot.services.youtube_cookies import is_youtube_rate_limit_error
        assert is_youtube_rate_limit_error(
            "rate-limited by YouTube for up to an hour"
        )

    def test_try_again_later(self):
        from bot.services.youtube_cookies import is_youtube_rate_limit_error
        assert is_youtube_rate_limit_error("content not available, try again later")

    def test_auth_error_is_not_rate_limit(self):
        from bot.services.youtube_cookies import is_youtube_rate_limit_error
        assert not is_youtube_rate_limit_error("Sign in to confirm you're not a bot")


@pytest.mark.asyncio
class TestHandleAuthFailureGating:
    @pytest.fixture(autouse=True)
    def _reset_counter(self):
        from bot.services import youtube_cookies as yc
        yc._consecutive_auth_fails = 0
        yield
        yc._consecutive_auth_fails = 0

    async def test_rate_limit_never_alerts(self, monkeypatch):
        from bot.services import youtube_cookies as yc
        from unittest.mock import AsyncMock

        send = AsyncMock()
        monkeypatch.setattr(yc, "_admin_alert", send)
        await yc.handle_auth_failure(
            "rate-limited by YouTube for up to an hour", context="download X"
        )
        send.assert_not_awaited()
        # Rate-limit must not count against the streak.
        assert yc._consecutive_auth_fails == 0

    async def test_single_failure_does_not_alert(self, monkeypatch):
        from bot.services import youtube_cookies as yc
        from unittest.mock import AsyncMock

        send = AsyncMock()
        monkeypatch.setattr(yc, "_admin_alert", send)
        await yc.handle_auth_failure(
            "Sign in to confirm you're not a bot", context="download X"
        )
        send.assert_not_awaited()
        assert yc._consecutive_auth_fails == 1

    async def test_consecutive_failures_alert(self, monkeypatch):
        from bot.services import youtube_cookies as yc
        from unittest.mock import AsyncMock

        send = AsyncMock()
        monkeypatch.setattr(yc, "_admin_alert", send)
        err = "Sign in to confirm you're not a bot"
        await yc.handle_auth_failure(err, context="download X")
        await yc.handle_auth_failure(err, context="download Y")
        send.assert_awaited_once()

    async def test_success_resets_streak(self, monkeypatch):
        from bot.services import youtube_cookies as yc
        from unittest.mock import AsyncMock

        send = AsyncMock()
        monkeypatch.setattr(yc, "_admin_alert", send)
        err = "Sign in to confirm you're not a bot"
        await yc.handle_auth_failure(err, context="download X")
        yc.note_download_success()
        assert yc._consecutive_auth_fails == 0
        # After reset, a single new failure should not alert.
        await yc.handle_auth_failure(err, context="download Z")
        send.assert_not_awaited()
