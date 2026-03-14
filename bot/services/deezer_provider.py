"""Deezer provider — search (public API) + download (ARL token + Blowfish).

Requires DEEZER_ARL environment variable (browser cookie from deezer.com).
If not configured — search still works (public), download returns None.
"""
import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import aiohttp

from bot.config import settings
from bot.services.downloader import cleanup_staged_files, finalize_staged_file, stage_path_for
from bot.services.http_session import get_session
from bot.utils import fmt_duration as _fmt_dur

logger = logging.getLogger(__name__)

_dz_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="deezer")

# Deezer public API (no auth)
_SEARCH_URL = "https://api.deezer.com/search"
_TRACK_URL = "https://api.deezer.com/track/{}"

# Deezer private API (ARL required)
_GW_URL = "https://www.deezer.com/ajax/gw-light.php"
_MEDIA_URL = "https://media.deezer.com/v1/get_url"

# Session state
_api_token: str = ""
_license_token: str = ""
_session_ready = False

# Blowfish import (optional — needed for download only)
try:
    from Crypto.Cipher import Blowfish
except ImportError:
    Blowfish = None  # type: ignore[assignment, misc]


def _get_blowfish_key(track_id: str) -> bytes:
    """Derive Blowfish decryption key from Deezer track ID."""
    secret = b"g4el58wc0zvf9na1"
    h = hashlib.md5(str(track_id).encode()).hexdigest()
    return bytes(ord(h[i]) ^ ord(h[i + 16]) ^ secret[i] for i in range(16))


def _decrypt_chunk(chunk: bytes, key: bytes) -> bytes:
    """Decrypt a single 2048-byte Blowfish CBC chunk."""
    if Blowfish is None:
        return chunk
    iv = bytes(range(8))  # b'\x00\x01\x02\x03\x04\x05\x06\x07'
    cipher = Blowfish.new(key, Blowfish.MODE_CBC, iv)
    return cipher.decrypt(chunk)


# ── Public search (no auth) ──────────────────────────────────────────────

def _track_to_dict(tr: dict) -> Optional[dict]:
    """Convert Deezer API track object to internal dict."""
    try:
        title = (tr.get("title") or "").strip()
        artist_obj = tr.get("artist") or {}
        artist = (artist_obj.get("name") or "").strip()
        if not title or not artist:
            return None
        dur_s = int(tr.get("duration") or 0)
        if dur_s <= 0 or dur_s > settings.MAX_DURATION:
            return None
        track_id = tr.get("id")
        if not track_id:
            return None
        # Cover: prefer album cover, fallback to artist picture
        album = tr.get("album") or {}
        cover = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""
        return {
            "video_id": f"dz_{track_id}",
            "dz_track_id": int(track_id),
            "title": title,
            "uploader": artist,
            "duration": dur_s,
            "duration_fmt": _fmt_dur(dur_s),
            "source": "deezer",
            "cover_url": cover,
            "yt_query": f"{artist} - {title}",
        }
    except Exception:
        return None


