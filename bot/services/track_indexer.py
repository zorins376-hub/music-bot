"""Background track indexer — harvests FULL metadata from music APIs into DB.

Builds a proper music database (like Spotify / Yandex Music) with:
  title, artist, album, genre, release_year, label, ISRC, explicit,
  popularity, language, duration, cover_url, BPM

Sources:
  1. All chart sources (Shazam/Apple, YouTube, Yandex, RusRadio, EuropaPlus)
  2. Yandex Music — chart, new releases, landing playlists (genre, year, label)
  3. Spotify — new releases, featured playlists (genre, year, ISRC, popularity)
"""

import asyncio
import logging
import re
import unicodedata
from typing import Any

from bot.config import settings
from bot.db import upsert_track

logger = logging.getLogger(__name__)

_INDEXER_INTERVAL = 4 * 3600  # every 4 hours


# ── Language detection ────────────────────────────────────────────────────

def _detect_language(text: str) -> str | None:
    """Detect dominant script: 'ru', 'en', or None."""
    cyr = lat = 0
    for ch in text:
        if ch.isalpha():
            try:
                name = unicodedata.name(ch, "")
            except ValueError:
                continue
            if "CYRILLIC" in name:
                cyr += 1
            elif "LATIN" in name:
                lat += 1
    if cyr > lat:
        return "ru"
    if lat > cyr:
        return "en"
    return None


# ── Chart track indexing ──────────────────────────────────────────────────

async def index_chart_tracks() -> int:
    """Save all current chart tracks to DB. Returns count of indexed tracks."""
    from bot.handlers.charts import _get_chart, _CHART_FETCHERS

    total = 0
    for source in _CHART_FETCHERS:
        try:
            tracks = await _get_chart(source)
            if not tracks:
                continue
            count = await _index_track_list(tracks, default_source=source)
            total += count
            logger.info("Indexed %d tracks from chart:%s", count, source)
        except Exception as e:
            logger.warning("Chart index failed for %s: %s", source, e)
    return total


# ── Yandex Music indexing (full metadata) ─────────────────────────────────

async def index_yandex_popular() -> int:
    """Fetch Yandex Music popular playlists & new releases with FULL metadata."""
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

        # 1. Landing blocks (new-releases, chart, personal playlists)
        try:
            landing = await client.landing(["new-releases", "chart"])
            for block in (landing.blocks or []):
                for entity in (block.entities or []):
                    playlist = getattr(entity, "data", None)
                    if not playlist:
                        continue
                    tracks_list = getattr(playlist, "tracks", None)
                    if not tracks_list:
                        continue
                    batch = _yandex_tracks_to_dicts(tracks_list)
                    cnt = await _index_track_list(batch, default_source="yandex")
                    total += cnt
        except Exception as e:
            logger.debug("Yandex landing error: %s", e)

        # 2. New releases — full album metadata (genre, year, label)
        try:
            new_releases = await client.new_releases()
            if new_releases:
                albums_to_fetch = new_releases[:50] if isinstance(new_releases, list) else []
                for album in albums_to_fetch:
                    album_id = getattr(album, "id", None)
                    if not album_id:
                        continue
                    try:
                        full_album = await client.albums_with_tracks(album_id)
                        if full_album and full_album.volumes:
                            # Album-level metadata
                            album_meta = _extract_yandex_album_meta(full_album)
                            for volume in full_album.volumes:
                                batch = _yandex_tracks_to_dicts(volume, album_meta=album_meta)
                                cnt = await _index_track_list(batch, default_source="yandex")
                                total += cnt
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Yandex new_releases error: %s", e)

        # 3. Genre playlists (popular in each genre)
        try:
            genres = await client.genres()
            if genres:
                for genre_obj in genres[:15]:  # top 15 genres
                    genre_id = getattr(genre_obj, "id", None)
                    genre_title = getattr(genre_obj, "title", None) or genre_id
                    if not genre_id:
                        continue
                    try:
                        # Yandex metatag playlists for genres
                        radio_info = getattr(genre_obj, "radio_icon", None)
                        sub_genres = getattr(genre_obj, "sub_genres", []) or []
                        # Use the genre's "chart" or similar
                        chart = await client.chart(genre_id)
                        if chart and getattr(chart, "chart", None):
                            chart_tracks = getattr(chart.chart, "tracks", []) or []
                            batch = _yandex_tracks_to_dicts(
                                chart_tracks[:50],
                                force_genre=genre_title,
                            )
                            cnt = await _index_track_list(batch, default_source="yandex")
                            total += cnt
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Yandex genres error: %s", e)

        logger.info("Indexed %d Yandex Music tracks total", total)
    except Exception as e:
        logger.warning("Yandex indexing error: %s", e)

    return total


