import asyncio
import logging
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid

import yt_dlp

from bot.config import settings, _COOKIES_PATH
from bot.services import youtube_cookies as _yt_cookies
from bot.services.track_format import clean_title as _clean_title, parse_artist_title as _parse_artist_title
from bot.utils import fmt_duration as _utils_fmt_duration

logger = logging.getLogger(__name__)


class _YtdlpSilentLogger:
    """Suppress yt-dlp's own stderr output; we handle errors ourselves."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass
    def info(self, msg): pass


_ytdlp_logger = _YtdlpSilentLogger()

# ── Permanent failure cache (age-restricted, removed, etc.) ──────────
_PERMANENT_FAILURES: dict[str, float] = {}
_PERM_FAIL_TTL = 86400  # 24 hours

_PERM_FAIL_PATTERNS = [
    "Sign in to confirm your age",
    "This video is private",
    "Video unavailable",
    "has been removed",
    "account associated with this video has been terminated",
    "Requested format is not available",
]

_EXPECTED_RESTRICTION_PATTERNS = [
    "Sign in to confirm your age",
    "Video unavailable",
    "not available in your country",
    "This video is private",
    "This video is not available",
    "has been removed",
    "Requested format is not available",
    "does not look like a Netscape format cookies file",
]


_alert_loop: asyncio.AbstractEventLoop | None = None


def set_ytdl_alert_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register main event loop so worker threads can schedule cookie alerts."""
    global _alert_loop
    _alert_loop = loop


def _maybe_notify_youtube_auth_error(error: Exception, *, context: str) -> None:
    if not _yt_cookies.is_youtube_auth_error(error):
        return
    loop = _alert_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("YouTube auth error (no event loop): %s", error)
            return
    coro = _yt_cookies.handle_auth_failure(error, context=context)
    try:
        running = asyncio.get_running_loop()
        running.create_task(coro)
    except RuntimeError:
        asyncio.run_coroutine_threadsafe(coro, loop)


def _mark_permanent_failure(video_id: str) -> None:
    _PERMANENT_FAILURES[video_id] = time.monotonic() + _PERM_FAIL_TTL


def _is_permanently_failed(video_id: str) -> bool:
    exp = _PERMANENT_FAILURES.get(video_id)
    if exp is None:
        return False
    if time.monotonic() > exp:
        del _PERMANENT_FAILURES[video_id]
        return False
    return True


def _check_permanent_failure(video_id: str, error: Exception) -> None:
    msg = str(error)
    for pat in _PERM_FAIL_PATTERNS:
        if pat in msg:
            _mark_permanent_failure(video_id)
            logger.warning("Marked %s as permanent failure (24h): %s", video_id, pat)
            return


def _is_expected_restriction_error(error: Exception) -> bool:
    msg = str(error)
    return any(pat in msg for pat in _EXPECTED_RESTRICTION_PATTERNS)


# ── Staging helpers (shared by download_manager and providers) ──────────

def stage_path_for(dest: Path, suffix: str = ".part") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_name = f"{dest.name}.{uuid.uuid4().hex}{suffix}"
    return dest.parent / temp_name


def finalize_staged_file(staged: Path | None, dest: Path) -> Path:
    if staged is None:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(dest)
    return dest


def cleanup_staged_files(staged: Path | None) -> None:
    if staged is None:
        return
    try:
        staged.unlink(missing_ok=True)
    except Exception:
        logger.debug("cleanup_staged_files failed path=%s", staged, exc_info=True)

# Dedicated thread pool for yt-dlp I/O operations
_ytdl_pool = ThreadPoolExecutor(max_workers=settings.YTDL_WORKERS, thread_name_prefix="ytdl")


def _fmt_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "-:--"
    if seconds == 0:
        return "0:00"
    return _utils_fmt_duration(seconds)