async def search_deezer(query: str, limit: int = 5) -> list[dict]:
    """Search Deezer public API (no auth needed)."""
    try:
        session = get_session()
        async with session.get(
            _SEARCH_URL,
            params={"q": query, "limit": min(limit + 5, 50)},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            results: list[dict] = []
            for item in data.get("data", []):
                d = _track_to_dict(item)
                if d:
                    results.append(d)
                if len(results) >= limit:
                    break
            return results
    except Exception as e:
        logger.error("Deezer search error: %s", e)
        return []


async def resolve_deezer_track(track_id: int) -> Optional[dict]:
    """Get track metadata by Deezer track ID."""
    try:
        session = get_session()
        async with session.get(
            _TRACK_URL.format(track_id),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return _track_to_dict(data)
    except Exception as e:
        logger.error("Deezer resolve error: %s", e)
        return None


# ── Private API session (ARL required for download) ──────────────────────

async def _ensure_gw_session() -> bool:
    """Initialize Deezer private API session using ARL cookie."""
    global _api_token, _license_token, _session_ready
    if _session_ready:
        return True

    arl = getattr(settings, "DEEZER_ARL", "") or os.getenv("DEEZER_ARL", "")
    if not arl:
        return False

    try:
        session = get_session()
        cookies = {"arl": arl}
        async with session.post(
            _GW_URL,
            params={"method": "deezer.getUserData", "api_version": "1.0",
                    "api_token": "", "input": "3"},
            cookies=cookies,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
            results = data.get("results", {})
            _api_token = results.get("checkForm", "")
            user = results.get("USER", {})
            opts = user.get("OPTIONS", {})
            _license_token = opts.get("license_token", "")
            if _api_token and user.get("USER_ID", 0) != 0:
                _session_ready = True
                logger.info("Deezer private API session ready (user %s)", user.get("USER_ID"))
                return True
            logger.warning("Deezer ARL invalid or expired")
            return False
    except Exception as e:
        logger.error("Deezer GW session init failed: %s", e)
        return False


async def _get_track_data(track_id: int) -> Optional[dict]:
    """Get full track data from Deezer private API (includes TRACK_TOKEN)."""
    if not await _ensure_gw_session():
        return None
    arl = getattr(settings, "DEEZER_ARL", "") or os.getenv("DEEZER_ARL", "")
    try:
        session = get_session()
        async with session.post(
            _GW_URL,
            params={"method": "song.getData", "api_version": "1.0",
                    "api_token": _api_token, "input": "3"},
            json={"sng_id": track_id},
            cookies={"arl": arl},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
            return data.get("results")
    except Exception as e:
        logger.error("Deezer get_track_data error: %s", e)
        return None


async def _get_media_url(track_token: str, quality: str = "MP3_128") -> Optional[str]:
    """Get encrypted media URL from Deezer CDN."""
    if not _license_token:
        return None
    try:
        session = get_session()
        async with session.post(
            _MEDIA_URL,
            json={
                "license_token": _license_token,
                "media": [{"type": "FULL", "formats": [
                    {"cipher": "BF_CBC_STRIPE", "format": quality},
                ]}],
                "track_tokens": [track_token],
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
            media_data = data.get("data", [])
            if not media_data:
                return None
            media = media_data[0].get("media")
            if not media:
                return None
            sources = media[0].get("sources", [])
            if not sources:
                return None
            return sources[0].get("url")
    except Exception as e:
        logger.error("Deezer get_media_url error: %s", e)
        return None


# ── Download + decrypt ───────────────────────────────────────────────────

async def download_deezer(track_id: int, dest: Path, quality: str = "MP3_128") -> Optional[Path]:
    """Download and decrypt a Deezer track. Returns path or None on failure.

    Requires: DEEZER_ARL env var + pycryptodome installed.
    """
    if Blowfish is None:
        logger.warning("pycryptodome not installed — Deezer download unavailable")
        return None

    track_data = await _get_track_data(track_id)
    if not track_data:
        return None

    track_token = track_data.get("TRACK_TOKEN", "")
    sng_id = str(track_data.get("SNG_ID", track_id))
    if not track_token:
        logger.warning("No TRACK_TOKEN for Deezer track %s", track_id)
        return None

    # Try MP3_320 first, fallback to MP3_128
    media_url = await _get_media_url(track_token, quality)
    if not media_url and quality != "MP3_128":
        media_url = await _get_media_url(track_token, "MP3_128")
    if not media_url:
        logger.warning("No media URL for Deezer track %s", track_id)
        return None

    bf_key = _get_blowfish_key(sng_id)
    staged = stage_path_for(dest, suffix=".dz")

    try:
        session = get_session()
        async with session.get(
            media_url,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            resp.raise_for_status()
            with staged.open("wb") as f:
                chunk_idx = 0
                async for chunk in resp.content.iter_chunked(2048):
                    if len(chunk) == 2048 and chunk_idx % 3 == 0:
                        chunk = _decrypt_chunk(chunk, bf_key)
                    f.write(chunk)
                    chunk_idx += 1

        return finalize_staged_file(staged, dest)
    except Exception as e:
        cleanup_staged_files(staged)
        logger.error("Deezer download failed for track %s: %s", track_id, e)
        return None