def _extract_yandex_album_meta(album) -> dict[str, Any]:
    """Extract album-level metadata from a Yandex Music Album object."""
    meta: dict[str, Any] = {}
    # Album name
    album_title = getattr(album, "title", None)
    if album_title:
        meta["album"] = album_title
    # Genre
    genre = getattr(album, "genre", None)
    if genre:
        meta["genre"] = genre
    # Year
    year = getattr(album, "year", None)
    if year:
        meta["release_year"] = year
    # Label
    labels = getattr(album, "labels", None) or []
    if labels:
        first_label = labels[0]
        label_name = getattr(first_label, "name", None) or (first_label if isinstance(first_label, str) else None)
        if label_name:
            meta["label"] = str(label_name)
    # Cover
    cover_uri = getattr(album, "cover_uri", None) or ""
    if cover_uri:
        meta["cover_url"] = "https://" + cover_uri.replace("%%", "400x400")
    return meta


def _yandex_tracks_to_dicts(
    tracks_list,
    album_meta: dict[str, Any] | None = None,
    force_genre: str | None = None,
) -> list[dict[str, Any]]:
    """Convert Yandex Music SDK track objects to rich metadata dicts."""
    result = []
    for item in tracks_list:
        track = getattr(item, "track", None) or item
        if not track:
            continue
        title = getattr(track, "title", None) or ""
        artists = getattr(track, "artists", []) or []
        artist = ", ".join(a.name for a in artists if getattr(a, "name", None)) if artists else ""
        if not title:
            continue
        track_id = getattr(track, "id", None) or getattr(track, "track_id", None)
        if not track_id:
            continue
        dur_ms = getattr(track, "duration_ms", 0) or 0

        # ── Cover ──
        cover_url = None
        cover_uri = getattr(track, "cover_uri", None) or ""
        if not cover_uri:
            albums = getattr(track, "albums", []) or []
            if albums:
                cover_uri = getattr(albums[0], "cover_uri", None) or ""
        if not cover_uri:
            cover_uri = getattr(track, "og_image", None) or ""
        if cover_uri:
            cover_url = "https://" + cover_uri.replace("%%", "400x400")
        if not cover_url and album_meta:
            cover_url = album_meta.get("cover_url")

        # ── Album metadata ──
        album_name = None
        genre = force_genre
        release_year = None
        label = None

        albums = getattr(track, "albums", []) or []
        if albums:
            alb = albums[0]
            album_name = getattr(alb, "title", None)
            if not genre:
                genre = getattr(alb, "genre", None)
            year = getattr(alb, "year", None)
            if year:
                release_year = year
            labels = getattr(alb, "labels", None) or []
            if labels:
                first_label = labels[0]
                lbl = getattr(first_label, "name", None) or (first_label if isinstance(first_label, str) else None)
                if lbl:
                    label = str(lbl)

        # Override from album_meta if we have richer data
        if album_meta:
            if not album_name:
                album_name = album_meta.get("album")
            if not genre:
                genre = album_meta.get("genre")
            if not release_year:
                release_year = album_meta.get("release_year")
            if not label:
                label = album_meta.get("label")

        # ── Explicit ──
        explicit = None
        content_warning = getattr(track, "content_warning", None)
        if content_warning:
            explicit = True
        elif hasattr(track, "explicit"):
            raw_explicit = getattr(track, "explicit", None)
            if raw_explicit is not None:
                explicit = bool(raw_explicit)

        # ── Language detection from title + artist ──
        lang = _detect_language(f"{artist} {title}")

        entry: dict[str, Any] = {
            "video_id": f"ym_{track_id}",
            "title": title,
            "artist": artist,
            "duration": round(dur_ms / 1000) if dur_ms else 0,
            "cover_url": cover_url,
            "source": "yandex",
            "album": album_name,
            "genre": genre,
            "release_year": release_year,
            "label": label,
            "explicit": explicit,
            "language": lang,
        }
        result.append(entry)
    return result