def log_runtime_info() -> None:
    """Log yt-dlp version, JS runtimes and cookie status at startup."""
    logger.info("yt-dlp version: %s", yt_dlp.version.__version__)
    for rt in ("deno", "node"):
        path = shutil.which(rt)
        if path:
            try:
                ver = subprocess.check_output([path, "--version"], timeout=5, text=True).strip()
                logger.info("JS runtime '%s': %s (%s)", rt, ver, path)
            except Exception as e:
                logger.warning("JS runtime '%s': found at %s but failed to get version: %s", rt, path, e)
        else:
            logger.warning("JS runtime '%s': NOT FOUND in PATH", rt)
    # Also check explicit paths used in _base_opts
    for explicit in ("/usr/local/bin/deno",):
        import os
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            try:
                ver = subprocess.check_output([explicit, "--version"], timeout=5, text=True).strip()
                logger.info("Explicit runtime '%s': %s", explicit, ver)
            except Exception as e:
                logger.warning("Explicit runtime '%s': exists but failed: %s", explicit, e)
        else:
            logger.warning("Explicit runtime '%s': NOT FOUND or not executable", explicit)
    info = _yt_cookies.validate_cookie_file()
    logger.info(
        "Cookies file: %s (exists=%s, valid=%s, auth=%s)",
        _COOKIES_PATH,
        info.get("exists"),
        info.get("valid"),
        info.get("auth_cookies"),
    )
    logger.info("bgutil PO Token URL: %s", settings.BGUTIL_POT_BASE_URL)
    yt_proxy = (getattr(settings, "YOUTUBE_PROXY", None) or "").strip()
    if yt_proxy:
        logger.info("YouTube proxy: %s", yt_proxy.split("@")[-1][:60])
    else:
        from bot.services.proxy_pool import proxy_pool
        if proxy_pool.size:
            logger.info("YouTube proxy: PROXY_POOL (%d entries)", proxy_pool.size)
        else:
            logger.warning(
                "YouTube proxy: none — datacenter VPS may need YOUTUBE_PROXY or PROXY_POOL"
            )


def _youtube_proxy() -> str | None:
    """Proxy for YouTube requests (YOUTUBE_PROXY wins, else PROXY_POOL round-robin)."""
    direct = (getattr(settings, "YOUTUBE_PROXY", None) or "").strip()
    if direct:
        return direct
    from bot.services.proxy_pool import proxy_pool
    return proxy_pool.get_next()


def _youtube_player_clients(*, has_auth_cookies: bool) -> list[str]:
    """yt-dlp 2026.x player_client ordering.

    Order matters: the first client that returns playable formats wins.

    * ``android_vr`` and ``web_embedded`` are the most resilient against the
      "Sign in to confirm you're not a bot" / LOGIN_REQUIRED walls that affect
      datacenter IPs, even when routed through a residential / WARP proxy.
    * ``tv_simply`` (the new TV client) often has formats when others do not.
    * ``mweb`` + ``ios`` are kept as backups since they sometimes provide higher-
      bitrate audio streams.
    * ``tv_embedded`` is unsupported in current yt-dlp and was removed.
    """
    if has_auth_cookies:
        return ["android_vr", "web_embedded", "tv_simply", "mweb", "web", "ios"]
    return ["android_vr", "web_embedded", "tv_simply", "mweb", "web", "ios"]


def _youtube_extractor_args(*, has_auth_cookies: bool) -> dict:
    youtube_args = {
        "player_client": _youtube_player_clients(has_auth_cookies=has_auth_cookies),
    }
    # yt-dlp forwards its proxy to the bgutil PO-token plugin. With local
    # Cloudflare WARP this makes the provider fail fetching BotGuard JS, while
    # the selected clients work through WARP without PO tokens.
    proxy = _youtube_proxy() or ""
    if proxy.startswith(("socks5://172.17.0.1:", "socks5h://172.17.0.1:", "socks5://127.0.0.1:", "socks5h://127.0.0.1:")):
        return {"youtube": youtube_args}
    pot_url = (settings.BGUTIL_POT_BASE_URL or "").strip().rstrip("/")
    return {
        "youtube": youtube_args,
        "youtubepot-bgutilhttp": {"base_url": [pot_url or "http://bgutil-provider:4416"]},
    }


