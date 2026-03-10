"""
tts_engine.py — Text-to-Speech via edge-tts.

Generates MP3 voice clips for DJ comments between tracks.
"""
import io
import logging
import tempfile

logger = logging.getLogger(__name__)

_VOICE_RU = "ru-RU-DmitryNeural"
_VOICE_EN = "en-US-GuyNeural"

_LANG_VOICES = {
    "ru": _VOICE_RU,
    "en": _VOICE_EN,
    "kg": _VOICE_RU,  # fallback to Russian
}


async def synthesize(text: str, lang: str = "ru") -> bytes | None:
    """Generate MP3 bytes from text using edge-tts. Returns None on error."""
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed, TTS unavailable")
        return None

    voice = _LANG_VOICES.get(lang, _VOICE_RU)

    try:
        communicate = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        return data if data else None
    except Exception as e:
        logger.error("TTS synthesis failed: %s", e)
        return None
