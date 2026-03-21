"""Deep background crawler — systematically indexes Yandex Music & Spotify catalogs.

Strategy:
  1. Crawl ALL genres + subgenres → discover artists from charts
  2. Fetch full artist discographies (all albums → all tracks)
  3. Follow "related artists" graph to discover more
  4. Run continuously in small batches with rate limiting

State tracked via Redis sets (in-memory fallback):
  - crawler:done:ym:artists   — processed Yandex artist IDs
  - crawler:done:ym:albums    — processed Yandex album IDs
  - crawler:done:sp:artists   — processed Spotify artist IDs
  - crawler:done:sp:albums    — processed Spotify album IDs
  - crawler:queue:ym:artists  — pending Yandex artist IDs
  - crawler:queue:sp:artists  — pending Spotify artist IDs
"""

import asyncio
import logging
from typing import Any

from bot.config import settings
from bot.services.track_indexer import (
    _artist_genre_cache,
    _detect_language,
    _extract_yandex_album_meta,
    _index_track_list,
    _yandex_tracks_to_dicts,
)

logger = logging.getLogger(__name__)

# ── Rate limiting ─────────────────────────────────────────────────────────
_BATCH_DELAY = 1.0        # seconds between API calls
_CYCLE_DELAY = 60          # seconds between full crawl cycles
_ARTIST_BATCH = 10         # artists per batch before sleeping
_ARTIST_BATCH_DELAY = 5.0  # seconds between artist batches

# ── In-memory fallback when Redis unavailable ─────────────────────────────
_mem_done: dict[str, set[str]] = {
    "ym:artists": set(),
    "ym:albums": set(),
    "sp:artists": set(),
    "sp:albums": set(),
}
_mem_queue: dict[str, list[str]] = {
    "ym:artists": [],
    "sp:artists": [],
}


# ── Queue helpers (Redis-backed with in-memory fallback) ──────────────────

async def _get_redis():
    try:
        from bot.services.cache import cache
        r = await cache.redis()
        if r:
            return r
    except Exception:
        logger.debug("_get_redis failed", exc_info=True)
    return None


async def _is_done(namespace: str, entity_id: str) -> bool:
    r = await _get_redis()
    if r:
        try:
            return await r.sismember(f"crawler:done:{namespace}", entity_id)
        except Exception:
            logger.debug("_is_done redis check failed ns=%s", namespace, exc_info=True)
    return entity_id in _mem_done.get(namespace, set())


async def _mark_done(namespace: str, entity_id: str) -> None:
    r = await _get_redis()
    if r:
        try:
            await r.sadd(f"crawler:done:{namespace}", entity_id)
            return
        except Exception:
            logger.debug("_mark_done redis set failed ns=%s", namespace, exc_info=True)
    _mem_done.setdefault(namespace, set()).add(entity_id)


async def _enqueue(namespace: str, entity_id: str) -> None:
    """Add to queue if not already done."""
    if await _is_done(namespace, entity_id):
        return
    r = await _get_redis()
    if r:
        try:
            await r.sadd(f"crawler:queue:{namespace}", entity_id)
            return
        except Exception:
            logger.debug("_enqueue redis set failed ns=%s", namespace, exc_info=True)
    q = _mem_queue.setdefault(namespace, [])
    if entity_id not in q:
        q.append(entity_id)


async def _dequeue_batch(namespace: str, count: int = 10) -> list[str]:
    """Get up to `count` items from queue that aren't already done."""
    batch: list[str] = []
    r = await _get_redis()
    if r:
        try:
            items = await r.spop(f"crawler:queue:{namespace}", count)
            if items:
                for item in items:
                    if not await _is_done(namespace, item):
                        batch.append(item)
            return batch
        except Exception:
            logger.debug("_dequeue_batch redis failed ns=%s", namespace, exc_info=True)
    q = _mem_queue.get(namespace, [])
    while q and len(batch) < count:
        item = q.pop(0)
        if not await _is_done(namespace, item):
            batch.append(item)
    return batch