def _base_opts(*, has_auth_cookies: bool | None = None) -> dict:
    """Return base yt-dlp options: cookies + remote EJS components + proxy."""
    if has_auth_cookies is None:
        has_auth_cookies = _COOKIES_PATH.exists() and bool(
            _yt_cookies.validate_cookie_file().get("auth_cookies")
        )
    opts: dict = {"remote_components": {"ejs:github"}}
    opts["js_runtimes"] = {"deno": {"path": "/usr/local/bin/deno"}, "node": {}}
    opts["extractor_args"] = _youtube_extractor_args(has_auth_cookies=has_auth_cookies)
    proxy = _youtube_proxy()
    if proxy:
        opts["proxy"] = proxy
    return opts


def _prepare_cookiefile() -> tuple[str | None, Path | None]:
    """Create an isolated cookie file copy for a single yt-dlp call.

    Returns (cookie_path, temp_copy_path). If temp_copy_path is not None,
    caller must remove it in a finally block.
    """
    if not _COOKIES_PATH.exists():
        return None, None

    tid = threading.current_thread().ident or 0
    temp_cookie = _COOKIES_PATH.parent / f".cookies_t{tid}_{uuid.uuid4().hex}.txt"
    try:
        shutil.copy2(_COOKIES_PATH, temp_cookie)
        return str(temp_cookie), temp_cookie
    except OSError:
        return str(_COOKIES_PATH), None


def _cleanup_temp_cookie(temp_cookie: Path | None) -> None:
    if temp_cookie is None:
        return
    try:
        temp_cookie.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove temporary cookie copy %s", temp_cookie, exc_info=True)

# Spotify URL regex
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/track/[a-zA-Z0-9]+",
)

# YouTube URL regex — matches youtube.com, youtu.be, m.youtube.com, music.youtube.com
_YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com/watch\?[^\s]*v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
)


def is_youtube_url(text: str) -> bool:
    """Check if text contains a YouTube URL."""
    return bool(_YOUTUBE_URL_RE.search(text))


def extract_youtube_video_id(text: str) -> str | None:
    """Extract YouTube video ID from a URL in text."""
    m = _YOUTUBE_URL_RE.search(text)
    return m.group(1) if m else None


async def resolve_youtube_url(video_id: str) -> dict | None:
    """Fetch metadata for a YouTube video ID and return a track_info dict."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_ytdl_pool, _resolve_youtube_sync, video_id)
    except Exception as e:
        logger.error("YouTube resolve failed for %s: %s", video_id, e)
        return None


async def resolve_youtube_audio_stream_url(video_id: str) -> str | None:
    """Resolve direct audio stream URL for immediate playback."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_ytdl_pool, _resolve_youtube_audio_stream_url_sync, video_id)
    except Exception as e:
        logger.error("YouTube audio stream URL resolve failed for %s: %s", video_id, e)
        return None


def _resolve_youtube_sync(video_id: str) -> dict | None:
    if _is_permanently_failed(video_id):
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    cookiefile, temp_cookie = _prepare_cookiefile()
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _ytdlp_logger,
        "skip_download": True,
        "socket_timeout": 15,
        **_base_opts(),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            duration = info.get("duration") or 0
            if duration <= 0 or duration > settings.MAX_DURATION:
                return None
            raw_title = info.get("title") or "Unknown"
            uploader = info.get("uploader") or info.get("channel") or "Unknown"
            artist, title = _parse_artist_title(raw_title, uploader)
            return {
                "video_id": video_id,
                "title": title,
                "uploader": artist,
                "duration": duration,
                "duration_fmt": _fmt_duration(int(duration)),
                "source": "youtube",
                "upload_year": _extract_year(info),
            }
    except Exception as e:
        _check_permanent_failure(video_id, e)
        _maybe_notify_youtube_auth_error(e, context=f"resolve {video_id}")
        if _is_expected_restriction_error(e):
            logger.warning("YouTube resolve unavailable for %s: %s", video_id, e)
        else:
            logger.error("YouTube resolve sync error for %s: %s", video_id, e)
        return None
    finally:
        _cleanup_temp_cookie(temp_cookie)


