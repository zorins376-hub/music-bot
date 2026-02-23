import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path

import yt_dlp

from bot.config import settings, _COOKIES_PATH

logger = logging.getLogger(__name__)


def log_runtime_info() -> None:
    """Log yt-dlp version, JS runtimes and cookie status at startup."""
    logger.info("yt-dlp version: %s", yt_dlp.version.__version__)
    for rt in ("deno", "node"):
        path = shutil.which(rt)
        if path:
            try:
                ver = subprocess.check_output([rt, "--version"], timeout=5, text=True).strip()
                logger.info("JS runtime '%s': %s (%s)", rt, ver, path)
            except Exception:
                logger.info("JS runtime '%s': found at %s (version unknown)", rt, path)
        else:
            logger.info("JS runtime '%s': NOT FOUND", rt)
    logger.info("Cookies file: %s (exists=%s)", _COOKIES_PATH, _COOKIES_PATH.exists())


def _cookies_opt() -> dict:
    """Return cookiefile option if cookies.txt exists."""
    if _COOKIES_PATH.exists():
        return {"cookiefile": str(_COOKIES_PATH)}
    return {}

# Spotify URL regex
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/track/[a-zA-Z0-9]+",
)

# Junk to strip from YouTube titles
_TITLE_JUNK_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:official\s*(?:music\s*)?video|official\s*audio|official\s*lyric[s]?\s*video"
    r"|lyric[s]?\s*video|lyric[s]?|audio|music\s*video|видеоклип|клип|текст"
    r"|hd|hq|4k|1080p|720p|mv|m/v"
    r"|премьера\s*(?:клипа)?\s*,?\s*\d{4}|премьера\s*\d{4}"
    r"|ft\.?[^)\]]*|feat\.?[^)\]]*)\s*[\)\]]",
    re.IGNORECASE,
)
_EXTRA_JUNK_RE = re.compile(
    r"\s*\|.*$"
    r"|\s*//.*$"
    r"|\s*#\w+"
    r"|\s*\(\s*\)"
    r"|\s*\[\s*\]",
    re.IGNORECASE,
)


def _clean_title(raw_title: str) -> str:
    """Strip common YouTube junk from title."""
    cleaned = _TITLE_JUNK_RE.sub("", raw_title)
    cleaned = _EXTRA_JUNK_RE.sub("", cleaned)
    # Strip trailing standalone words: "lyrics", "audio", "video", "текст"
    cleaned = re.sub(r"\s+(?:lyrics|audio|video|текст)\s*$", "", cleaned, flags=re.IGNORECASE)
    # Normalize whitespace
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _parse_artist_title(raw_title: str, uploader: str) -> tuple[str, str]:
    """Extract clean (artist, title) from YouTube video title.

    Tries to split on ' - ', ' — ', ' – '. If found, returns parsed pair.
    Otherwise uses uploader as artist and cleaned title as song name.
    Strips ' - Topic' from YouTube auto-generated channel names.
    """
    cleaned = _clean_title(raw_title)

    # Try splitting on common separators
    for sep in (" — ", " – ", " - "):
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            if artist and title:
                return artist, title

    # Fallback: use uploader as artist, cleaned title as song
    artist = uploader or "Unknown"
    # Strip " - Topic" from YouTube auto-generated channels
    if artist.endswith(" - Topic"):
        artist = artist[:-8].strip()
    elif artist.endswith(" - Тема"):
        artist = artist[:-7].strip()
    # Strip "VEVO" suffix
    if artist.upper().endswith("VEVO"):
        artist = artist[:-4].strip()

    return artist, cleaned or raw_title


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _extract_year(entry: dict) -> str | None:
    """Extract release year from yt-dlp entry."""
    upload_date = entry.get("upload_date") or entry.get("release_date") or ""
    if upload_date and len(upload_date) >= 4:
        return upload_date[:4]
    release_year = entry.get("release_year")
    if release_year:
        return str(release_year)
    return None


