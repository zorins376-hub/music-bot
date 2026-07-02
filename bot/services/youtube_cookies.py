"""YouTube cookies lifecycle: validation, health probes, admin alerts."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import aiohttp
import yt_dlp

from bot.config import settings, sync_cookies_from_env
from bot.services.cache import cache

logger = logging.getLogger(__name__)

_COOKIES_PATH: Path = settings.DATA_DIR / "cookies.txt"

_ADMIN_ALERT_THROTTLE_KEY = "alert:yt_cookies_expired"
_ADMIN_ALERT_THROTTLE_SECONDS = 12 * 3600

_PROBE_VIDEO_ID = "jNQXAC9IVRw"
_PROBE_INTERVAL_SEC = 6 * 3600

_AUTH_ERROR_PATTERNS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
    "cookies are no longer valid",
    "http error 403",
    "unable to extract",
    "login required",
    "use --cookies-from-browser",
    "this content isn't available",
    "bot detection",
    "sign in to confirm your age",
)

_IP_BLOCK_HINT = "datacenter IP blocked by YouTube"
_PROXY_ERROR_HINT = "YouTube proxy unreachable or rejected"

_PROXY_ERROR_PATTERNS = (
    "unable to connect to proxy",
)

# Transient YouTube throttling — NOT a cookie/auth problem. These resolve on
# their own within an hour, so they must never trigger an admin cookie alert.
_RATE_LIMIT_PATTERNS = (
    "rate-limited",
    "rate limited",
    "try again later",
    "too many requests",
    "http error 429",
)

_RECOMMENDED_COOKIE_NAMES = frozenset({
    "SAPISID", "APISID", "SSID", "SID", "HSID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
})

_last_probe_ok: bool | None = None
_last_probe_at: float = 0.0
_last_probe_error: str | None = None

# Require this many consecutive auth-failure probes before alerting the admin,
# to avoid false alarms from transient/network blips.
_ALERT_AFTER_CONSECUTIVE_FAILS = 2
_consecutive_auth_fails: int = 0


def cookies_path() -> Path:
    return _COOKIES_PATH


def is_youtube_auth_error(error: BaseException | str) -> bool:
    msg = str(error).lower()
    if is_youtube_proxy_error(error):
        return False
    return any(pat in msg for pat in _AUTH_ERROR_PATTERNS)


def is_youtube_proxy_error(error: BaseException | str) -> bool:
    """True when yt-dlp failed due to proxy connectivity or proxy HTTP 403."""
    msg = str(error).lower()
    if any(pat in msg for pat in _PROXY_ERROR_PATTERNS):
        return True
    if "proxy" in msg and ("403" in msg or "forbidden" in msg):
        return True
    return False


def is_youtube_rate_limit_error(error: BaseException | str) -> bool:
    """True when the failure is transient YouTube throttling (not a cookie issue)."""
    msg = str(error).lower()
    return any(pat in msg for pat in _RATE_LIMIT_PATTERNS)


def note_download_success() -> None:
    """Reset the consecutive-failure streak after any successful YouTube fetch."""
    global _consecutive_auth_fails
    if _consecutive_auth_fails:
        logger.info(
            "YouTube fetch recovered after %d consecutive failure(s)",
            _consecutive_auth_fails,
        )
    _consecutive_auth_fails = 0


def _proxy_probe_message(error: str) -> str:
    return f"{_PROXY_ERROR_HINT}: {error[:300]}"


def parse_cookie_names(content: str) -> set[str]:
    names: set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6:
            names.add(parts[5])
    return names


def validate_cookie_file(path: Path | None = None) -> dict:
    """Return cookie file diagnostics for admin/status."""
    path = path or _COOKIES_PATH
    if not path.exists():
        return {
            "exists": False,
            "valid": False,
            "line_count": 0,
            "auth_cookies": [],
            "missing_recommended": sorted(_RECOMMENDED_COOKIE_NAMES),
            "error": "cookies.txt not found",
        }

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {
            "exists": True,
            "valid": False,
            "line_count": 0,
            "auth_cookies": [],
            "missing_recommended": sorted(_RECOMMENDED_COOKIE_NAMES),
            "error": str(e),
        }

    if "does not look like a Netscape format" in text:
        return {
            "exists": True,
            "valid": False,
            "line_count": 0,
            "auth_cookies": [],
            "missing_recommended": sorted(_RECOMMENDED_COOKIE_NAMES),
            "error": "not Netscape format",
        }

    names = parse_cookie_names(text)
    auth_found = sorted(names & _RECOMMENDED_COOKIE_NAMES)
    missing = sorted(_RECOMMENDED_COOKIE_NAMES - names)
    line_count = sum(
        1 for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )
    valid = line_count > 0 and bool(auth_found)

    err = None
    if line_count == 0:
        err = "empty file"
    elif not auth_found:
        err = "no Google auth cookies (export while logged in to YouTube)"

    return {
        "exists": True,
        "valid": valid,
        "line_count": line_count,
        "auth_cookies": auth_found,
        "missing_recommended": missing,
        "error": err,
        "mtime": path.stat().st_mtime,
        "size": path.stat().st_size,
    }


def format_status_message() -> str:
    info = validate_cookie_file()
    probe = get_last_probe_status()
    lines = ["<b>YouTube cookies</b>", f"Path: <code>{_COOKIES_PATH}</code>"]
    if not info.get("exists"):
        lines.append("Status: missing")
    else:
        lines.append(
            f"File: {info.get('line_count', 0)} entries, "
            f"{info.get('size', 0)} bytes"
        )
        if info.get("auth_cookies"):
            lines.append(f"Auth cookies: {', '.join(info['auth_cookies'])}")
        else:
            lines.append("Auth cookies: none")
        if info.get("error"):
            lines.append(f"Warning: {info['error']}")
    lines.append(f"Last probe: {probe['summary']}")
    lines.append(
        "\nRefresh: send <code>cookies.txt</code> (Netscape) as a document, "
        "or set <code>YT_COOKIES</code> (base64) in .env and restart."
    )
    return "\n".join(lines)


def get_last_probe_status() -> dict:
    if _last_probe_at <= 0:
        return {"ok": None, "summary": "never run", "error": _last_probe_error}
    age_min = int((time.monotonic() - _last_probe_at) / 60)
    if _last_probe_ok:
        return {"ok": True, "summary": f"OK ({age_min}m ago)", "error": None}
    return {
        "ok": False,
        "summary": f"FAILED ({age_min}m ago)",
        "error": _last_probe_error,
    }


def save_cookies_content(raw: bytes) -> tuple[bool, str]:
    """Validate and atomically write cookies.txt."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False, "File must be UTF-8 text (Netscape cookies.txt)"

    info = validate_cookie_file_from_text(text)
    if info.get("line_count", 0) == 0:
        return False, "Empty or invalid Netscape cookies file"
    if not info.get("auth_cookies"):
        return False, (
            "No Google auth cookies found. Export from a logged-in browser "
            "(Chrome → youtube.com → extension 'Get cookies.txt LOCALLY')."
        )

    _COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _COOKIES_PATH.with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(_COOKIES_PATH)
    global _last_probe_ok, _last_probe_at
    _last_probe_ok = None
    _last_probe_at = 0.0
    logger.info(
        "YouTube cookies updated: %d lines, auth=%s",
        info["line_count"],
        info["auth_cookies"],
    )
    return True, f"Saved {info['line_count']} cookies ({len(info['auth_cookies'])} auth)"