def _resolve_youtube_audio_stream_url_sync(video_id: str) -> str | None:
    if _is_permanently_failed(video_id):
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    cookiefile, temp_cookie = _prepare_cookiefile()
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _ytdlp_logger,
        "skip_download": True,
        "socket_timeout": 10,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "extract_flat": False,
        "no_check_certificates": True,
        **_base_opts(),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            stream_url = info.get("url")
            if isinstance(stream_url, str) and stream_url:
                return stream_url

            formats = info.get("formats") or []
            best_audio_url = None
            best_abr = -1.0
            for fmt in formats:
                acodec = (fmt.get("acodec") or "none")
                vcodec = (fmt.get("vcodec") or "none")
                fmt_url = fmt.get("url")
                if acodec == "none" or not fmt_url:
                    continue
                if vcodec != "none":
                    continue
                abr = float(fmt.get("abr") or 0)
                if abr > best_abr:
                    best_abr = abr
                    best_audio_url = fmt_url
            return best_audio_url
    except Exception as e:
        _check_permanent_failure(video_id, e)
        _maybe_notify_youtube_auth_error(e, context=f"audio url {video_id}")
        if _is_expected_restriction_error(e):
            logger.warning("YouTube audio URL resolve unavailable for %s: %s", video_id, e)
        else:
            logger.error("YouTube audio URL resolve sync error for %s: %s", video_id, e)
        return None
    finally:
        _cleanup_temp_cookie(temp_cookie)


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
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": _ytdlp_logger}) as ydl:
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

    cookiefile, temp_cookie = _prepare_cookiefile()
    ydl_opts = {
        "format": "bestaudio/best",
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "logger": _ytdlp_logger,
        "socket_timeout": 15,
        "ignore_no_formats_error": True,
        **_base_opts(),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"{search_prefix}:{query}"
            info = ydl.extract_info(search_query, download=False)
            # Convert to list INSIDE context to avoid I/O errors after close
            entries = list(info.get("entries", [])) if info else []

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
        _maybe_notify_youtube_auth_error(e, context="search")
        logger.error("Search error: %s", e)
        return []
    finally:
        _cleanup_temp_cookie(temp_cookie)


def _list_formats_debug(video_id: str) -> None:
    """Log available formats for a video (debug helper)."""
    if _is_permanently_failed(video_id):
        return
    cookiefile, temp_cookie = _prepare_cookiefile()
    try:
        opts = {
            "quiet": False, "verbose": True, "no_warnings": False,
            "skip_download": True, **_base_opts(),
        }
        if cookiefile:
            opts["cookiefile"] = cookiefile
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False, process=False,
            )
            if not info:
                logger.error("DEBUG formats %s: no info returned", video_id)
                return
            formats = info.get("formats") or []
            logger.info("DEBUG formats %s: %d raw formats found", video_id, len(formats))
            for f in formats[:10]:
                logger.info(
                    "  fmt %s | ext=%s | acodec=%s | vcodec=%s | abr=%s | res=%s | url=%s",
                    f.get("format_id"), f.get("ext"), f.get("acodec"),
                    f.get("vcodec"), f.get("abr"), f.get("resolution"),
                    "YES" if f.get("url") else "NO",
                )
    except Exception as e:
        logger.error("DEBUG list-formats failed for %s: %s", video_id, e)
    finally:
        _cleanup_temp_cookie(temp_cookie)