def _extract_spotify_meta(url: str) -> str | None:
    """Extract artist — title from Spotify URL via yt-dlp (no API key needed)."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                artist = info.get("artist") or info.get("uploader") or ""
                title = info.get("track") or info.get("title") or ""
                return f"{artist} {title}".strip() or None
    except Exception as e:
        logger.warning("Spotify extract failed: %s", e)
    return None


def is_spotify_url(text: str) -> bool:
    return bool(_SPOTIFY_RE.search(text))


def _search_sync(query: str, max_results: int, source: str = "youtube") -> list[dict]:
    # Request extra results to compensate for filtered out 0-duration tracks
    fetch_count = max_results + 5
    if source == "soundcloud":
        search_prefix = f"scsearch{fetch_count}"
    else:
        search_prefix = f"ytsearch{fetch_count}"

    ydl_opts = {
        "format": "bestaudio/best",
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "default_search": search_prefix,
        **_cookies_opt(),
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
            # Skip tracks with no duration (unplayable) or too long
            if duration <= 0 or duration > settings.MAX_DURATION:
                continue
            raw_title = entry.get("title", "Unknown")
            uploader = entry.get("uploader") or entry.get("channel") or "Unknown"
            artist, title = _parse_artist_title(raw_title, uploader)
            tracks.append(
                {
                    "video_id": entry.get("id", ""),
                    "title": title,
                    "uploader": artist,
                    "duration": duration,
                    "duration_fmt": _fmt_duration(int(duration)),
                    "source": source,
                    "upload_year": _extract_year(entry),
                }
            )
        return tracks[:max_results]
    except Exception as e:
        logger.error("Search error: %s", e)
        return []


def _list_formats_debug(video_id: str) -> None:
    """Log available formats for a video (debug helper)."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, **_cookies_opt()}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if not info:
                logger.error("DEBUG formats %s: no info returned", video_id)
                return
            formats = info.get("formats") or []
            logger.info("DEBUG formats %s: %d formats found", video_id, len(formats))
            for f in formats:
                logger.info(
                    "  fmt %s | ext=%s | acodec=%s | vcodec=%s | abr=%s | resolution=%s",
                    f.get("format_id"), f.get("ext"), f.get("acodec"),
                    f.get("vcodec"), f.get("abr"), f.get("resolution"),
                )
    except Exception as e:
        logger.error("DEBUG list-formats failed for %s: %s", video_id, e)


def _download_sync(video_id: str, output_dir: Path, bitrate: int) -> Path:
    url = f"https://www.youtube.com/watch?v={video_id}"
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
        **_cookies_opt(),
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {settings.MAX_DURATION}"
        ),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.error("Download failed for %s: %s", video_id, e)
        _list_formats_debug(video_id)
        raise

    mp3_path = output_dir / f"{video_id}.mp3"
    if mp3_path.exists():
        return mp3_path
    raise FileNotFoundError(f"MP3 not found after download: {video_id}")


async def search_tracks(query: str, max_results: int = 5, source: str = "youtube") -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_sync, query, max_results, source)


async def resolve_spotify(url: str) -> str | None:
    """Resolve Spotify URL to 'artist title' search query."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract_spotify_meta, url)


async def download_track(video_id: str, bitrate: int = 192) -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _download_sync, video_id, settings.DOWNLOAD_DIR, bitrate
    )


def _fetch_year_sync(video_id: str) -> str | None:
    """Fetch upload year for a single video via yt-dlp (no download)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        **_cookies_opt(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if info:
                return _extract_year(info)
    except Exception:
        pass
    return None


async def fetch_track_year(video_id: str) -> str | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_year_sync, video_id)


def cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        # Удаляем thumbnail если остался
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            thumb = path.with_suffix(ext)
            thumb.unlink(missing_ok=True)
    except Exception:
        pass