def validate_cookie_file_from_text(text: str) -> dict:
    names = parse_cookie_names(text)
    auth_found = sorted(names & _RECOMMENDED_COOKIE_NAMES)
    line_count = sum(
        1 for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )
    return {
        "line_count": line_count,
        "auth_cookies": auth_found,
        "valid": line_count > 0 and bool(auth_found),
    }


async def handle_auth_failure(
    error: BaseException | str, *, context: str = "", count: bool = True
) -> None:
    """Log a YouTube failure and alert admins only after N *consecutive* real
    auth/cookie failures. Transient rate-limits are ignored entirely."""
    global _last_probe_ok, _last_probe_at, _last_probe_error, _consecutive_auth_fails
    msg = str(error)

    # Transient throttling is not a cookie problem — log only, never alert,
    # and don't count it against the consecutive-failure streak.
    if is_youtube_rate_limit_error(msg):
        logger.warning("YouTube rate-limited (transient, no alert): %s", msg[:200])
        return

    _last_probe_ok = False
    _last_probe_at = time.monotonic()
    _last_probe_error = msg[:500]

    if count:
        _consecutive_auth_fails += 1

    detail = f"{context}: {msg[:300]}" if context else msg[:300]
    logger.error(
        "YouTube auth/cookie failure (streak=%d/%d): %s",
        _consecutive_auth_fails, _ALERT_AFTER_CONSECUTIVE_FAILS, detail,
    )

    # Only escalate to admins once the failure looks persistent.
    if _consecutive_auth_fails < _ALERT_AFTER_CONSECUTIVE_FAILS:
        return

    await _admin_alert(
        "YouTube cookies or bot-check failed.\n"
        f"{detail}\n\n"
        "Refresh cookies: /admin ytcookies — then upload cookies.txt"
    )


async def _admin_alert(text: str) -> None:
    should_send = True
    try:
        throttle_ok = await cache.redis.set(
            _ADMIN_ALERT_THROTTLE_KEY,
            "1",
            ex=_ADMIN_ALERT_THROTTLE_SECONDS,
            nx=True,
        )
        should_send = bool(throttle_ok)
        await cache.redis.setex(
            "alert:yt_cookies_status",
            _ADMIN_ALERT_THROTTLE_SECONDS,
            text,
        )
    except Exception:
        logger.debug("yt cookies alert throttle redis failed", exc_info=True)

    if should_send:
        await _send_admin_telegram_alert(text)

    logger.error(text)