def _download_sync(video_id: str, output_dir: Path, bitrate: int, progress_cb=None, dl_id: str | None = None) -> Path:
    if _is_permanently_failed(video_id):
        raise yt_dlp.utils.DownloadError(f"Permanently failed (cached): {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    file_stem = f"{video_id}_{dl_id}" if dl_id else video_id
    output_template = str(output_dir / f"{file_stem}.%(ext)s")
    cookiefile, temp_cookie = _prepare_cookiefile()

    def _hook(d: dict) -> None:
        if progress_cb and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                progress_cb(downloaded, total)

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
        "logger": _ytdlp_logger,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": settings.YTDL_CONCURRENT_FRAGMENTS,
        "progress_hooks": [_hook],
        **_base_opts(),
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {settings.MAX_DURATION}"
        ),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        _check_permanent_failure(video_id, e)
        _maybe_notify_youtube_auth_error(e, context=f"download {video_id}")
        if _is_expected_restriction_error(e):
            logger.warning("Download unavailable for %s: %s", video_id, e)
        else:
            logger.error("Download failed for %s: %s", video_id, e)
            _list_formats_debug(video_id)
        raise
    finally:
        _cleanup_temp_cookie(temp_cookie)

    _yt_cookies.note_download_success()
    mp3_path = output_dir / f"{file_stem}.mp3"
    if mp3_path.exists():
        return mp3_path
    # Fallback: check without dl_id suffix (older naming)
    if dl_id:
        alt = output_dir / f"{video_id}.mp3"
        if alt.exists():
            return alt
    raise FileNotFoundError(f"MP3 not found after download: {video_id}")


async def search_tracks(query: str, max_results: int = 5, source: str = "youtube") -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_ytdl_pool, _search_sync, query, max_results, source)


async def resolve_spotify(url: str) -> str | None:
    """Resolve Spotify URL to 'artist title' search query."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_ytdl_pool, _extract_spotify_meta, url)


async def download_track(video_id: str, bitrate: int = 192, progress_cb=None, dl_id: str | None = None) -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _ytdl_pool, _download_sync, video_id, settings.DOWNLOAD_DIR, bitrate, progress_cb, dl_id
    )


# ── Video download ──────────────────────────────────────────────────────

def _download_video_sync(video_id: str, output_dir: Path, quality: str) -> Path:
    """Download YouTube video as mp4. quality: 360 / 480 / 720."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    height = int(quality)
    output_template = str(output_dir / f"{video_id}_v{quality}.%(ext)s")
    cookiefile, temp_cookie = _prepare_cookiefile()
    ydl_opts = {
        "format": f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegMetadata"}],
        "quiet": True,
        "no_warnings": True,
        "logger": _ytdlp_logger,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": settings.YTDL_CONCURRENT_FRAGMENTS,
        **_base_opts(),
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {settings.MAX_DURATION}"
        ),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        _check_permanent_failure(video_id, e)
        _maybe_notify_youtube_auth_error(e, context=f"video {video_id}")
        if _is_expected_restriction_error(e):
            logger.warning("Video download unavailable for %s: %s", video_id, e)
        else:
            logger.error("Video download failed for %s: %s", video_id, e)
        raise
    finally:
        _cleanup_temp_cookie(temp_cookie)

    mp4_path = output_dir / f"{video_id}_v{quality}.mp4"
    if mp4_path.exists():
        return mp4_path
    # yt-dlp might have used a different extension; find it
    for f in output_dir.glob(f"{video_id}_v{quality}.*"):
        if f.suffix in (".mp4", ".mkv", ".webm"):
            return f
    raise FileNotFoundError(f"Video not found after download: {video_id}")


async def download_video(video_id: str, quality: str = "480") -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _ytdl_pool, _download_video_sync, video_id, settings.DOWNLOAD_DIR, quality
    )


def cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        # Удаляем thumbnail если остался
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            thumb = path.with_suffix(ext)
            thumb.unlink(missing_ok=True)
    except Exception:
        logger.debug("cleanup_file failed path=%s", path, exc_info=True)