# ── Spotify indexing (full metadata) ──────────────────────────────────────

# Cache artist genres to avoid duplicate API calls within one indexing cycle
_artist_genre_cache: dict[str, str | None] = {}


async def index_spotify_popular() -> int:
    """Fetch Spotify new releases & playlists with FULL metadata."""
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        return 0

    try:
        from bot.services.spotify_provider import _get_client
    except ImportError:
        return 0

    total = 0
    loop = asyncio.get_event_loop()

    def _fetch_spotify_tracks() -> list[dict[str, Any]]:
        sp = _get_client()
        if not sp:
            return []
        tracks: list[dict[str, Any]] = []

        def _extract_track(t: dict, album_data: dict | None = None) -> dict[str, Any] | None:
            """Extract rich metadata from a Spotify track object."""
            title = (t.get("name") or "").strip()
            artists_list = t.get("artists") or []
            artist = ", ".join(a["name"] for a in artists_list if a.get("name"))
            dur_ms = t.get("duration_ms") or 0
            tid = t.get("id") or ""
            if not title or not artist or not tid:
                return None

            # Album info (from track.album or passed album_data)
            alb = t.get("album") or album_data or {}
            album_name = alb.get("name")
            release_date = alb.get("release_date") or ""
            release_year = None
            if release_date:
                try:
                    release_year = int(release_date[:4])
                except (ValueError, IndexError):
                    pass

            # Cover
            cover_url = None
            images = alb.get("images") or []
            if images:
                cover_url = images[0].get("url")

            # Label (only on full album objects)
            label = alb.get("label")

            # ISRC (from external_ids)
            isrc = None
            ext_ids = t.get("external_ids") or {}
            if ext_ids:
                isrc = ext_ids.get("isrc")

            # Explicit
            explicit = t.get("explicit")

            # Popularity (0-100)
            popularity = t.get("popularity")

            # Genre — Spotify puts genres on artists, not tracks
            # Try to get from first artist (cached per indexing cycle)
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
                            genre = genres[0]  # primary genre
                        _artist_genre_cache[first_artist_id] = genre
                    except Exception:
                        _artist_genre_cache[first_artist_id] = None

            # Language detection
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

        # 1. New releases (full album metadata — label, year, genre)
        try:
            releases = sp.new_releases(limit=50)
            albums = (releases or {}).get("albums", {}).get("items", [])
            for album in albums[:30]:
                album_id = album.get("id")
                if not album_id:
                    continue
                try:
                    # Fetch full album for label info
                    full_album = sp.album(album_id)
                    album_tracks = sp.album_tracks(album_id, limit=50)
                    for t in (album_tracks or {}).get("items", []):
                        entry = _extract_track(t, album_data=full_album)
                        if entry:
                            tracks.append(entry)
                except Exception:
                    continue
        except Exception:
            pass

        # 2. Featured playlists (popular tracks with full metadata)
        try:
            featured = sp.featured_playlists(limit=10)
            playlists = (featured or {}).get("playlists", {}).get("items", [])
            for pl in playlists[:5]:
                pl_id = pl.get("id")
                if not pl_id:
                    continue
                try:
                    items = sp.playlist_items(pl_id, limit=50)
                    for item in (items or {}).get("items", []):
                        t = (item or {}).get("track")
                        if not t:
                            continue
                        entry = _extract_track(t)
                        if entry:
                            tracks.append(entry)
                except Exception:
                    continue
        except Exception:
            pass

        # 3. Top 50 playlists (global & Russia)
        _TOP_PLAYLISTS = [
            "37i9dQZEVXbMDoHDwVN2tF",  # Global Top 50
            "37i9dQZEVXbL8l7ra5vVdB",  # Top 50 Russia
        ]
        for pl_id in _TOP_PLAYLISTS:
            try:
                items = sp.playlist_items(pl_id, limit=50)
                for item in (items or {}).get("items", []):
                    t = (item or {}).get("track")
                    if not t:
                        continue
                    entry = _extract_track(t)
                    if entry:
                        tracks.append(entry)
            except Exception:
                continue

        return tracks

    try:
        _artist_genre_cache.clear()
        spotify_tracks = await loop.run_in_executor(None, _fetch_spotify_tracks)
        if spotify_tracks:
            total = await _index_track_list(spotify_tracks, default_source="spotify")
            logger.info("Indexed %d Spotify tracks", total)
    except Exception as e:
        logger.warning("Spotify indexing error: %s", e)

    return total


