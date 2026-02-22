import asyncio
import logging
from pathlib import Path

import yt_dlp

from bot.config import settings

logger = logging.getLogger(__name__)


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _search_sync(query: str, max_results: int) -> list[dict]:
    ydl_opts = {
        "format": "bestaudio/best",
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": f"ytsearch{max_results}",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries", []) if info else []

        tracks = []
        for entry in entries:
            if not entry:
                continue
            duration = entry.get("duration") or 0
            if duration > settings.MAX_DURATION:
                continue
            tracks.append(
                {
                    "video_id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "uploader": entry.get("uploader") or entry.get("channel") or "Unknown",
                    "duration": duration,
                    "duration_fmt": _fmt_duration(int(duration)),
                    "source": "youtube",
                }
            )
        return tracks
    except Exception as e:
        logger.error("Search error: %s", e)
        return []


def _download_sync(video_id: str, output_dir: Path, bitrate: int) -> Path:
    output_template = str(output_dir / f"{video_id}.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(bitrate),
            },
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {settings.MAX_DURATION}"
        ),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    mp3_path = output_dir / f"{video_id}.mp3"
    if mp3_path.exists():
        return mp3_path
    raise FileNotFoundError(f"MP3 not found after download: {video_id}")


async def search_tracks(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_sync, query, max_results)


async def download_track(video_id: str, bitrate: int = 192) -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _download_sync, video_id, settings.DOWNLOAD_DIR, bitrate
    )


def cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        # Удаляем thumbnail если остался
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            thumb = path.with_suffix(ext)
            thumb.unlink(missing_ok=True)
    except Exception:
        pass
