"""
tts_engine.py — Text-to-Speech via edge-tts with gTTS fallback.

Generates MP3 voice clips for DJ comments between tracks.
Caches generated audio in Redis (tts:{hash} → file bytes, TTL 30 days).
"""
import hashlib
import io
import logging

logger = logging.getLogger(__name__)

_VOICE_RU = "ru-RU-DmitryNeural"
_VOICE_EN = "en-US-GuyNeural"

_LANG_VOICES = {
    "ru": _VOICE_RU,
    "en": _VOICE_EN,
    "kg": _VOICE_RU,  # fallback to Russian
}

_GTTS_LANG = {"ru": "ru", "en": "en", "kg": "ru"}

_CACHE_TTL = 30 * 24 * 3600  # 30 days


async def _get_cached(cache_key: str) -> bytes | None:
    """Try to get TTS audio from Redis cache."""
    try:
        from bot.services.cache import cache
        data = await cache.redis.get(cache_key)
        return data
    except Exception:
        return None


async def _set_cached(cache_key: str, data: bytes) -> None:
    """Store TTS audio in Redis cache."""
    try:
        from bot.services.cache import cache
        await cache.redis.set(cache_key, data, ex=_CACHE_TTL)
    except Exception:
        logger.debug("tts cache set failed", exc_info=True)


async def _synthesize_edge(text: str, voice: str) -> bytes | None:
    """Generate MP3 using edge-tts."""
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed")
        return None

    try:
        communicate = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        return data if data else None
    except Exception as e:
        logger.error("edge-tts synthesis failed: %s", e)
        return None


def _synthesize_gtts_sync(text: str, lang: str) -> bytes | None:
    """Generate MP3 using gTTS (sync, runs in thread pool)."""
    try:
        from gtts import gTTS
    except ImportError:
        logger.warning("gTTS not installed")
        return None

    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        data = buf.getvalue()
        return data if data else None
    except Exception as e:
        logger.error("gTTS synthesis failed: %s", e)
        return None


async def synthesize(text: str, lang: str = "ru") -> bytes | None:
    """Generate MP3 bytes from text. Checks cache, tries edge-tts, falls back to gTTS."""
    # Check cache first
    text_hash = hashlib.md5(f"{lang}:{text}".encode()).hexdigest()
    cache_key = f"tts:{text_hash}"
    cached = await _get_cached(cache_key)
    if cached:
        return cached

    voice = _LANG_VOICES.get(lang, _VOICE_RU)

    # Try edge-tts first
    data = await _synthesize_edge(text, voice)

    # Fallback to gTTS
    if not data:
        import asyncio
        gtts_lang = _GTTS_LANG.get(lang, "en")
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _synthesize_gtts_sync, text, gtts_lang)

    # Cache result
    if data:
        await _set_cached(cache_key, data)

    return data
