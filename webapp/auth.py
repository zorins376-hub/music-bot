"""
Telegram WebApp initData HMAC-SHA256 verification.

See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qs, unquote

from bot.config import settings

_auth_logger = logging.getLogger("webapp.auth")


def verify_init_data(init_data: str, max_age: int = 86400) -> dict | None:
    """
    Validate Telegram WebApp initData string.

    Returns parsed user dict on success, None on failure.
    """
    # Debug: log the initData length and keys
    parsed = parse_qs(init_data, keep_blank_values=True)
    _auth_logger.warning("[AUTH] initData len=%d keys=%s", len(init_data), list(parsed.keys()))

    if "hash" not in parsed:
        _auth_logger.warning("[AUTH] FAIL: no hash in initData")
        return None

    received_hash = parsed.pop("hash")[0]

    # Check auth_date freshness
    auth_date_str = parsed.get("auth_date", [""])[0]
    if not auth_date_str:
        _auth_logger.warning("[AUTH] FAIL: no auth_date")
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        _auth_logger.warning("[AUTH] FAIL: invalid auth_date format")
        return None
    age = time.time() - auth_date
    if age > max_age:
        _auth_logger.warning("[AUTH] FAIL: expired age=%.0f max_age=%d", age, max_age)
        return None

    # Build data-check-string: sorted key=value pairs joined by \n
    data_check_parts = sorted(
        f"{k}={v[0]}" for k, v in parsed.items()
    )
    data_check_string = "\n".join(data_check_parts)

    # HMAC-SHA256 verification
    secret_key = hmac.new(
        b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        _auth_logger.warning("[AUTH] FAIL: HMAC mismatch")
        return None

    # Extract user info
    user_raw = parsed.get("user", [""])[0]
    if not user_raw:
        _auth_logger.warning("[AUTH] FAIL: no user field")
        return None
    try:
        user = json.loads(unquote(user_raw))
    except (json.JSONDecodeError, ValueError):
        _auth_logger.warning("[AUTH] FAIL: invalid user JSON")
        return None

    _auth_logger.warning("[AUTH] OK user_id=%s", user.get("id"))
    return user