async def _send_admin_telegram_alert(text: str) -> None:
    if not getattr(settings, "YT_COOKIE_ALERT_TELEGRAM", True):
        return
    if not settings.BOT_TOKEN or not settings.ADMIN_IDS:
        return

    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    msg = f"⚠️ YouTube cookies alert\n\n{text}"

    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for admin_id in settings.ADMIN_IDS:
                try:
                    await session.post(
                        url,
                        json={"chat_id": int(admin_id), "text": msg},
                    )
                except Exception:
                    continue
    except Exception:
        return


def _probe_extract(url: str, *, cookiefile: str | None, has_auth_cookies: bool) -> tuple[bool, str | None]:
    from bot.services.downloader import _YtdlpSilentLogger, _base_opts

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _YtdlpSilentLogger(),
        "skip_download": True,
        "socket_timeout": 20,
        **_base_opts(has_auth_cookies=has_auth_cookies),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return False, "probe returned no metadata"
        return True, None
    except Exception as e:
        if is_youtube_proxy_error(e):
            return False, _proxy_probe_message(str(e))
        if is_youtube_auth_error(e):
            return False, str(e)
        logger.warning("YouTube probe non-auth error: %s", e)
        return True, None


def _probe_sync() -> tuple[bool, str | None]:
    from bot.services.downloader import _prepare_cookiefile, _cleanup_temp_cookie

    url = f"https://www.youtube.com/watch?v={_PROBE_VIDEO_ID}"
    cookie_info = validate_cookie_file()
    has_auth = bool(cookie_info.get("auth_cookies"))

    # PO token path without cookies — detects VPS/datacenter IP blocks early.
    ok_pot, err_pot = _probe_extract(url, cookiefile=None, has_auth_cookies=False)
    if ok_pot:
        if has_auth:
            cookiefile, temp_cookie = _prepare_cookiefile()
            try:
                ok_cookies, err_cookies = _probe_extract(
                    url, cookiefile=cookiefile, has_auth_cookies=True,
                )
                if ok_cookies:
                    return True, None
                if err_cookies and is_youtube_proxy_error(err_cookies):
                    return False, err_cookies
                if err_cookies and is_youtube_auth_error(err_cookies):
                    return False, err_cookies
                return True, None
            finally:
                _cleanup_temp_cookie(temp_cookie)
        return True, None

    if err_pot and is_youtube_auth_error(err_pot):
        if has_auth:
            cookiefile, temp_cookie = _prepare_cookiefile()
            try:
                ok_cookies, err_cookies = _probe_extract(
                    url, cookiefile=cookiefile, has_auth_cookies=True,
                )
                if ok_cookies:
                    return True, None
            finally:
                _cleanup_temp_cookie(temp_cookie)
        from bot.config import settings
        if not (getattr(settings, "YOUTUBE_PROXY", None) or "").strip():
            from bot.services.proxy_pool import proxy_pool
            if not proxy_pool.size:
                return False, (
                    f"{_IP_BLOCK_HINT}: configure YOUTUBE_PROXY or PROXY_POOL "
                    f"(residential). Detail: {err_pot[:200]}"
                )
        return False, err_pot

    if err_pot and is_youtube_proxy_error(err_pot):
        return False, err_pot

    return ok_pot, err_pot


async def run_health_probe(*, notify_on_failure: bool = True) -> bool:
    global _last_probe_ok, _last_probe_at, _last_probe_error, _consecutive_auth_fails
    loop = asyncio.get_running_loop()
    ok, err = await loop.run_in_executor(None, _probe_sync)
    _last_probe_ok = ok
    _last_probe_at = time.monotonic()
    _last_probe_error = err
    if ok:
        if _consecutive_auth_fails:
            logger.info("YouTube cookie probe recovered after %d failure(s)", _consecutive_auth_fails)
        _consecutive_auth_fails = 0
        logger.info("YouTube cookie health probe: OK")
    else:
        is_auth = bool(err and is_youtube_auth_error(err) and _IP_BLOCK_HINT not in err)
        if is_auth and notify_on_failure:
            # handle_auth_failure owns the consecutive-failure counting + gating.
            await handle_auth_failure(err, context="health probe")
        else:
            if is_auth:
                _consecutive_auth_fails += 1
            logger.warning(
                "YouTube cookie health probe failed (auth=%s, streak=%d): %s",
                is_auth, _consecutive_auth_fails, err,
            )
    return ok


async def startup_cookie_check() -> None:
    sync_cookies_from_env()
    info = validate_cookie_file()
    if info.get("exists"):
        logger.info(
            "YouTube cookies: %s lines, auth=%s, valid=%s",
            info.get("line_count"),
            info.get("auth_cookies"),
            info.get("valid"),
        )
    else:
        logger.warning(
            "YouTube cookies file missing at %s — age-restricted content may fail; "
            "PO Token (bgutil) still used for most requests",
            _COOKIES_PATH,
        )
    try:
        await run_health_probe(notify_on_failure=bool(info.get("valid")))
    except Exception:
        logger.debug("startup YouTube probe failed", exc_info=True)


async def start_cookie_health_scheduler() -> None:
    while True:
        await asyncio.sleep(_PROBE_INTERVAL_SEC)
        try:
            await run_health_probe(notify_on_failure=True)
        except Exception:
            logger.debug("periodic YouTube cookie probe failed", exc_info=True)