async def _queue_size(namespace: str) -> int:
    r = await _get_redis()
    if r:
        try:
            return await r.scard(f"crawler:queue:{namespace}")
        except Exception:
            logger.debug("_queue_size redis failed ns=%s", namespace, exc_info=True)
    return len(_mem_queue.get(namespace, []))


async def _done_count(namespace: str) -> int:
    r = await _get_redis()
    if r:
        try:
            return await r.scard(f"crawler:done:{namespace}")
        except Exception:
            logger.debug("_done_count redis failed ns=%s", namespace, exc_info=True)
    return len(_mem_done.get(namespace, set()))


# ── Deep Yandex Music crawler ────────────────────────────────────────────

async def deep_crawl_yandex() -> int:
    """Systematically crawl Yandex Music: all genres → artist discographies."""
    if not settings.YANDEX_MUSIC_TOKEN:
        return 0
    try:
        from yandex_music import ClientAsync
    except ImportError:
        return 0

    total = 0
    token = settings.YANDEX_MUSIC_TOKEN

    try:
        client = await ClientAsync(token).init()

        # ── Phase 1: Discover artists from ALL genres + subgenres ──
        try:
            genres = await client.genres()
            if genres:
                all_genre_ids = _collect_all_genre_ids(genres)
                logger.info("Yandex deep crawl: %d genres found", len(all_genre_ids))

                for genre_id, genre_title in all_genre_ids:
                    try:
                        chart = await client.chart(genre_id)
                        if chart and getattr(chart, "chart", None):
                            chart_tracks = getattr(chart.chart, "tracks", []) or []
                            # Index tracks from chart
                            batch = _yandex_tracks_to_dicts(
                                chart_tracks[:100],
                                force_genre=genre_title,
                            )
                            cnt = await _index_track_list(batch, default_source="yandex")
                            total += cnt

                            # Discover artists → queue for discography crawl
                            for item in chart_tracks:
                                track = getattr(item, "track", None) or item
                                for art in getattr(track, "artists", []) or []:
                                    art_id = str(getattr(art, "id", "") or "")
                                    if art_id:
                                        await _enqueue("ym:artists", art_id)

                        await asyncio.sleep(_BATCH_DELAY)
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Yandex genre crawl error: %s", e)

        # ── Phase 2: Crawl artist discographies ──
        artists_batch = await _dequeue_batch("ym:artists", _ARTIST_BATCH)
        processed = 0
        while artists_batch:
            for artist_id in artists_batch:
                try:
                    cnt = await _crawl_yandex_artist(client, artist_id)
                    total += cnt
                    processed += 1
                except Exception as e:
                    logger.debug("Yandex artist %s error: %s", artist_id, e)
                await asyncio.sleep(_BATCH_DELAY)

            if processed >= _ARTIST_BATCH:
                await asyncio.sleep(_ARTIST_BATCH_DELAY)
                processed = 0
            artists_batch = await _dequeue_batch("ym:artists", _ARTIST_BATCH)

        ym_done = await _done_count("ym:artists")
        ym_queue = await _queue_size("ym:artists")
        logger.info(
            "Yandex deep crawl cycle done: %d tracks, %d artists done, %d queued",
            total, ym_done, ym_queue,
        )
    except Exception as e:
        logger.warning("Yandex deep crawl error: %s", e)

    return total


def _collect_all_genre_ids(genres) -> list[tuple[str, str]]:
    """Recursively collect all genre/subgenre IDs with their titles."""
    result: list[tuple[str, str]] = []
    for g in genres:
        gid = getattr(g, "id", None)
        title = getattr(g, "title", None) or gid
        if gid:
            result.append((str(gid), str(title)))
        # Recurse into subgenres
        subs = getattr(g, "sub_genres", []) or []
        if subs:
            result.extend(_collect_all_genre_ids(subs))
    return result


