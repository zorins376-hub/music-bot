"""
Telegram WebApp initData HMAC-SHA256 verification.

See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, unquote

from bot.config import settings


def verify_init_data(init_data: str, max_age: int = 86400) -> dict | None:
    """
    Validate Telegram WebApp initData string.

    Returns parsed user dict on success, None on failure.
    """
    parsed = parse_qs(init_data, keep_blank_values=True)

    if "hash" not in parsed:
        return None

    received_hash = parsed.pop("hash")[0]

    # Check auth_date freshness
    auth_date_str = parsed.get("auth_date", [""])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
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
        return None

    # Extract user info
    user_raw = parsed.get("user", [""])[0]
    if not user_raw:
        return None
    try:
        user = json.loads(unquote(user_raw))
    except (json.JSONDecodeError, ValueError):
        return None

    return user
