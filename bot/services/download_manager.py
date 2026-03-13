"""
download_manager.py — Intelligent download orchestrator.

Features:
  1. Request coalescing: multiple requests for the same track share one download.
  2. Chunked parallel download: split direct audio URL into multiple Range segments.
  3. Auto-scaling thread pool: grows under load, shrinks when idle.
  4. Concurrency limiter: semaphore prevents resource exhaustion.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import aiohttp

from bot.config import settings
from bot.services.downloader import cleanup_staged_files, finalize_staged_file, stage_path_for

logger = logging.getLogger(__name__)

# ── Configuration (VPS-optimized via config.py) ─────────────────────────────

MIN_WORKERS = settings.YTDL_WORKERS  # baseline thread pool size
MAX_WORKERS = settings.YTDL_WORKERS * settings.YTDL_MAX_WORKERS_MULTIPLIER  # max scaling limit
MAX_CONCURRENT_DOWNLOADS = MAX_WORKERS + 4  # semaphore limit
CHUNK_SIZE = 4 * 1024 * 1024         # 4 MB per chunk for parallel download (was 2MB)
MIN_FILE_SIZE_FOR_CHUNKS = 256 * 1024  # chunk files > 256 KB (was 512KB)
MAX_PARALLEL_CHUNKS = settings.YTDL_CONCURRENT_FRAGMENTS  # max parallel Range segments
SCALE_CHECK_INTERVAL = 3             # seconds between scaling checks (was 5)


class DownloadManager:
    """Singleton download orchestrator."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=MIN_WORKERS, thread_name_prefix="dl"
        )
        self._current_workers = MIN_WORKERS
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

        # Coalescing: video_id -> Future[Path]
        self._inflight: dict[str, asyncio.Future[Path]] = {}
        self._lock = asyncio.Lock()

        # Stats for auto-scaling
        self._active_count = 0
        self._queue_depth = 0
        self._last_scale_check = 0.0

    # ── Public API ───────────────────────────────────────────────────────

    async def download(
        self,
        video_id: str,
        bitrate: int = 192,
        progress_cb=None,
        dl_id: str | None = None,
    ) -> Path:
        """Download a track, coalescing duplicate requests."""
        mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
        if mp3_path.exists() and mp3_path.stat().st_size > 10240:
            return mp3_path

        async with self._lock:
            if video_id in self._inflight:
                logger.debug("Coalescing download for %s", video_id)
                return await self._inflight[video_id]

            future: asyncio.Future[Path] = asyncio.get_running_loop().create_future()
            self._inflight[video_id] = future

        try:
            result = await self._do_download(video_id, bitrate, progress_cb, dl_id)
            future.set_result(result)
            return result
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(video_id, None)

    async def chunked_download_url(
        self,
        url: str,
        dest: Path,
        session: aiohttp.ClientSession | None = None,
    ) -> Path:
        """Download a direct URL using parallel Range requests."""
        own_session = False
        if session is None:
            session = aiohttp.ClientSession()
            own_session = True

        staged_dest: Path | None = None
        try:
            staged_dest = stage_path_for(dest, suffix=".chunked")
            # Get file size
            content_length = await self._get_content_length(session, url)
            if not content_length or content_length < MIN_FILE_SIZE_FOR_CHUNKS:
                # Small file — single request
                return await self._single_download(session, url, dest)

            # Split into chunks
            chunks = self._plan_chunks(content_length)
            logger.info(
                "Chunked download: %s → %d chunks (%.1f MB)",
                dest.name, len(chunks), content_length / (1024 * 1024),
            )

            # Download all chunks in parallel
            chunk_data = [None] * len(chunks)

            async def _fetch_chunk(idx: int, start: int, end: int):
                headers = {"Range": f"bytes={start}-{end}"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status not in (200, 206):
                        raise IOError(f"Chunk {idx} failed: HTTP {resp.status}")
                    chunk_data[idx] = await resp.read()

            await asyncio.gather(
                *[_fetch_chunk(i, s, e) for i, (s, e) in enumerate(chunks)]
            )

            # Merge chunks to file
            with open(staged_dest, "wb") as f:
                for data in chunk_data:
                    f.write(data)

            return finalize_staged_file(staged_dest, dest)
        except Exception:
            cleanup_staged_files(staged_dest)
            raise
        finally:
            if own_session:
                await session.close()

    @property
    def stats(self) -> dict:
        """Return current manager statistics."""
        return {
            "active_downloads": self._active_count,
            "queued": self._queue_depth,
            "inflight_coalesced": len(self._inflight),
            "pool_workers": self._current_workers,
            "pool_max": MAX_WORKERS,
        }

    async def shutdown(self) -> None:
        self._pool.shutdown(wait=False)

    # ── Internal ─────────────────────────────────────────────────────────

    async def _do_download(
        self,
        video_id: str,
        bitrate: int,
        progress_cb,
        dl_id: str | None,
    ) -> Path:
        self._queue_depth += 1
        await self._maybe_scale_up()

        async with self._semaphore:
            self._queue_depth -= 1
            self._active_count += 1
            try:
                from bot.services.downloader import _download_sync
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._pool,
                    _download_sync,
                    video_id,
                    settings.DOWNLOAD_DIR,
                    bitrate,
                    progress_cb,
                    dl_id,
                )
                return result
            finally:
                self._active_count -= 1
                await self._maybe_scale_down()

    async def _maybe_scale_up(self) -> None:
        """Grow thread pool if queue is building up."""
        now = time.monotonic()
        if now - self._last_scale_check < SCALE_CHECK_INTERVAL:
            return
        self._last_scale_check = now

        pending = self._queue_depth
        if pending > self._current_workers and self._current_workers < MAX_WORKERS:
            new_size = min(self._current_workers + 2, MAX_WORKERS)
            self._pool._max_workers = new_size
            self._current_workers = new_size
            logger.info(
                "Auto-scale UP: workers %d → %d (queue=%d, active=%d)",
                self._current_workers - 2, new_size, pending, self._active_count,
            )

    async def _maybe_scale_down(self) -> None:
        """Shrink thread pool when idle."""
        now = time.monotonic()
        if now - self._last_scale_check < SCALE_CHECK_INTERVAL:
            return
        self._last_scale_check = now

        if (
            self._active_count <= MIN_WORKERS
            and self._queue_depth == 0
            and self._current_workers > MIN_WORKERS
        ):
            self._pool._max_workers = MIN_WORKERS
            self._current_workers = MIN_WORKERS
            logger.info("Auto-scale DOWN: workers → %d", MIN_WORKERS)

    @staticmethod
    def _plan_chunks(total: int) -> list[tuple[int, int]]:
        """Split total bytes into Range segments."""
        num_chunks = min(MAX_PARALLEL_CHUNKS, max(1, total // CHUNK_SIZE))
        chunk_size = total // num_chunks
        chunks = []
        for i in range(num_chunks):
            start = i * chunk_size
            end = (i + 1) * chunk_size - 1 if i < num_chunks - 1 else total - 1
            chunks.append((start, end))
        return chunks

    @staticmethod
    async def _get_content_length(
        session: aiohttp.ClientSession, url: str
    ) -> Optional[int]:
        try:
            async with session.head(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                accept_ranges = resp.headers.get("Accept-Ranges", "")
                if "bytes" not in accept_ranges:
                    return None
                cl = resp.headers.get("Content-Length")
                return int(cl) if cl else None
        except Exception:
            return None

    @staticmethod
    async def _single_download(
        session: aiohttp.ClientSession, url: str, dest: Path
    ) -> Path:
        staged_dest = stage_path_for(dest, suffix=".single")
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise IOError(f"Download failed: HTTP {resp.status}")
                with open(staged_dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
            return finalize_staged_file(staged_dest, dest)
        except Exception:
            cleanup_staged_files(staged_dest)
            raise


# Singleton
download_manager = DownloadManager()