async def _crawl_yandex_artist(client, artist_id: str) -> int:
    """Fetch all albums of a Yandex Music artist and index their tracks."""
    if await _is_done("ym:artists", artist_id):
        return 0

    total = 0
    try:
        brief = await client.artists_brief_info(int(artist_id))
        if not brief:
            await _mark_done("ym:artists", artist_id)
            return 0

        # Get album IDs from artist
        albums = getattr(brief, "albums", []) or []
        # Also check db_albums
        db_albums = getattr(brief, "db_albums", []) or []
        all_albums = list(albums) + list(db_albums)

        for album in all_albums:
            album_id = str(getattr(album, "id", "") or "")
            if not album_id or await _is_done("ym:albums", album_id):
                continue

            try:
                full_album = await client.albums_with_tracks(int(album_id))
                if full_album and getattr(full_album, "volumes", None):
                    album_meta = _extract_yandex_album_meta(full_album)
                    for volume in full_album.volumes:
                        batch = _yandex_tracks_to_dicts(volume, album_meta=album_meta)
                        cnt = await _index_track_list(batch, default_source="yandex")
                        total += cnt

                        # Discover more artists from collaborations
                        for item in volume:
                            track = getattr(item, "track", None) or item
                            for art in getattr(track, "artists", []) or []:
                                aid = str(getattr(art, "id", "") or "")
                                if aid and aid != artist_id:
                                    await _enqueue("ym:artists", aid)

                await _mark_done("ym:albums", album_id)
                await asyncio.sleep(_BATCH_DELAY * 0.5)
            except Exception:
                continue

        # Also try to get "similar artists" for graph expansion
        try:
            similar = getattr(brief, "similar_artists", []) or []
            for sim in similar:
                sim_id = str(getattr(sim, "id", "") or "")
                if sim_id:
                    await _enqueue("ym:artists", sim_id)
        except Exception:
            logger.debug("yandex similar artists fetch failed artist=%s", artist_id, exc_info=True)

    except Exception as e:
        logger.debug("Yandex artist %s crawl error: %s", artist_id, e)

    await _mark_done("ym:artists", artist_id)
    return total


# ── Deep Spotify crawler ─────────────────────────────────────────────────

