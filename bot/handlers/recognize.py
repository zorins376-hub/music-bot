"""FR-002: Shazam-based recognition for voice messages, audio files, videos."""
import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message

from bot.db import get_or_create_user
from bot.i18n import t

logger = logging.getLogger(__name__)

router = Router()

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_MIN_DURATION = 5  # seconds


async def _tg_download(bot, file_id: str, suffix: str) -> Path:
    tg_file = await bot.get_file(file_id)
    path = Path(tempfile.mktemp(suffix=suffix))
    await bot.download_file(tg_file.file_path, destination=str(path))
    return path


async def _convert_to_wav(input_path: Path) -> Path | None:
    """Convert audio/video to 16kHz mono WAV (first 15 sec). Returns None on failure."""
    wav_path = Path(str(input_path) + ".wav")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(input_path),
            "-ac", "1", "-ar", "16000", "-t", "15",
            str(wav_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if wav_path.exists() and wav_path.stat().st_size > 0:
            return wav_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found — skipping WAV conversion")
    except Exception as e:
        logger.warning("ffmpeg conversion failed: %s", e)
    return None


def _cleanup(*paths: Path | None) -> None:
    for p in paths:
        if p and p.exists():
            try:
                p.unlink()
            except Exception:
                pass


async def _recognize_and_search(message: Message, file_id: str, suffix: str) -> None:
    """Download, convert, recognize with Shazam, then route to search."""
    from bot.handlers.search import _do_search  # local import avoids circular dep

    user = await get_or_create_user(message.from_user)
    lang = user.language

    status = await message.answer(t(lang, "shazam_recognizing"))

    input_path: Path | None = None
    wav_path: Path | None = None
    try:
        input_path = await _tg_download(message.bot, file_id, suffix)
        wav_path = await _convert_to_wav(input_path)
        recognize_path = wav_path if wav_path else input_path

        try:
            from shazamio import Shazam
        except ImportError:
            logger.error("shazamio not installed — cannot recognize")
            await status.edit_text(t(lang, "shazam_error"))
            return

        shazam = Shazam()
        result = await shazam.recognize(str(recognize_path))

        track = (result or {}).get("track") or {}
        title: str = track.get("title", "").strip()
        artist: str = track.get("subtitle", "").strip()  # Shazam "subtitle" = artist name

        if not title or not artist:
            await status.edit_text(t(lang, "shazam_not_recognized"))
            return

        await status.edit_text(t(lang, "shazam_recognized", artist=artist, title=title))
        await _do_search(message, f"{artist} - {title}")

    except Exception as e:
        logger.error("Shazam recognition failed: %s", e)
        try:
            await status.edit_text(t(lang, "shazam_error"))
        except Exception:
            pass
    finally:
        _cleanup(input_path, wav_path)


# ── Handlers ──────────────────────────────────────────────────────────────

@router.message(F.voice)
async def handle_voice(message: Message) -> None:
    v = message.voice
    if (v.duration or 0) < _MIN_DURATION:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_short"))
        return
    if v.file_size and v.file_size > _MAX_FILE_SIZE:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_large"))
        return
    await _recognize_and_search(message, v.file_id, ".ogg")


@router.message(F.audio)
async def handle_audio(message: Message) -> None:
    a = message.audio
    duration = a.duration or 0
    if 0 < duration < _MIN_DURATION:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_short"))
        return
    if a.file_size and a.file_size > _MAX_FILE_SIZE:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_large"))
        return
    await _recognize_and_search(message, a.file_id, ".mp3")


@router.message(F.video_note)
async def handle_video_note(message: Message) -> None:
    vn = message.video_note
    if (vn.duration or 0) < _MIN_DURATION:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_short"))
        return
    if vn.file_size and vn.file_size > _MAX_FILE_SIZE:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_large"))
        return
    await _recognize_and_search(message, vn.file_id, ".mp4")


@router.message(F.video)
async def handle_video(message: Message) -> None:
    v = message.video
    if (v.duration or 0) < _MIN_DURATION:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_short"))
        return
    if v.file_size and v.file_size > _MAX_FILE_SIZE:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "shazam_too_large"))
        return
    await _recognize_and_search(message, v.file_id, ".mp4")
