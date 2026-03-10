"""
feature_flags.py — Simple feature flag system.

Flags stored in Redis, toggled via admin commands.
Default values used when Redis unavailable.
"""
import logging

from bot.services.cache import cache

logger = logging.getLogger(__name__)

_PREFIX = "ff:"

# Default values for feature flags
_DEFAULTS: dict[str, bool] = {
    "premium_history_limit": True,
    "premium_priority_queue": True,
    "tts_enabled": True,
    "sponsored_tracks": False,
    "apple_music_import": True,
    "story_cards": True,
}


async def is_enabled(flag: str) -> bool:
    """Check if a feature flag is enabled."""
    try:
        val = await cache.redis.get(f"{_PREFIX}{flag}")
        if val is not None:
            return val == "1"
    except Exception:
        pass
    return _DEFAULTS.get(flag, False)


async def set_flag(flag: str, enabled: bool) -> None:
    """Set a feature flag value."""
    try:
        await cache.redis.set(f"{_PREFIX}{flag}", "1" if enabled else "0")
    except Exception as e:
        logger.error("Failed to set feature flag %s: %s", flag, e)


async def get_all_flags() -> dict[str, bool]:
    """Get all feature flags with their current values."""
    result = {}
    for flag, default in _DEFAULTS.items():
        try:
            val = await cache.redis.get(f"{_PREFIX}{flag}")
            result[flag] = val == "1" if val is not None else default
        except Exception:
            result[flag] = default
    return result