async def deep_crawl_spotify() -> int:
    """Systematically crawl Spotify: all categories → artist discographies."""
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        return 0
    try:
        from bot.services.spotify_provider import _get_client
    except ImportError:
        return 0

    total = 0
    loop = asyncio.get_event_loop()

    def _discover_from_categories() -> list[dict[str, Any]]:
        """Fetch tracks from ALL Spotify categories/playlists."""
        sp = _get_client()
        if not sp:
            return []
        tracks: list[dict[str, Any]] = []
        discovered_artists: list[str] = []

        # Get all categories
        try:
            offset = 0
            while True:
                cats = sp.categories(limit=50, offset=offset, country="RU")
                items = (cats or {}).get("categories", {}).get("items", [])
                if not items:
                    break
                for cat in items:
                    cat_id = cat.get("id")
                    if not cat_id:
                        continue
                    try:
                        pls = sp.category_playlists(cat_id, limit=50, country="RU")
                        pl_items = (pls or {}).get("playlists", {}).get("items", [])
                        for pl in (pl_items or [])[:20]:
                            pl_id = (pl or {}).get("id")
                            if not pl_id:
                                continue
                            try:
                                pit = sp.playlist_items(pl_id, limit=100)
                                for pi in (pit or {}).get("items", []):
                                    t = (pi or {}).get("track")
                                    if not t or not t.get("id"):
                                        continue
                                    entry = _extract_spotify_track(sp, t)
                                    if entry:
                                        tracks.append(entry)
                                    # Collect artist IDs
                                    for a in t.get("artists") or []:
                                        aid = a.get("id")
                                        if aid:
                                            discovered_artists.append(aid)
                            except Exception:
                                continue
                    except Exception:
                        continue
                offset += 50
                if offset > 200:  # Spotify typically has <200 categories
                    break
        except Exception:
            logger.debug("spotify categories discovery failed", exc_info=True)

        return tracks, discovered_artists

    def _crawl_spotify_artist_sync(sp, artist_id: str) -> tuple[list[dict], list[str]]:
        """Fetch all albums/tracks for a Spotify artist. Returns (tracks, new_artist_ids)."""
        tracks: list[dict[str, Any]] = []
        new_artists: list[str] = []

        try:
            # Get all albums (paginated)
            offset = 0
            album_ids: list[str] = []
            while True:
                albums = sp.artist_albums(
                    artist_id,
                    album_type="album,single,compilation",
                    limit=50,
                    offset=offset,
                )
                items = (albums or {}).get("items", [])
                if not items:
                    break
                for alb in items:
                    aid = alb.get("id")
                    if aid:
                        album_ids.append(aid)
                offset += 50
                next_url = (albums or {}).get("next")
                if not next_url:
                    break

            # Fetch tracks from each album
            for album_id in album_ids:
                try:
                    full_album = sp.album(album_id)
                    album_tracks = sp.album_tracks(album_id, limit=50)
                    for t in (album_tracks or {}).get("items", []):
                        entry = _extract_spotify_track(sp, t, album_data=full_album)
                        if entry:
                            tracks.append(entry)
                        # Discover collaborators
                        for a in t.get("artists") or []:
                            collab_id = a.get("id")
                            if collab_id and collab_id != artist_id:
                                new_artists.append(collab_id)
                except Exception:
                    continue

            # Get related artists for graph expansion
            try:
                related = sp.artist_related_artists(artist_id)
                for ra in (related or {}).get("artists", []):
                    ra_id = ra.get("id")
                    if ra_id:
                        new_artists.append(ra_id)
            except Exception:
                logger.debug("spotify related artists fetch failed", exc_info=True)

        except Exception:
            logger.debug("spotify artist crawl failed artist=%s", artist_id, exc_info=True)

        return tracks, new_artists

    try:
        _artist_genre_cache.clear()

        # Phase 1: Discover from categories
        logger.info("Spotify deep crawl: scanning categories...")
        result = await loop.run_in_executor(None, _discover_from_categories)
        cat_tracks, discovered_ids = result
        if cat_tracks:
            cnt = await _index_track_list(cat_tracks, default_source="spotify")
            total += cnt
            logger.info("Spotify categories: indexed %d tracks, discovered %d artists",
                        cnt, len(set(discovered_ids)))

        # Queue discovered artists
        for aid in set(discovered_ids):
            await _enqueue("sp:artists", aid)

        # Phase 2: Crawl artist discographies
        artists_batch = await _dequeue_batch("sp:artists", _ARTIST_BATCH)
        processed = 0
        while artists_batch:
            for artist_id in artists_batch:
                if await _is_done("sp:artists", artist_id):
                    continue
                try:
                    sp = await loop.run_in_executor(None, _get_client)
                    if not sp:
                        break
                    art_tracks, new_ids = await loop.run_in_executor(
                        None, _crawl_spotify_artist_sync, sp, artist_id,
                    )
                    if art_tracks:
                        cnt = await _index_track_list(art_tracks, default_source="spotify")
                        total += cnt
                    for nid in set(new_ids):
                        await _enqueue("sp:artists", nid)
                    await _mark_done("sp:artists", artist_id)
                    processed += 1
                except Exception as e:
                    logger.debug("Spotify artist %s error: %s", artist_id, e)
                    await _mark_done("sp:artists", artist_id)

                await asyncio.sleep(_BATCH_DELAY)

            if processed >= _ARTIST_BATCH:
                await asyncio.sleep(_ARTIST_BATCH_DELAY)
                processed = 0
            artists_batch = await _dequeue_batch("sp:artists", _ARTIST_BATCH)

        sp_done = await _done_count("sp:artists")
        sp_queue = await _queue_size("sp:artists")
        logger.info(
            "Spotify deep crawl cycle done: %d tracks, %d artists done, %d queued",
            total, sp_done, sp_queue,
        )
    except Exception as e:
        logger.warning("Spotify deep crawl error: %s", e)

    return total