# ── Common helpers ────────────────────────────────────────────────────────

async def _index_track_list(
    tracks: list[dict[str, Any]],
    default_source: str = "youtube",
) -> int:
    """Upsert a list of track dicts with full metadata into DB."""
    count = 0
    for tr in tracks:
        source_id = tr.get("video_id") or ""
        if not source_id:
            continue
        title = tr.get("title") or tr.get("name")
        artist = tr.get("artist") or tr.get("uploader")
        if not title:
            continue

        source = tr.get("source", default_source)
        # Normalize chart source names
        if source in ("shazam", "apple"):
            source = "apple"
        elif source in ("vk",):
            source = "yandex"

        # Auto-detect language if not provided
        language = tr.get("language")
        if not language and artist and title:
            language = _detect_language(f"{artist} {title}")

        try:
            await upsert_track(
                source_id=source_id,
                title=title,
                artist=artist,
                duration=tr.get("duration"),
                source=source,
                cover_url=tr.get("cover_url"),
                genre=tr.get("genre"),
                album=tr.get("album"),
                release_year=tr.get("release_year"),
                label=tr.get("label"),
                isrc=tr.get("isrc"),
                explicit=tr.get("explicit"),
                popularity=tr.get("popularity"),
                language=language,
            )
            count += 1
        except Exception as e:
            logger.debug("Index track %s failed: %s", source_id, e)

    # Ingest to Supabase AI for embedding enrichment (best-effort)
    await _ingest_to_supabase(tracks)
    return count


async def _ingest_to_supabase(tracks: list[dict[str, Any]]) -> None:
    """Best-effort ingest to Supabase AI for recommendation enrichment."""
    if not getattr(settings, "SUPABASE_AI_ENABLED", False):
        return
    try:
        from bot.services.supabase_ai import supabase_ai
        if not supabase_ai.enabled:
            return
        for tr in tracks[:100]:  # cap to avoid overloading
            source_id = tr.get("video_id") or ""
            if not source_id:
                continue
            await supabase_ai.ingest_event(
                event="index",
                user_id=0,  # system user
                track={
                    "source_id": source_id,
                    "title": tr.get("title") or "",
                    "artist": tr.get("artist") or tr.get("uploader") or "",
                    "genre": tr.get("genre"),
                    "album": tr.get("album"),
                    "release_year": tr.get("release_year"),
                    "duration": tr.get("duration"),
                    "cover_url": tr.get("cover_url"),
                    "language": tr.get("language"),
                },
                source="indexer",
            )
    except Exception as e:
        logger.debug("Supabase ingest batch error: %s", e)


# ── Main orchestrator ─────────────────────────────────────────────────────

async def run_indexer() -> dict[str, int]:
    """Run full indexing cycle across all sources. Returns per-source counts."""
    logger.info("Track indexer starting...")
    results: dict[str, int] = {}

    # 1. Charts (fast — uses cached data)
    results["charts"] = await index_chart_tracks()

    # 2. Yandex Music (full metadata: genre, year, label, album)
    results["yandex"] = await index_yandex_popular()

    # 3. Spotify (full metadata: genre, year, ISRC, popularity, label)
    results["spotify"] = await index_spotify_popular()

    total = sum(results.values())
    logger.info("Track indexer done: %d total (%s)", total, results)
    return results


async def start_indexer_scheduler() -> None:
    """Start background indexer loop — runs after initial chart prewarm."""
    asyncio.create_task(_indexer_loop())


async def _indexer_loop() -> None:
    """Periodic indexer loop."""
    # Wait for initial startup (charts need to be warmed first)
    await asyncio.sleep(30)
    while True:
        try:
            await run_indexer()
        except Exception as e:
            logger.warning("Indexer loop error: %s", e)
        await asyncio.sleep(_INDEXER_INTERVAL)