def _extract_spotify_track(sp, t: dict, album_data: dict | None = None) -> dict[str, Any] | None:
    """Extract rich metadata from a Spotify track object."""
    title = (t.get("name") or "").strip()
    artists_list = t.get("artists") or []
    artist = ", ".join(a["name"] for a in artists_list if a.get("name"))
    dur_ms = t.get("duration_ms") or 0
    tid = t.get("id") or ""
    if not title or not tid:
        return None

    alb = t.get("album") or album_data or {}
    album_name = alb.get("name")
    release_date = alb.get("release_date") or ""
    release_year = None
    if release_date:
        try:
            release_year = int(release_date[:4])
        except (ValueError, IndexError):
            pass

    cover_url = None
    images = alb.get("images") or []
    if images:
        cover_url = images[0].get("url")

    label = alb.get("label")
    isrc = (t.get("external_ids") or {}).get("isrc")
    explicit = t.get("explicit")
    popularity = t.get("popularity")

    # Genre from first artist (cached)
    genre = None
    first_artist_id = artists_list[0].get("id") if artists_list else None
    if first_artist_id:
        if first_artist_id in _artist_genre_cache:
            genre = _artist_genre_cache[first_artist_id]
        else:
            try:
                artist_data = sp.artist(first_artist_id)
                genres = (artist_data or {}).get("genres") or []
                if genres:
                    genre = genres[0]
                _artist_genre_cache[first_artist_id] = genre
            except Exception:
                _artist_genre_cache[first_artist_id] = None

    lang = _detect_language(f"{artist} {title}")

    return {
        "video_id": f"sp_{tid}",
        "title": title,
        "artist": artist,
        "duration": dur_ms // 1000,
        "cover_url": cover_url,
        "source": "spotify",
        "album": album_name,
        "genre": genre,
        "release_year": release_year,
        "label": label,
        "isrc": isrc,
        "explicit": explicit,
        "popularity": popularity,
        "language": lang,
    }


# ── Main deep crawler orchestrator ───────────────────────────────────────

async def run_deep_crawl() -> dict[str, int]:
    """Run one deep crawl cycle."""
    logger.info("Deep crawler starting cycle...")
    results: dict[str, int] = {}
    results["yandex_deep"] = await deep_crawl_yandex()
    results["spotify_deep"] = await deep_crawl_spotify()
    total = sum(results.values())
    logger.info("Deep crawler cycle done: %d total (%s)", total, results)
    return results


async def start_deep_crawler() -> None:
    """Start the continuous deep crawler background loop."""
    asyncio.create_task(_deep_crawler_loop())


async def _deep_crawler_loop() -> None:
    """Continuous deep crawl loop — never stops, rate-limited."""
    # Wait for app to fully start + initial indexer to run first
    await asyncio.sleep(120)
    logger.info("Deep crawler started — will continuously index Yandex & Spotify catalogs")
    while True:
        try:
            stats = await run_deep_crawl()
            ym_q = await _queue_size("ym:artists")
            sp_q = await _queue_size("sp:artists")
            ym_d = await _done_count("ym:artists")
            sp_d = await _done_count("sp:artists")
            logger.info(
                "Deep crawler stats — YM: %d done / %d queued, SP: %d done / %d queued",
                ym_d, ym_q, sp_d, sp_q,
            )
        except Exception as e:
            logger.warning("Deep crawler loop error: %s", e)
        # Wait before next cycle — artists queue refills via graph expansion
        await asyncio.sleep(_CYCLE_DELAY)


async def get_crawler_stats() -> dict[str, Any]:
    """Get current crawler statistics."""
    return {
        "yandex": {
            "artists_done": await _done_count("ym:artists"),
            "artists_queued": await _queue_size("ym:artists"),
            "albums_done": await _done_count("ym:albums"),
        },
        "spotify": {
            "artists_done": await _done_count("sp:artists"),
            "artists_queued": await _queue_size("sp:artists"),
            "albums_done": await _done_count("sp:albums"),
        },
    }
