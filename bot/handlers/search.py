import asyncio
import html
import json as _json
import logging
import secrets
import time
import uuid
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatAction, MessageEntityType
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import settings
from bot.db import get_or_create_user, get_popular_titles, get_random_popular_track, increment_request_count, record_listening_event, search_local_tracks, upsert_track
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track, search_tracks, is_youtube_url, extract_youtube_video_id, resolve_youtube_url
from bot.services.spotify_provider import is_spotify_url, resolve_spotify_url, search_spotify
from bot.services.vk_provider import download_vk, search_vk
from bot.services.yandex_provider import download_yandex, search_yandex, is_yandex_music_url, resolve_yandex_url
from bot.services.metrics import cache_hits, cache_misses, requests_total
from bot.services.provider_health import record_provider_event
from bot.services.search_engine import (
    _relevance_score,
    deduplicate_results,
    is_lyric_like_query,
    needs_lyrics_search_boost,
    normalize_query,
    parse_query,
    query_title_hint_coverage,
    suggest_query,
    detect_script,
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
)
from bot.services.analytics import track_event
from bot.services.share_links import create_share_link, resolve_share_link
from bot.callbacks import TrackCallback, FeedbackCallback, AddToPlCb, AddToQueueCb, LyricsCb, LyrTransCb, FavoriteCb, ShareTrackCb, SimilarCb, StoryCb, TrackCardCb, TrackMenuCb, WrongTrackPickCb, WtCollapseCb, WtExpandCb
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()

_TRACK_SHARE_TTL = 30 * 24 * 3600  # 30 days
_DOWNLOAD_LOCK_TTL = 10

# Telegram message effect IDs: 🎉=5159385139981059251 🔥=5104841245755180586 👍=5107584321108051014
_EFFECT_FIRE = "5104841245755180586"


def _classify_download_error(err_msg: str) -> str:
    """Return i18n key for a download error message."""
    from bot.services.youtube_cookies import is_youtube_auth_error
    if is_youtube_auth_error(err_msg):
        return "error_yt_auth"
    if "Sign in to confirm your age" in err_msg:
        return "error_age_restricted"
    if "not available" in err_msg.lower() or "geo" in err_msg.lower() or "blocked" in err_msg.lower():
        return "error_geo_restricted"
    if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
        return "error_timeout"
    return "error_download"

# Group chat auto-cleanup timeout (seconds)
_GROUP_CLEANUP_SEC = 60

# Search result limits
_MAX_RESULTS_GROUP = 5      # In groups — search 5 candidates for retry

# ── Download progress ─────────────────────────────────────────────────────

_PROGRESS_BARS = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]


def _make_progress_bar(pct: int) -> str:
    """Build a compact 10-char progress bar from percentage."""
    filled = pct // 10
    return "█" * filled + "░" * (10 - filled)


def _make_progress_cb(status_msg, lang: str):
    """Create a thread-safe progress callback that throttles Telegram edits.

    Returns (callback_fn, last_edit_state_dict).
    The callback can be invoked from a worker thread — it schedules edits on the event loop.
    """
    loop = asyncio.get_event_loop()
    state = {"last_pct": -1, "last_edit": 0.0}

    def _on_progress(downloaded: int, total: int) -> None:
        pct = int(downloaded * 100 / total) if total else 0
        now = time.monotonic()
        # Only update every 20% or every 3 seconds (Telegram rate limits)
        if pct - state["last_pct"] < 20 and now - state["last_edit"] < 3:
            return
        state["last_pct"] = pct
        state["last_edit"] = now
        bar = _make_progress_bar(pct)
        mb_dl = downloaded / (1024 * 1024)
        mb_tt = total / (1024 * 1024)
        text = f"⬇ {t(lang, 'downloading')} {pct}%\n{bar}  {mb_dl:.1f} / {mb_tt:.1f} MB"
        asyncio.run_coroutine_threadsafe(_safe_edit(status_msg, text), loop)

    return _on_progress


import re as _re
_YT_ID_RE = _re.compile(r'^[A-Za-z0-9_-]{11}$')


def _is_valid_yt_id(video_id: str) -> bool:
    """Check if a string looks like a valid YouTube video ID (11 chars, base64url)."""
    return bool(_YT_ID_RE.match(video_id))


async def _resolve_yt_video_id(track_info: dict) -> str | None:
    """For non-YouTube tracks without a valid video_id, search YouTube by artist+title."""
    query = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
    yt_results = await search_tracks(query.strip(), max_results=1, source="youtube")
    if yt_results:
        return yt_results[0]["video_id"]
    return None


async def _safe_edit(msg, text: str) -> None:
    """Edit message text, ignoring any Telegram errors."""
    try:
        await msg.edit_text(text)
    except Exception:
        logger.debug("safe_edit failed", exc_info=True)


def _download_lock_key(user_id: int, track_id: str) -> str:
    return f"download:{user_id}:{track_id}"


async def _acquire_download_lock(user_id: int, track_id: str, ttl: int = _DOWNLOAD_LOCK_TTL) -> bool:
    """Acquire a short Redis lock for a user+track download flow.

    Fail-open if Redis is unavailable to avoid blocking playback.
    """
    try:
        key = _download_lock_key(user_id, track_id)
        acquired = await cache.redis.set(key, "1", ex=ttl, nx=True)
        return bool(acquired)
    except Exception:
        return True


async def _release_download_lock(user_id: int, track_id: str) -> None:
    """Release user+track download lock (best-effort)."""
    try:
        key = _download_lock_key(user_id, track_id)
        await cache.redis.delete(key)
    except Exception:
        logger.debug("release_download_lock failed user=%s", user_id, exc_info=True)


def _smart_bitrate(source: str | None, duration: int | None, default_br: int) -> int:
    """TASK-024: Choose bitrate based on source and duration.

    - Yandex → 320 (native)
    - Duration > 300s (5 min) → 192 to save traffic
    - Otherwise use default_br
    """
    if source == "yandex":
        return 320
    if duration and duration > 300:
        return min(default_br, 192)
    return default_br


async def _get_bot_setting(key: str, default: str) -> str:
    """Read admin-set setting from Redis (same keys as admin panel)."""
    val = await cache.redis.get(f"bot:setting:{key}")
    if val:
        return val if isinstance(val, str) else val.decode()
    return default

# session_id → {chat_id, user_msg_id, status_msg_id, created_at}
_group_sessions: dict[str, dict] = {}
_group_sessions_lock = asyncio.Lock()


async def _group_sessions_pop(session_id: str) -> dict | None:
    async with _group_sessions_lock:
        return _group_sessions.pop(session_id, None)


async def _schedule_group_cleanup(bot, session_id: str) -> None:
    """Delete search messages in group if no track selected within timeout."""
    await asyncio.sleep(_GROUP_CLEANUP_SEC)
    info = await _group_sessions_pop(session_id)
    if not info:
        return
    for mid in (info.get("status_msg_id"), info.get("user_msg_id")):
        if mid:
            try:
                await bot.delete_message(info["chat_id"], mid)
            except Exception:
                logger.debug("group cleanup delete msg=%s failed", mid, exc_info=True)


async def _cleanup_group_search(bot, session_id: str, results_msg: Message) -> None:
    """After track is selected in group: delete original message + search results."""
    info = await _group_sessions_pop(session_id)
    # Delete the search results message (the inline keyboard message)
    try:
        await results_msg.delete()
    except Exception:
        logger.debug("cleanup group search results delete failed", exc_info=True)
    if not info:
        return
    # Delete the original user message
    if info.get("user_msg_id"):
        try:
            await bot.delete_message(info["chat_id"], info["user_msg_id"])
        except Exception:
            logger.debug("cleanup group user msg delete failed", exc_info=True)


from bot.services.track_format import audio_tag_kwargs_from_info as _audio_tag_kwargs, format_track_line


def _audio_tags(track_info: dict) -> tuple[str, str]:
    """Clean performer/title for Telegram audio bubble."""
    kw = _audio_tag_kwargs(track_info)
    return kw["performer"], kw["title"]


# Bot @username, cached lazily (see _do_search) so the delivered-track caption can
# link back to the bot for discovery from group chats.
_BOT_USERNAME: str = ""


def _track_caption(lang: str, track_info: dict, bitrate: int, *, ad_free: bool = False) -> str:
    """Premium track card caption.

    The audio bubble already shows the performer — title from the file tags, so the
    caption does NOT repeat them. Instead the top line is the bot's name (a link to
    the bot), above the duration/bitrate:

    line1  ◇ BLACK ROOM            (links to the bot)
    line2  <code>3:42 · 192 kbps · 2019</code>
    """
    from bot.services.track_flair import track_extra_caption_lines

    dur = track_info.get("duration_fmt")
    if not dur and track_info.get("duration"):
        # Curated pins carry a raw duration but no pre-formatted string.
        try:
            dur = _fmt_duration(int(track_info["duration"]))
        except Exception:
            dur = None
    dur = dur or "?:??"
    year = track_info.get("upload_year")
    year_str = f" · {year}" if year else ""
    brand = t(lang, "track_brand_line")
    if _BOT_USERNAME:
        brand = f'<a href="https://t.me/{_BOT_USERNAME}">{brand}</a>'
    base = t(lang, "track_caption", duration=dur, bitrate=bitrate, year=year_str)
    body = f"{brand}\n{base}"
    # Rare per-track dedication flair (already carries the BLACK ROOM mark).
    extra = track_extra_caption_lines(lang, track_info)
    if extra:
        return f"{body}\n{extra}"
    return body


async def _ensure_caption_duration(track_info: dict) -> None:
    """Fill a missing duration from the Track row in Postgres before captioning.

    file_id deliveries skip the download, so the mutagen duration-read never runs;
    a curated pin / rcache entry with no duration then showed "?:??" in the caption
    while the audio bubble (from the file itself) showed the real length. The row
    is populated on first download, so a cached track almost always has it.
    """
    if track_info.get("duration_fmt") or track_info.get("duration"):
        return
    try:
        from sqlalchemy import select
        from bot.models.base import async_session
        from bot.models.track import Track
        async with async_session() as session:
            res = await session.execute(
                select(Track.duration).where(Track.source_id == track_info.get("video_id", ""))
            )
            dur = res.scalar_one_or_none()
        if dur:
            track_info["duration"] = int(dur)
            track_info["duration_fmt"] = _fmt_duration(int(dur))
    except Exception:
        logger.debug("caption duration lookup failed", exc_info=True)


def _is_ad_free(user) -> bool:
    """Check if user has ad-free (Premium, admin, or paid ad-free period)."""
    if user.is_premium or user.is_admin:
        return True
    from datetime import datetime, timezone as tz
    if user.ad_free_until and user.ad_free_until > datetime.now(tz.utc):
        return True
    return False


async def _fetch_tracks_for_lyrics_hints(
    lyric_hints: list[dict],
    *,
    search_yandex_fn,
    search_vk_fn,
    search_spotify_fn,
    search_yt_fn,
) -> list[dict]:
    """Resolve lyrics DB hits (Genius/Musixmatch) into playable track candidates."""
    hint_tracks: list[dict] = []
    seen_hint_queries: set[str] = set()

    for hint in lyric_hints:
        artist_hint = (hint.get("artist") or "").strip()
        title_hint = (hint.get("title") or "").strip()
        if not artist_hint or not title_hint:
            continue
        hint_query = f"{artist_hint} {title_hint}".strip()
        if hint_query in seen_hint_queries:
            continue
        seen_hint_queries.add(hint_query)

        try:
            hint_yandex, hint_vk, hint_spotify, hint_youtube = await asyncio.gather(
                asyncio.wait_for(search_yandex_fn(hint_query, limit=2), timeout=10),
                asyncio.wait_for(search_vk_fn(hint_query, limit=2), timeout=10),
                asyncio.wait_for(search_spotify_fn(hint_query, limit=2), timeout=10),
                asyncio.wait_for(search_yt_fn(hint_query, limit=2), timeout=10),
            )
        except Exception:
            logger.debug("lyrics hint provider search failed q=%r", hint_query[:60], exc_info=True)
            continue

        merged = (hint_yandex or []) + (hint_vk or []) + (hint_spotify or []) + (hint_youtube or [])
        for idx, track in enumerate(merged):
            track["_provider_pos"] = idx
            track["_score_query"] = hint_query
            track["_hint_bonus"] = 2.45 if idx == 0 else 1.75
            track["_from_lyrics"] = True
            hint_tracks.append(track)

    return hint_tracks


async def _fetch_lyric_fallback_tracks(
    query: str,
    parsed: dict,
    *,
    search_yandex_fn,
    search_vk_fn,
    search_yt_fn,
) -> list[dict]:
    """When lyrics DB is empty, search providers directly with lyric phrasing variants."""
    from bot.services.search_engine import (
        extract_distinctive_lyric_words,
        lyric_search_variants,
        normalize_query,
        _hint_word_in_title,
    )

    variants = lyric_search_variants(query, parsed)
    distinctive = extract_distinctive_lyric_words(query)
    fallback_tracks: list[dict] = []
    seen_ids: set[str] = set()

    for v_idx, variant in enumerate(variants[:4]):
        try:
            yandex, vk, youtube = await asyncio.gather(
                asyncio.wait_for(search_yandex_fn(variant, limit=3), timeout=10),
                asyncio.wait_for(search_vk_fn(variant, limit=3), timeout=10),
                asyncio.wait_for(search_yt_fn(variant, limit=2), timeout=10),
            )
        except Exception:
            logger.debug("lyric fallback search failed q=%r", variant[:60], exc_info=True)
            continue

        merged = (yandex or []) + (vk or []) + (youtube or [])
        for idx, track in enumerate(merged):
            vid = track.get("video_id", "")
            if vid and vid in seen_ids:
                continue
            title_n = normalize_query(track.get("title", ""))
            blob = f"{normalize_query(track.get('uploader', ''))} {title_n}"
            if distinctive and v_idx > 0:
                if not any(
                    _hint_word_in_title(w, title_n) or w in blob
                    for w in distinctive
                ):
                    continue
            if vid:
                seen_ids.add(vid)
            track["_provider_pos"] = idx
            track["_score_query"] = variant
            track["_hint_bonus"] = 1.55 if v_idx == 0 and idx == 0 else 1.25
            track["_from_lyric_fallback"] = True
            fallback_tracks.append(track)

    return fallback_tracks


async def _fetch_parsed_hint_tracks(
    parsed: dict,
    *,
    search_yandex_fn,
    search_vk_fn,
    search_spotify_fn,
    search_yt_fn,
    include_youtube: bool = True,
) -> list[dict]:
    """Targeted search for parsed artist + title (e.g. 'матранг' + 'рука')."""
    artist = (parsed.get("artist_hint") or "").strip()
    title = (parsed.get("title_hint") or "").strip()
    if not artist or not title:
        return []

    queries = [f"{artist} {title}", f"{artist} - {title}"]
    if detect_script(artist) == "cyrillic":
        lat_a = transliterate_cyr_to_lat(artist)
        lat_t = transliterate_cyr_to_lat(title)
        if lat_a and lat_t:
            queries.append(f"{lat_a} {lat_t}")

    hint_tracks: list[dict] = []
    seen_ids: set[str] = set()
    for q_idx, hint_query in enumerate(dict.fromkeys(queries)):
        try:
            yandex_coro = asyncio.wait_for(search_yandex_fn(hint_query, limit=3), timeout=10)
            vk_coro = asyncio.wait_for(search_vk_fn(hint_query, limit=3), timeout=10)
            spotify_coro = asyncio.wait_for(search_spotify_fn(hint_query, limit=3), timeout=10)
            if include_youtube:
                youtube_coro = asyncio.wait_for(search_yt_fn(hint_query, limit=3), timeout=8)
                yandex, vk, spotify, youtube = await asyncio.gather(
                    yandex_coro, vk_coro, spotify_coro, youtube_coro,
                )
            else:
                yandex, vk, spotify = await asyncio.gather(
                    yandex_coro, vk_coro, spotify_coro,
                )
                youtube = []
        except Exception:
            logger.debug("parsed hint search failed q=%r", hint_query[:60], exc_info=True)
            continue

        merged = (yandex or []) + (vk or []) + (spotify or []) + (youtube or [])
        for idx, track in enumerate(merged):
            vid = track.get("video_id", "")
            if vid and vid in seen_ids:
                continue
            if vid:
                seen_ids.add(vid)
            track["_provider_pos"] = idx
            track["_hint_bonus"] = 1.35 if q_idx == 0 and idx == 0 else 1.15
            track["_from_parsed_hint"] = True
            hint_tracks.append(track)

    return hint_tracks


def _filter_lyric_hints_for_artist(lyric_hints: list[dict], artist_hint: str) -> list[dict]:
    """Prefer lyrics DB hits whose artist matches the parsed artist hint."""
    if not artist_hint or not lyric_hints:
        return lyric_hints
    from bot.services.search_engine import _token_set_sim

    ah = normalize_query(artist_hint)
    matched = [
        h for h in lyric_hints
        if _token_set_sim(ah, normalize_query(h.get("artist", ""))) >= 0.65
        or ah in normalize_query(h.get("artist", ""))
    ]
    return matched or lyric_hints


_SEARCH_LOGO = "\u25c9 <b>BLACK ROOM</b>"


_SOURCE_BADGE = {
    "yandex": "YM",
    "vk": "VK",
    "soundcloud": "SC",
    "youtube": "YT",
    "spotify": "SP",
}


def _result_row_label(track: dict, *, checked: bool = False) -> str:
    """Compact result row: '✓ ▸ [YM] Artist — Title · 3:42' with safe access."""
    check = "✓ " if checked else ""
    badge = _SOURCE_BADGE.get(track.get("source", ""))
    badge_str = f"[{badge}] " if badge else ""
    artist = (track.get("uploader") or "").strip()
    title = (track.get("title") or "").strip()
    if artist and title:
        name = f"{artist} — {title}"
    else:
        name = artist or title or "?"
    if len(name) > 44:
        name = name[:43].rstrip() + "…"
    dur = (track.get("duration_fmt") or "").strip()
    tail = f" · {dur}" if dur else ""
    return f"{check}▸ {badge_str}{name}{tail}"


def _build_results_keyboard(
    results: list[dict],
    session_id: str,
    picked: set[int] | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    for i, track in enumerate(results):
        buttons.append(
            [InlineKeyboardButton(
                text=_result_row_label(track, checked=bool(picked and i in picked)),
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _direct_hit_present(
    results: list[dict], provider_query: str, top_k: int = 3, thresh: float = 0.8
) -> bool:
    """True when a top result already contains (nearly) all query words in its
    artist+title — i.e. we have a confident direct match and don't need the
    lyric-resolution machinery, which would only add noise + ~12s latency.

    E.g. "9 грамм Дэнс" already has "9 грамм — Дэнс" at #1; without this guard a
    lyric fallback injects "9 грамм свинца" (wrong artist) and it can win ranking.
    Only short-circuits when the answer is demonstrably already in hand, so it
    never reduces recall for genuine lyric fragments (whose words are NOT all
    present in any single result's artist+title before the boost runs).
    """
    pq_words = set(normalize_query(provider_query).split())
    if not pq_words:
        return False
    for r in results[:top_k]:
        at = set(normalize_query(f"{r.get('uploader','')} {r.get('title','')}").split())
        if len(pq_words & at) / len(pq_words) >= thresh:
            return True
    return False


def _group_pick_score(
    track: dict,
    *,
    provider_query: str,
    parsed_query: dict,
    source_rank: dict[str, int],
) -> float:
    """Unified relevance score for group auto-play (matches dedup + lyrics hints)."""
    pq_norm = normalize_query(provider_query)
    score_q = track.get("_score_query") or pq_norm
    parsed = parsed_query
    if track.get("_from_lyrics") or track.get("_from_lyric_fallback"):
        parsed = None
    rel = _relevance_score(
        score_q,
        track.get("uploader", ""),
        track.get("title", ""),
        position=track.get("_provider_pos", 5),
        parsed=parsed,
    )
    rel += float(track.get("_hint_bonus", 0.0))
    if track.get("_from_lyrics"):
        rel += 0.4
    if track.get("source") != "youtube":
        rel += 0.35
    if track.get("file_id"):
        rel += min(0.18, 0.05 + track.get("_downloads", 0) / 250)
    rel += source_rank.get(track.get("source", ""), 0) * 0.01
    # Named-artist match: if the result's (multi-word) artist name appears in full
    # in the query, the user explicitly named that artist — that dominates. This
    # also shields such results from the title-hint penalty below, which mishandles
    # multi-word artist names (e.g. "Клава Кока" mis-parsed as artist="клава", which
    # wrongly crushed "Клава Кока — ЛА ЛА ЛА" while promoting a same-titled "Душный"
    # by a different artist).
    _a_tokens = [t for t in normalize_query(track.get("uploader", "")).split() if len(t) >= 3]
    _strong_artist = len(_a_tokens) >= 2 and all(t in pq_norm.split() for t in _a_tokens)
    if _strong_artist:
        rel += 2.0
    if not _strong_artist and parsed_query.get("artist_hint") and parsed_query.get("title_hint"):
        tc = query_title_hint_coverage(pq_norm, track.get("title", ""), parsed_query)
        if tc >= 0.5:
            rel += 0.75 + tc * 0.45
        elif tc < 0.3:
            rel *= 0.12
    return rel


def _group_play_queue(
    results: list[dict],
    *,
    provider_query: str,
    parsed_query: dict,
    source_rank: dict[str, int],
    best: dict | None = None,
    max_tries: int = 5,
) -> list[dict]:
    """Order group download attempts by relevance; drop obvious title mismatches."""
    ranked = _group_relevance_rank(
        results,
        provider_query=provider_query,
        parsed_query=parsed_query,
        source_rank=source_rank,
    )
    ordered = [t for t, _ in ranked]
    if best is not None:
        best_vid = best.get("video_id")
        ordered = [best] + [t for t in ordered if t.get("video_id") != best_vid]

    if parsed_query.get("title_hint"):
        pq_norm = normalize_query(provider_query)

        def _title_cov(t: dict) -> float:
            return query_title_hint_coverage(pq_norm, t.get("title", ""), parsed_query)

        title_ok = [
            t for t in ordered
            if t.get("_curated") or _title_cov(t) >= 0.35
        ]
        if title_ok:
            ordered = title_ok
        else:
            # No strong match — still prefer best title overlap over random Yandex #1
            ordered = sorted(ordered, key=_title_cov, reverse=True)
            ordered = [t for t in ordered if _title_cov(t) > 0] or ordered[:1]
        if best is not None and all(t.get("video_id") != best.get("video_id") for t in ordered):
            ordered = [best] + ordered

    # Dead YouTube proxy: don't burn 30s×N on uncached yt downloads when YM/VK exist
    non_yt = [
        t for t in ordered
        if t.get("source") != "youtube" or t.get("file_id")
    ]
    if non_yt:
        ordered = non_yt

    return ordered[:max_tries]


def _group_relevance_rank(
    results: list[dict],
    *,
    provider_query: str,
    parsed_query: dict,
    source_rank: dict[str, int],
) -> list[tuple[dict, float]]:
    """Rank group candidates by relevance (lyrics hints, parsed artist/title, source)."""
    ranked = [
        (r, _group_pick_score(r, provider_query=provider_query, parsed_query=parsed_query, source_rank=source_rank))
        for r in results
    ]
    # If the query names an artist (a candidate's full multi-word artist name appears
    # in the query), keep ONLY that artist's tracks — the user explicitly asked for
    # that artist, so a same-titled track by someone else must never win (e.g.
    # "Клава кока душный" must return Клава Кока, never another artist's "Душный").
    # If that artist has no title match, their top track wins.
    _pq_tok = set(normalize_query(provider_query).split())

    def _artist_named(t: dict) -> bool:
        _at = [x for x in normalize_query(t.get("uploader", "")).split() if len(x) >= 3]
        return len(_at) >= 2 and all(x in _pq_tok for x in _at)

    _artist_only = [item for item in ranked if _artist_named(item[0])]
    if _artist_only:
        ranked = _artist_only
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _group_choice_needed(ranked: list[tuple[dict, float]]) -> bool:
    """Groups always auto-play — no inline choice menu in chats."""
    return False


def _build_group_choice_keyboard(session_id: str, results: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, track in enumerate(results[:3]):
        title = (track.get("title") or "")[:34]
        artist = (track.get("uploader") or "")[:24]
        duration = track.get("duration_fmt") or "?:??"
        buttons.append([
            InlineKeyboardButton(
                text=f"{i + 1}. {artist} — {title} ({duration})",
                callback_data=WrongTrackPickCb(sid=session_id, i=i).pack(),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _do_search(message: Message, query: str) -> None:
    try:
        user = await get_or_create_user(message.from_user)
    except Exception:
        await message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return
    lang = user.language

    if user.is_banned:
        return

    global _BOT_USERNAME
    if not _BOT_USERNAME:
        try:
            _BOT_USERNAME = (await message.bot.me()).username or ""
        except Exception:
            pass

    # Strip the bot's own @mention anywhere in the query — private-chat users
    # tapping the @bot autocomplete produced queries like "@TSmymusicbot_bot
    # песня" that went to providers verbatim (12 garbage searches in the audit).
    if _BOT_USERNAME and "@" in query:
        _q2 = _re.sub(rf"@{_re.escape(_BOT_USERNAME)}\b", " ", query, flags=_re.IGNORECASE)
        _q2 = _re.sub(r"\s+", " ", _q2).strip()
        if _q2 != query.strip():
            query = _q2
            if not query:
                return

    is_group = message.chat.type in ("group", "supergroup")
    # Groups: only Yandex/Spotify links and text search — no YouTube URLs
    if is_group and is_youtube_url(query):
        return

    from bot.services.search_curated import is_junk_search_query
    if is_junk_search_query(query):
        return

    # Admins bypass rate limits
    if message.from_user.id not in settings.ADMIN_IDS:
        allowed, cooldown = await cache.check_rate_limit(
            message.from_user.id, is_premium=user.is_premium
        )
        if not allowed:
            if cooldown > 0:
                await message.answer(t(lang, "rate_limit_cooldown", seconds=cooldown))
            else:
                await message.answer(t(lang, "rate_limit_exceeded"))
            return

    # Yandex ALBUM link → send the whole album (capped), track by track.
    from bot.services.yandex_provider import is_yandex_album_url, resolve_yandex_album, yandex_album_id_from_url
    if is_yandex_album_url(query):
        _alb_id = yandex_album_id_from_url(query)
        status = await message.answer("💿 Собираю альбом…")
        _alb_cap = 5 if is_group else 10
        _alb_title, _alb_tracks = await resolve_yandex_album(_alb_id, limit=_alb_cap)
        if not _alb_tracks:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="yandex"
        )
        try:
            await status.edit_text(
                f"💿 <b>{html.escape(_alb_title)}</b>\nОтправляю {len(_alb_tracks)} трек(ов)…",
                parse_mode="HTML",
            )
        except Exception:
            pass
        _sent_n = 0
        for _ti in _alb_tracks:
            try:
                if await _send_album_track(message, user, _ti):
                    _sent_n += 1
            except Exception:
                logger.debug("album track send failed", exc_info=True)
            await asyncio.sleep(2)  # Telegram flood control
        try:
            if _sent_n:
                await status.edit_text(
                    f"💿 <b>{html.escape(_alb_title)}</b> — {_sent_n}/{len(_alb_tracks)} ✓",
                    parse_mode="HTML",
                )
            else:
                await status.edit_text(t(lang, "error_download"))
        except Exception:
            pass
        return

    # Unsupported link (Instagram/TikTok/VK video/…) → friendly hint instead of
    # a garbage text search (the audit found reels/shorts links returning random
    # tracks after a full 200s search).
    _q_low = query.strip().lower()
    if _q_low.startswith(("http://", "https://")) and not (
        is_spotify_url(query) or is_yandex_music_url(query) or is_youtube_url(query)
    ):
        await message.answer(
            "⚠️ Такие ссылки я пока не понимаю.\n"
            "Пришли <b>название трека</b> или ссылку на "
            "Яндекс.Музыку / Spotify / YouTube.",
            parse_mode="HTML",
        )
        return

    # Spotify link → resolve via Spotify API, show track directly
    if is_spotify_url(query):
        status = await message.answer(t(lang, "spotify_detected"))
        track_info = await resolve_spotify_url(query)
        if not track_info:
            # API credentials down (403 since sub lapsed) → resolve the link via
            # the PUBLIC embed/oEmbed pages to artist+title, then serve the track
            # from our own providers (Yandex). Keeps Spotify links working with
            # zero Spotify credentials — the SpotSeek flow, legally cleaner.
            try:
                from bot.services.spotify_provider import resolve_spotify_link_public
                _at = await resolve_spotify_link_public(query)
            except Exception:
                _at = None
            if _at:
                _sp_q = f"{_at[0]} {_at[1]}".strip()
                logger.info("spotify link public-resolved -> %r", _sp_q)
                try:
                    _sp_batch = await asyncio.wait_for(search_yandex(_sp_q, limit=3), timeout=8)
                except Exception:
                    _sp_batch = []
                if _sp_batch:
                    track_info = _sp_batch[0]
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="spotify"
        )
        requests_total.labels(source="spotify").inc()
        if is_group:
            await _group_auto_play(message, status, user, track_info)
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ Spotify\n"
                f"♪ <b>{html.escape(track_info['uploader'])} — {html.escape(track_info['title'])}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    # Yandex Music link → fetch track directly, skip search
    elif is_yandex_music_url(query):
        status = await message.answer(t(lang, "yandex_link_detected"))
        track_info = await resolve_yandex_url(query)
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="yandex"
        )
        requests_total.labels(source="yandex").inc()
        if is_group:
            try:
                await _group_auto_play(message, status, user, track_info, raise_on_error=True)
            except Exception as dl_err:
                failed_ym = track_info.get("ym_track_id")
                logger.warning(
                    "Yandex link auto-play failed ym=%s: %s — provider fallback",
                    failed_ym, dl_err,
                )
                fallback_q = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
                alt: dict | None = None
                if fallback_q:
                    for batch in (
                        await search_yandex(fallback_q, limit=5) or [],
                        await search_vk(fallback_q, limit=3) or [],
                    ):
                        for cand in batch:
                            if cand.get("ym_track_id") == failed_ym:
                                continue
                            if cand.get("video_id") == track_info.get("video_id"):
                                continue
                            alt = cand
                            break
                        if alt:
                            break
                if alt:
                    try:
                        await status.edit_text(t(lang, "downloading"))
                    except Exception:
                        pass
                    await _group_auto_play(message, status, user, alt, raise_on_error=False)
                else:
                    try:
                        await status.edit_text(t(lang, "error_download"))
                    except Exception:
                        pass
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ Яндекс.Музыка\n"
                f"♪ <b>{html.escape(track_info['uploader'])} — {html.escape(track_info['title'])}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    # YouTube link → resolve metadata, download directly
    elif is_youtube_url(query):
        video_id = extract_youtube_video_id(query)
        if not video_id:
            return
        status = await message.answer(t(lang, "youtube_link_detected"))
        track_info = await resolve_youtube_url(video_id)
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="youtube"
        )
        requests_total.labels(source="youtube").inc()
        if is_group:
            await _group_auto_play(message, status, user, track_info)
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ YouTube\n"
                f"♪ <b>{html.escape(track_info['uploader'])} — {html.escape(track_info['title'])}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    else:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        status = await message.answer(t(lang, "searching"))

    _search_t0 = time.monotonic()
    # Global wall-clock budget for the ENRICHMENT phases (aliases, canonical,
    # genius, translit, speller, parsed hints, lyric boost). Individually each has
    # an 8-12s timeout, but they run sequentially — with dead providers the waves
    # stacked to 95-230s (June audit: p90 96s, 18% of searches ≥60s, users left).
    # The primary provider gather is NOT budgeted — core search always completes;
    # the budget only stops piling fallback waves on top of it.
    _search_budget = 12.0

    def _budget_left() -> float:
        return _search_budget - (time.monotonic() - _search_t0)
    if is_group:
        max_results = _MAX_RESULTS_GROUP
    else:
        max_results = int(await _get_bot_setting("max_results", "10"))

    parsed_query = parse_query(query)
    provider_query = parsed_query.get("clean") or parsed_query.get("original") or query

    # STEP 1: Search local DB (TEQUILA / FULLMOON channels + cached tracks)
    local_tracks = await search_local_tracks(provider_query, limit=max_results)
    local_results = []
    for tr in (local_tracks or []):
        local_results.append({
            "video_id": tr.source_id,
            "title": tr.title or "Unknown",
            "uploader": tr.artist or "Unknown",
            "duration": tr.duration or 0,
            "duration_fmt": _fmt_duration(tr.duration) if tr.duration else "?:??",
            "source": tr.source or "channel",
            "file_id": tr.file_id,
            "_downloads": tr.downloads or 0,
        })

    # ── Tier 0: instant answers that bypass the whole provider engine ──
    # A repeat query (cached ranked results), a curated/learned pin, or a local-DB
    # top hit that already covers the FULL query and has a ready file_id — deliver
    # these with no external provider call. Escalates to the full engine when not
    # confident, so match quality is never reduced.
    _norm_q = normalize_query(provider_query)
    _tier0: list[dict] | None = None
    try:
        # Curated pins are explicit human curation — they outrank a cached result,
        # so a newly added pin takes effect immediately instead of being shadowed
        # by a stale rcache entry for up to RCACHE_TTL. Free (in-process dict).
        from bot.services.search_curated import curated_track_for_query
        from bot.services.search_memory import get_learned_track as _get_learned
        _pin0 = curated_track_for_query(query) or curated_track_for_query(provider_query)
        if _pin0 and _pin0.get("video_id"):
            _tier0 = [_pin0]
        if _tier0 is None:
            _rc = await cache.get_result_cache(_norm_q)
            if _rc:
                _tier0 = _rc
        if _tier0 is None:
            _pin0 = await _get_learned(provider_query)
            if _pin0 and _pin0.get("video_id"):
                _tier0 = [_pin0]
            elif local_results and local_results[0].get("file_id"):
                _qtok = set(_norm_q.split())
                _lt0 = local_results[0]
                _ltok = set(normalize_query(f"{_lt0.get('uploader','')} {_lt0.get('title','')}").split())
                if _qtok and all(w in _ltok for w in _qtok):
                    _tier0 = local_results
    except Exception:
        logger.debug("tier0 check failed", exc_info=True)
    _skip_engine = _tier0 is not None
    if _skip_engine:
        logger.info("search: tier0 hit q=%r n=%d", provider_query[:60], len(_tier0 or []))

    # STEP 2: Parallel external search — Yandex + Spotify + SoundCloud + VK + YouTube
    async def _search_source(source: str, search_fn, limit: int) -> list[dict]:
        """Search a single source with cache and 12s timeout."""
        t0 = time.monotonic()
        try:
            cached = await cache.get_query_cache(provider_query, source)
            if cached is not None:
                # Cache hit — do NOT record a provider success event (no real call made)
                return cached
            res = await asyncio.wait_for(search_fn(provider_query, limit=limit), timeout=8)
            elapsed = time.monotonic() - t0
            record_provider_event(source, "search", elapsed, True)
            if res:
                await cache.set_query_cache(provider_query, res, source)
                requests_total.labels(source=source).inc()
            return res or []
        except Exception as exc:
            elapsed = time.monotonic() - t0
            record_provider_event(source, "search", elapsed, False, str(exc))
            logger.debug("search source %s failed", source, exc_info=True)
            return []

    async def _search_sc(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="soundcloud")

    async def _search_yt(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="youtube")

    lyric_like = is_lyric_like_query(provider_query, parsed_query)
    lyrics_task = None
    if not _skip_engine and (lyric_like or len(provider_query.split()) >= 3):
        async def _lyrics_lookup() -> list[dict]:
            try:
                from bot.services.lyrics_provider import search_by_lyrics
                return await asyncio.wait_for(
                    search_by_lyrics(provider_query, limit=3),
                    timeout=10,
                )
            except Exception:
                logger.debug("parallel lyrics search failed", exc_info=True)
                return []

        lyrics_task = asyncio.create_task(_lyrics_lookup())

    from bot.services.search_engine import detect_script, transliterate_cyr_to_lat, transliterate_lat_to_cyr, get_query_search_aliases

    all_results: list[dict] = []
    if _skip_engine:
        all_results = list(_tier0 or [])
    else:
        tasks = [
            _search_source("yandex", search_yandex, max_results),
            _search_source("spotify", search_spotify, max_results),
            _search_source("vk", search_vk, max_results),
        ]
        if not is_group:
            tasks.extend([
                _search_source("soundcloud", _search_sc, max_results),
                _search_source("youtube", _search_yt, max_results),
            ])
        source_results = await asyncio.gather(*tasks)
        for batch in source_results:
            all_results.extend(batch)

    for alias_q in ([] if _skip_engine else get_query_search_aliases(provider_query)):
        if _budget_left() <= 0:
            break
        alias_batch = await _search_source(
            "yandex",
            lambda q, limit, aq=alias_q: search_yandex(aq, limit=limit),
            max_results,
        )
        all_results.extend(alias_batch)

    # Query understanding: when iTunes AND Deezer independently agree on the same
    # "Artist - Title", we have a confident canonical for a vague/misspelled query
    # (e.g. "мокрые кросы" -> "Тима Белорусских - Мокрые кроссы"). Search Yandex for
    # it so the intended track is in the pool; a post-dedup boost then promotes it.
    # No cross-source agreement -> canon is None -> search is left untouched (so this
    # can only help, never regress). Cheap: cached resolve + one fast Yandex call.
    canonical_query: str | None = None
    if not _skip_engine and _budget_left() > 0:
        try:
            from bot.services.canonical_resolver import resolve_canonical
            canonical_query = await resolve_canonical(provider_query)
        except Exception:
            canonical_query = None
    if canonical_query and normalize_query(canonical_query) != normalize_query(provider_query) and _budget_left() > 0:
        try:
            canon_batch = await asyncio.wait_for(
                search_yandex(canonical_query, limit=max_results),
                timeout=min(8, max(1, _budget_left())),
            )
            all_results.extend(canon_batch)
        except Exception:
            logger.debug("canonical yandex search failed for %r", canonical_query, exc_info=True)

    # Lyric fragment ("words from a song") -> resolve the song via Genius, then
    # search providers for it so the pool holds the intended track (raw providers
    # can't match a lyric line to a title). Only for lyric-like queries with a
    # Genius token; the resolved title is boosted after dedup. Fails soft.
    lyric_song: tuple[str, str] | None = None
    if (
        not _skip_engine and len(provider_query.split()) >= 4
        and settings.GENIUS_ACCESS_TOKEN and _budget_left() > 1
    ):
        try:
            from bot.services.canonical_resolver import resolve_lyric_song
            lyric_song = await resolve_lyric_song(provider_query)
        except Exception:
            lyric_song = None
        if lyric_song:
            _lartist, _ltitle = lyric_song
            for _lq in (f"{_lartist} {_ltitle}", _ltitle):
                if _budget_left() <= 0:
                    break
                try:
                    _lb = await asyncio.wait_for(
                        search_yandex(_lq, limit=max_results),
                        timeout=min(8, max(1, _budget_left())),
                    )
                    all_results.extend(_lb)
                except Exception:
                    logger.debug("lyric-resolved yandex search failed", exc_info=True)

    # A-05: If few results and query is mono-language, try transliterated search
    if len(all_results) < 3 and not _skip_engine and _budget_left() > 0:
        script = detect_script(provider_query)
        alt_query = None
        if script == "cyrillic":
            alt_query = transliterate_cyr_to_lat(provider_query)
        elif script == "latin":
            alt_query = transliterate_lat_to_cyr(provider_query)
        if alt_query and alt_query != provider_query:
            alt_tasks = [
                _search_source("yandex", lambda q, limit=5: search_yandex(alt_query, limit=limit), max_results),
            ]
            if not is_group:
                alt_tasks.insert(
                    0,
                    _search_source("youtube", lambda q, limit=5: search_tracks(alt_query, max_results=limit, source="youtube"), max_results),
                )
            alt_results = await asyncio.gather(*alt_tasks)
            for batch in alt_results:
                all_results.extend(batch)

    # Spell-correction fallback: typos in the query → poor provider hits.
    # Only triggered when results are weak, to keep latency low.
    if len(all_results) < 3 and not _skip_engine and _budget_left() > 0:
        try:
            from bot.services.speller import correct_query
            corrected = await correct_query(provider_query)
        except Exception:
            corrected = None
        if corrected and normalize_query(corrected) != normalize_query(provider_query):
            logger.info("search: spell-corrected %r -> %r", provider_query, corrected)
            spell_tasks = [
                _search_source("yandex", lambda q, limit=5: search_yandex(corrected, limit=limit), max_results),
            ]
            if not is_group:
                spell_tasks.append(
                    _search_source("youtube", lambda q, limit=5: search_tracks(corrected, max_results=limit, source="youtube"), max_results),
                )
            spell_results = await asyncio.gather(*spell_tasks)
            for batch in spell_results:
                all_results.extend(batch)

    # Merge local + external results, then deduplicate
    all_results = local_results + all_results

    from bot.services.search_curated import inject_curated_track
    all_results = inject_curated_track(all_results, provider_query)

    # Deduplicate across sources (language-aware ranking)
    script = detect_script(provider_query)
    results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:max_results] if all_results else []

    # Parsed artist+title / lyrics enrichment when top-1 is weak.
    lyric_hints: list[dict] = []
    if lyrics_task is not None:
        try:
            lyric_hints = await lyrics_task
        except Exception:
            lyric_hints = []

    extra_tracks: list[dict] = []
    top_track = results[0] if results else None
    if parsed_query.get("artist_hint") and parsed_query.get("title_hint"):
        title_cov = (
            query_title_hint_coverage(
                normalize_query(provider_query),
                top_track.get("title", ""),
                parsed_query,
            )
            if top_track else 0.0
        )
        # Skip when the top result already covers the whole query (nothing to fix)
        # or the budget is spent. Previously unbounded (up to 3 queries × 10s) and
        # ALWAYS ran for groups — a major part of the 95s+ June latency disaster.
        if (
            (is_group or title_cov < 0.85) and not _skip_engine
            and _budget_left() > 1
            and not _direct_hit_present(results, provider_query)
        ):
            try:
                extra_tracks.extend(
                    await asyncio.wait_for(
                        _fetch_parsed_hint_tracks(
                            parsed_query,
                            search_yandex_fn=search_yandex,
                            search_vk_fn=search_vk,
                            search_spotify_fn=search_spotify,
                            search_yt_fn=_search_yt,
                            include_youtube=not is_group,
                        ),
                        timeout=max(2, min(10, _budget_left())),
                    )
                )
            except Exception:
                logger.debug("parsed-hint fetch timed out/failed", exc_info=True)

    _has_artist_title = bool(
        parsed_query.get("artist_hint") and parsed_query.get("title_hint")
    )
    _run_lyrics_boost = (not _skip_engine) and _budget_left() > 2 and (needs_lyrics_search_boost(
        provider_query, top_track, parsed=parsed_query
    ) or (is_group and lyric_like and not _has_artist_title))

    # An artist-named query (e.g. "Клава Кока душный") is NOT a lyric fragment: if
    # any top result's full multi-word artist appears in the query, skip the lyric
    # boost — it wrongly injects same-titled wrong-artist tracks (the "Душный" bug)
    # and calls the slow lyric providers (a stuck one froze search ~24s).
    if _run_lyrics_boost and results:
        _pq_tok = set(normalize_query(provider_query).split())
        for _r in results[:5]:
            _at = [t for t in normalize_query(_r.get("uploader", "")).split() if len(t) >= 3]
            if len(_at) >= 2 and all(t in _pq_tok for t in _at):
                _run_lyrics_boost = False
                break

    # Confident direct hit already in the pool → skip the lyric machinery entirely
    # (it would only add a wrong-track and ~12s latency). See _direct_hit_present.
    if _run_lyrics_boost and _direct_hit_present(results, provider_query):
        logger.info("search: skip lyric boost — direct hit for %r", provider_query[:60])
        _run_lyrics_boost = False

    if _run_lyrics_boost:
        # The lyric-verify machinery (verify pool + per-candidate lyric fetches +
        # provider fallback) is otherwise unbounded and has hung searches for 2+
        # minutes when the lyric providers are slow/rate-limited. Wrap the WHOLE
        # boost in a single hard deadline so it can never dominate a search.
        async def _run_lyric_boost() -> list[dict]:
            _hints = lyric_hints
            if not _hints:
                try:
                    from bot.services.lyrics_provider import search_by_lyrics
                    _hints = await search_by_lyrics(provider_query, limit=3)
                except Exception:
                    _hints = []
            _hints = _filter_lyric_hints_for_artist(_hints, parsed_query.get("artist_hint") or "")

            # LRCLib's catalog is a purpose-built lyric->song index and is far
            # cleaner than the word-overlap verify pool (which matched the fragment
            # "восьмиклассница ну кто же виноват" to "Кто же виноват" instead of
            # Кино — "Восьмиклассница"). Try it BEFORE the noisy pool.
            if not _hints:
                try:
                    from bot.services.lyrics_provider import search_lrclib_catalog
                    _hints = _filter_lyric_hints_for_artist(
                        await search_lrclib_catalog(provider_query, limit=3) or [],
                        parsed_query.get("artist_hint") or "",
                    )
                    if _hints:
                        logger.info(
                            "search: LRCLib catalog q=%r hits=%s", provider_query[:60],
                            [f"{h.get('artist')} - {h.get('title')}" for h in _hints[:2]],
                        )
                except Exception:
                    logger.debug("LRCLib catalog lookup failed", exc_info=True)

            if not _hints and all_results:
                try:
                    from bot.services.lyrics_provider import (
                        gather_lyric_verify_pool,
                        resolve_lyrics_from_candidates,
                    )
                    verify_pool = await gather_lyric_verify_pool(
                        provider_query, all_results[:25],
                        search_yandex_fn=search_yandex, search_vk_fn=search_vk,
                        parsed=parsed_query,
                    )
                    _hints = await resolve_lyrics_from_candidates(provider_query, verify_pool, limit=3)
                    if _hints:
                        logger.info(
                            "search: LRCLib verified q=%r hits=%s", provider_query[:60],
                            [f"{h.get('artist')} - {h.get('title')}" for h in _hints[:2]],
                        )
                except Exception:
                    logger.debug("LRCLib candidate verify failed", exc_info=True)

            if _hints:
                logger.info(
                    "search: lyrics boost q=%r hints=%s top=%s", provider_query[:60],
                    [f"{h.get('artist')} - {h.get('title')}" for h in _hints[:2]],
                    f"{top_track.get('uploader')} - {top_track.get('title')}" if top_track else "none",
                )
                return await _fetch_tracks_for_lyrics_hints(
                    _hints, search_yandex_fn=search_yandex, search_vk_fn=search_vk,
                    search_spotify_fn=search_spotify, search_yt_fn=_search_yt,
                )
            logger.info("search: lyrics DB empty, provider fallback q=%r", provider_query[:60])
            return await _fetch_lyric_fallback_tracks(
                provider_query, parsed_query,
                search_yandex_fn=search_yandex, search_vk_fn=search_vk, search_yt_fn=_search_yt,
            )

        try:
            extra_tracks.extend(await asyncio.wait_for(
                _run_lyric_boost(), timeout=max(2, min(12, _budget_left())),
            ))
        except Exception:
            logger.debug("lyric boost timed out/failed for %r", provider_query[:60], exc_info=True)

    if extra_tracks:
        all_results.extend(extra_tracks)
        results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:max_results]

    # Promote the confident canonical track to #1 when it is present in the results,
    # so a vague/misspelled query lands on the intended song. Only fires when iTunes
    # and Deezer agreed (canonical_query set) AND a result matches it by artist+title;
    # otherwise ranking is left exactly as-is (no regression).
    if canonical_query and results:
        try:
            from bot.services.canonical_resolver import canonical_match_index
            _bi = canonical_match_index(results, canonical_query)
            if _bi is not None and _bi > 0:
                results.insert(0, results.pop(_bi))
        except Exception:
            logger.debug("canonical boost failed", exc_info=True)

    # Promote the Genius-resolved song (by title) for a lyric-fragment query, so
    # "words from a song" lands on the track. Title-only match (artist may be a
    # cover). Only fires when a lyric song was resolved. NOTE: this reorders the
    # result list but does NOT force the group pick — a Genius resolve alone is too
    # unreliable to override _group_relevance_rank (force-pinning it regressed
    # artist+title queries and lyrics where Genius guessed wrong).
    if lyric_song and results and not _direct_hit_present(results, provider_query):
        try:
            from bot.services.canonical_resolver import canonical_match_index, title_match_index
            _la, _lt = lyric_song
            # Prefer an artist+title match (Genius artist correct, e.g. Звери);
            # fall back to title-only (Genius gave a cover artist, e.g. IOWA).
            _li = canonical_match_index(results, f"{_la} {_lt}")
            if _li is None:
                _li = title_match_index(results, _lt)
            if _li is not None and _li > 0:
                results.insert(0, results.pop(_li))
        except Exception:
            logger.debug("lyric boost failed", exc_info=True)

    # DMCA filter: remove blocked tracks, show appeal button if any were blocked
    blocked_count = 0
    if results:
        from bot.services.dmca_filter import filter_blocked, is_blocked
        before_count = len(results)
        # Find the first blocked track for the appeal button
        blocked_source_id = None
        for r in results:
            if is_blocked(r.get("video_id", "")):
                blocked_source_id = r.get("video_id", "")
                break
        results = filter_blocked(results)
        blocked_count = before_count - len(results)

    if not results:
        # Log the miss BEFORE returning — zero-result searches are exactly what the
        # audit exists to catch, but the main audit write sits below this return,
        # so every hard miss used to vanish from the log (June audit blind spot).
        try:
            _miss_audit = _json.dumps({
                "t": "search", "ts": int(time.time()), "uid": user.id,
                "grp": is_group, "q": query[:300], "pq": provider_query[:300],
                "n": 0, "top1": "", "top1_sc": 0.0, "src": [],
                "ms": int((time.monotonic() - _search_t0) * 1000),
            }, ensure_ascii=False)
            await cache.redis.lpush("search:audit", _miss_audit)
            await cache.redis.ltrim("search:audit", 0, 49999)
        except Exception:
            logger.debug("miss audit log failed", exc_info=True)
        # TASK-012: "Did you mean?" suggestions
        try:
            corpus = await get_popular_titles(limit=500)
            suggestions = suggest_query(query, corpus, max_suggestions=1)
        except Exception:
            suggestions = []
        if suggestions:
            sug = suggestions[0]
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f'🔍 "{sug}"', switch_inline_query_current_chat=sug),
            ]])
            await status.edit_text(
                f"{t(lang, 'no_results')}\n\n💡 {t(lang, 'did_you_mean')}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            await status.edit_text(t(lang, "no_results"))
        return

    await record_listening_event(
        user_id=user.id, query=query[:500], action="search", source="search"
    )

    # ── Search audit log ──────────────────────────────────────────────────
    try:
        _search_ms = int((time.monotonic() - _search_t0) * 1000)
        _top1 = results[0] if results else {}
        _top1_score = 0.0
        if _top1:
            _top1_score = round(_relevance_score(
                normalize_query(provider_query),
                _top1.get("uploader", ""),
                _top1.get("title", ""),
                position=_top1.get("_provider_pos", 5),
            ), 3)
        _src_set = list({r.get("source", "?") for r in results})
        _audit = _json.dumps({
            "t": "search",
            "ts": int(time.time()),
            "uid": user.id,
            "grp": is_group,
            "q": query[:300],
            "pq": provider_query[:300],
            "n": len(results),
            "top1": f"{_top1.get('uploader', '')} - {_top1.get('title', '')}" if _top1 else "",
            "top1_sc": _top1_score,
            "src": _src_set,
            "ms": _search_ms,
        }, ensure_ascii=False)
        await cache.redis.lpush("search:audit", _audit)
        await cache.redis.ltrim("search:audit", 0, 49999)
    except Exception:
        logger.debug("search audit log failed", exc_info=True)

    # Tag every result with the originating query so downstream handlers
    # (e.g. "🔁 Не тот трек?") can learn the correct track for this query.
    for _r in results:
        _r["_query"] = query

    # Self-improving search: pin the track previously confirmed correct for this
    # query (learned from "🔁 Не тот трек?" picks) to the top of results.
    _learned_pin = None
    try:
        from bot.services.search_memory import get_learned_track
        from bot.services.search_curated import curated_track_for_query

        _curated = curated_track_for_query(query) or curated_track_for_query(provider_query)
        _learned = None
        for _lq in (query, provider_query):
            _learned = await get_learned_track(_lq)
            if _learned:
                break
        # Curated catalog pins override stale/wrong learned mappings.
        if _curated and _learned and _learned.get("video_id") != _curated.get("video_id"):
            _learned = None
        pin = _curated or _learned
        if pin and pin.get("video_id"):
            _match = next(
                (c for c in results if c.get("video_id") == pin.get("video_id")),
                None,
            )
            _learned_pin = _match or pin
            _learned_pin["_query"] = query
            if _curated and _learned_pin is pin:
                _learned_pin["_curated"] = True
                _learned_pin["_hint_bonus"] = max(
                    float(_learned_pin.get("_hint_bonus", 0.0)), 3.0,
                )
            results = [_learned_pin] + [
                r for r in results if r.get("video_id") != _learned_pin.get("video_id")
            ]
            logger.info(
                "search: pin vid=%s title=%s curated=%s",
                _learned_pin.get("video_id"), _learned_pin.get("title"), bool(_curated),
            )
    except Exception:
        logger.debug("learned pin failed", exc_info=True)

    # Cache the final ranked results so a repeat of this query bypasses the whole
    # engine next time (Tier 0). file_id is stripped — delivery re-resolves it via
    # Redis/Postgres, so a stale Telegram id can never be served from this cache.
    # Skipped when we already served from cache (_skip_engine) to avoid churn.
    if results and not _skip_engine:
        try:
            _slim = [{k: v for k, v in r.items() if k != "file_id"} for r in results]
            await cache.set_result_cache(_norm_q, _slim)
        except Exception:
            logger.debug("set_result_cache failed", exc_info=True)

    # Groups: auto-play first track — prefer cached tracks for instant delivery
    if is_group:
        import re as _re_grp
        from bot.services.search_engine import _SOURCE_RANK as _SRC_RANK_MIX, _SOURCE_RANK_CYR
        _q_has_cyr = bool(_re_grp.search(r'[а-яёА-ЯЁ]', provider_query))
        _grp_rank = _SOURCE_RANK_CYR if _q_has_cyr else _SRC_RANK_MIX

        # Highest priority: a track previously confirmed correct for this query.
        best = _learned_pin

        if best is None:
            _ranked = _group_relevance_rank(
                results,
                provider_query=provider_query,
                parsed_query=parsed_query,
                source_rank=_grp_rank,
            )
            best = _ranked[0][0]
            # A result that covers ~all query words (artist+title) is an exact match
            # and must win over a higher-scored but non-covering track — e.g. the
            # popular "Jah Khalib — 9 грамм свинца" (covers 2/3 words) was beating the
            # queried "9 грамм — Дэнс" (covers 3/3) on file_id/downloads bonus, and
            # "Три дня дождя — Bye-Bye" was beating the queried "…— Прощание".
            #
            # Scanned against the UNFILTERED results (not _ranked): the relevance
            # rank drops "named-artist" collabs — "Три дня дождя, MONA — Прощание" is
            # dropped for query "Три дня дождя Прощание" because it adds the featured
            # "MONA", leaving only "…— Bye-Bye". The dedup order of results still
            # surfaces the exact match. Safe for the "Клава Кока душный" case: no track
            # there covers all 3 words, so no promote fires and the filter still rules.
            if not _direct_hit_present([best], provider_query):
                for _cand in results:
                    if _direct_hit_present([_cand], provider_query):
                        logger.info(
                            "Group: promote exact-cover pick over %s -> %s",
                            best.get("title"), _cand.get("title"),
                        )
                        best = _cand
                        break
            logger.info(
                "Group: relevance pick score=%.3f src=%s vid=%s title=%s",
                _ranked[0][1], best.get("source"), best.get("video_id"), best.get("title"),
            )

        if not best.get("file_id"):
            fid = await cache.get_file_id(best.get("video_id", ""), bitrate=192)
            if fid:
                best["file_id"] = fid

        # Build play queue: score-sorted, title-hint filtered (no Круг on «матранг рука»)
        from bot.services.downloader import _is_permanently_failed as _pf_check
        _play_queue = _group_play_queue(
            results,
            provider_query=provider_query,
            parsed_query=parsed_query,
            source_rank=_grp_rank,
            best=best,
            max_tries=5,
        )
        _played = False
        for _pi, _play_cand in enumerate(_play_queue):
            _vid = _play_cand.get("video_id", "")
            if _vid and _pf_check(_vid):
                logger.info("Group: skipping permanently-failed candidate %s", _vid)
                continue
            logger.info(
                "Group auto-play try #%d: src=%s vid=%s title=%s",
                _pi, _play_cand.get("source"), _vid, _play_cand.get("title"),
            )
            # Alts for this candidate = everything else in the play queue
            _this_alts = [r for r in _play_queue if r.get("video_id") != _vid]
            _this_alt_sid: str | None = None
            if _this_alts:
                _this_alt_sid = secrets.token_urlsafe(6)
                await cache.store_search(_this_alt_sid, _this_alts)
            try:
                await _group_auto_play(
                    message, status, user, _play_cand,
                    alt_sid=_this_alt_sid,
                    raise_on_error=True,
                )
                _played = True
                break
            except Exception as _play_err:
                logger.warning(
                    "Group: candidate #%d failed (%s), trying next: %s",
                    _pi, _vid, _play_err,
                )
                continue
        if not _played:
            try:
                await status.edit_text(t(lang, "error_download"))
            except Exception:
                pass
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)
    keyboard = _build_results_keyboard(results, session_id)
    # Collect unique sources
    _source_tags = {"soundcloud": "SoundCloud", "vk": "VK Music", "yandex": "Яндекс.Музыка", "spotify": "Spotify", "youtube": "YouTube", "channel": "Каталог"}
    sources_used = []
    for r in results:
        s = r.get("source", "youtube")
        tag = _source_tags.get(s, s)
        if tag not in sources_used:
            sources_used.append(tag)
    source_line = " · ".join(sources_used) if sources_used else "YouTube"
    await status.edit_text(
        f"{_SEARCH_LOGO}\n\n"
        f"<b>{t(lang, 'search_results')}:</b> {html.escape(query)}\n"
        f"▸ {source_line} · {len(results)} треков",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    # Show appeal button if any tracks were blocked
    if blocked_count > 0 and blocked_source_id:
        from bot.callbacks import AppealCb
        appeal_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t(lang, "dmca_appeal_btn"),
                callback_data=AppealCb(sid=blocked_source_id[:30]).pack(),
            )
        ]])
        await message.answer(
            t(lang, "dmca_blocked_notice", count=blocked_count),
            reply_markup=appeal_kb,
            parse_mode="HTML",
        )


async def _download_spotify_track(track_info: dict, bitrate: int) -> Path:
    """Download a Spotify track via Yandex Music (preferred) or YouTube fallback."""
    query = track_info.get("yt_query") or f"{track_info['uploader']} - {track_info['title']}"
    video_id = track_info["video_id"]

    # Try Yandex first — best quality
    ym_results = await search_yandex(query, limit=1)
    if ym_results and ym_results[0].get("ym_track_id"):
        _dl_id = uuid.uuid4().hex[:8]
        dest = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
        await download_yandex(ym_results[0]["ym_track_id"], dest, bitrate)
        return dest

    # Fallback: search YouTube and download
    yt_results = await search_tracks(query, max_results=1, source="youtube")
    if yt_results:
        return await download_track(yt_results[0]["video_id"], bitrate, dl_id=uuid.uuid4().hex[:8])

    raise RuntimeError(f"No downloadable source found for Spotify track: {query}")


def _wrong_track_keyboard(alt_sid: str, num_alts: int) -> InlineKeyboardMarkup | None:
    """Build the '🔁 Не тот трек?' inline keyboard for group messages.

    Shows numbered buttons (#1 #2 …) that let the user pick an alternative track.
    """
    if not alt_sid or num_alts == 0:
        return None
    alt_buttons = []
    for i in range(min(num_alts, 4)):
        alt_buttons.append(
            InlineKeyboardButton(
                text=f"#{i + 1}",
                callback_data=WrongTrackPickCb(sid=alt_sid, i=i).pack(),
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Не тот трек?", callback_data="wt_label")],
            alt_buttons,
        ]
    )


@router.callback_query(lambda c: c.data == "wt_label")
async def cb_wt_label(callback: CallbackQuery) -> None:
    """Noop handler for the '🔁 Не тот трек?' label button — just shows a tooltip."""
    await callback.answer("Нажми на номер, чтобы скачать другой вариант", show_alert=False)


def _group_track_keyboard(
    alt_sid: str | None,
    num_alts: int,
    tid: int | None,
    lang: str = "ru",
    *,
    alts: list[dict] | None = None,
    expanded: bool = False,
) -> InlineKeyboardMarkup | None:
    """Group track buttons: «Не тот трек?» dropdown + a lyrics button.

    Collapsed (default): one «🔁 Не тот трек?» button — tapping it expands the
    named alternatives in place (no permanent #1 #2 #3 clutter under the track).
    Expanded: one row per alternative (artist — title) + «‹ Скрыть».
    """
    rows: list[list[InlineKeyboardButton]] = []
    if alt_sid and num_alts > 0:
        if expanded and alts:
            for i, a in enumerate(alts[:4]):
                label = f"{(a.get('uploader') or '')[:24]} — {(a.get('title') or '')[:32]}".strip(" —")
                rows.append([
                    InlineKeyboardButton(
                        text=label or f"#{i + 1}",
                        callback_data=WrongTrackPickCb(sid=alt_sid, i=i).pack(),
                    )
                ])
            rows.append([
                InlineKeyboardButton(
                    text="‹ Скрыть",
                    callback_data=WtCollapseCb(sid=alt_sid, tid=tid or 0).pack(),
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    text="🔁 Не тот трек?",
                    callback_data=WtExpandCb(sid=alt_sid, tid=tid or 0).pack(),
                )
            ])
    if tid:
        rows.append([
            InlineKeyboardButton(
                text=t(lang, "tb_lyrics"),
                callback_data=LyricsCb(tid=tid).pack(),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.callback_query(WtExpandCb.filter())
async def cb_wt_expand(callback: CallbackQuery, callback_data: WtExpandCb) -> None:
    """«Не тот трек?» → expand the named alternatives in place."""
    alts = await cache.get_search(callback_data.sid)
    if not alts:
        await callback.answer("Список устарел — повтори запрос", show_alert=True)
        return
    try:
        user = await get_or_create_user(callback.from_user)
        lang = user.language
    except Exception:
        lang = "ru"
    kb = _group_track_keyboard(
        callback_data.sid, len(alts), callback_data.tid or None, lang,
        alts=alts, expanded=True,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Выбери правильный вариант")


@router.callback_query(WtCollapseCb.filter())
async def cb_wt_collapse(callback: CallbackQuery, callback_data: WtCollapseCb) -> None:
    """«‹ Скрыть» → collapse back to the single button."""
    alts = await cache.get_search(callback_data.sid)
    try:
        user = await get_or_create_user(callback.from_user)
        lang = user.language
    except Exception:
        lang = "ru"
    kb = _group_track_keyboard(
        callback_data.sid, len(alts) if alts else 0,
        callback_data.tid or None, lang,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


async def _send_album_track(message: Message, user, track_info: dict) -> bool:
    """Send one album track: cached file_id if available, else Yandex download.

    Compact single-track delivery for the whole-album flow — no status messages,
    no original-message cleanup (the album loop manages its own status).
    """
    lang = user.language
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else 192
    video_id = track_info.get("video_id", "")
    _af = _is_ad_free(user)

    file_id = await cache.get_file_id(video_id, bitrate)
    if not file_id:
        try:
            from bot.services.telegram_cache import get_file_id as _tg_get_fid
            file_id = await _tg_get_fid(video_id)
        except Exception:
            file_id = None
    if file_id:
        await _ensure_caption_duration(track_info)
        await message.answer_audio(
            audio=file_id,
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            **_audio_tag_kwargs(track_info),
        )
        await _post_download(user.id, track_info, file_id, bitrate)
        return True

    if not track_info.get("ym_track_id"):
        return False
    mp3_path: Path | None = None
    try:
        _dl_id = uuid.uuid4().hex[:8]
        mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
        await download_yandex(track_info["ym_track_id"], mp3_path, bitrate)
        if not track_info.get("duration_fmt"):
            try:
                from mutagen import File as _MutFile
                _mf = _MutFile(str(mp3_path))
                if _mf and _mf.info and getattr(_mf.info, "length", 0):
                    track_info["duration"] = int(_mf.info.length)
                    track_info["duration_fmt"] = _fmt_duration(int(_mf.info.length))
            except Exception:
                pass
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            **_audio_tag_kwargs(track_info),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        return True
    except Exception:
        logger.debug("album track download failed for %s", video_id, exc_info=True)
        return False
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _group_auto_play(
    message: Message, status: Message, user, track_info: dict,
    alt_sid: str | None = None,
    raise_on_error: bool = False,
) -> None:
    """In groups: download and send the first track immediately, then clean up.

    alt_sid   — session ID for the alternate-candidates list (for "🔁 Не тот трек?" button).
    raise_on_error — re-raise download exceptions instead of showing error message;
                     used by the retry loop in the group dispatch section.
    """
    lang = user.language
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else _smart_bitrate(
        track_info.get("source"), track_info.get("duration"), default_br
    )
    video_id = track_info["video_id"]

    # "Не тот трек?" keyboard must be available on ALL delivery paths — a wrong
    # pick served from cache (file_id) is otherwise uncorrectable while rcache
    # keeps re-serving it for 7 days (the self-learning bust/pin machinery only
    # triggers from this button).
    _wt_kb = None
    _alt_n = 0
    if alt_sid:
        try:
            _alt_list = await cache.get_search(alt_sid)
            if _alt_list:
                _alt_n = len(_alt_list)
                _wt_kb = _group_track_keyboard(alt_sid, _alt_n, None, lang)
        except Exception:
            pass

    # Local file_id (channel tracks)
    _af = _is_ad_free(user)
    local_fid = track_info.get("file_id")
    if local_fid:
        await _ensure_caption_duration(track_info)
        caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
        sent = await message.answer_audio(
            audio=local_fid,
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=caption,
            reply_markup=_wt_kb,
            **_audio_tag_kwargs(track_info),
        )
        tid = await _post_download(user.id, track_info, local_fid, bitrate)
        if tid:  # add the lyrics button once the track DB id is known
            try:
                await sent.edit_reply_markup(
                    reply_markup=_group_track_keyboard(alt_sid, _alt_n, tid, lang)
                )
            except Exception:
                pass
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
        return

    # Redis cache, then Postgres (durable file_id) before falling back to download.
    file_id = await cache.get_file_id(video_id, bitrate)
    if not file_id:
        try:
            from bot.services.telegram_cache import get_file_id as _tg_get_fid
            file_id = await _tg_get_fid(video_id)  # Redis -> Postgres Track.file_id -> warm Redis
        except Exception:
            file_id = None
    if file_id:
        await _ensure_caption_duration(track_info)
        caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
        sent = await message.answer_audio(
            audio=file_id,
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=caption,
            reply_markup=_wt_kb,
            **_audio_tag_kwargs(track_info),
        )
        tid = await _post_download(user.id, track_info, file_id, bitrate)
        if tid:
            try:
                await sent.edit_reply_markup(
                    reply_markup=_group_track_keyboard(alt_sid, _alt_n, tid, lang)
                )
            except Exception:
                pass
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
        return

    # Download (safe edit — status might already show "downloading" from a previous attempt)
    try:
        await status.edit_text(t(lang, "downloading"))
    except Exception:
        pass  # "message is not modified" or already deleted — ignore
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    mp3_path: Path | None = None
    try:
        _dl_id = uuid.uuid4().hex[:8]
        if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
            logger.info(
                "Group download: src=yandex ym_track_id=%s vid=%s",
                track_info.get("ym_track_id"), video_id,
            )
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
        elif track_info.get("source") == "vk" and track_info.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_vk(track_info["vk_url"], mp3_path)
        elif track_info.get("source") == "spotify":
            mp3_path = await _download_spotify_track(track_info, bitrate)
        else:
            dl_vid = video_id
            if not _is_valid_yt_id(video_id):
                dl_vid = await _resolve_yt_video_id(track_info)
                if not dl_vid:
                    if not raise_on_error:
                        try:
                            await status.edit_text(t(lang, "error_download"))
                        except Exception:
                            pass
                    raise RuntimeError(f"Could not resolve YouTube ID for {video_id}")
            mp3_path = await download_track(dl_vid, bitrate, dl_id=_dl_id)
        file_size = mp3_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            dl_vid = video_id if _is_valid_yt_id(video_id) else (await _resolve_yt_video_id(track_info) or video_id)
            try:
                mp3_path = await download_track(dl_vid, 128, dl_id=_dl_id)
                bitrate = 128
                file_size = mp3_path.stat().st_size
            except Exception:
                mp3_path = None
                if raise_on_error:
                    raise RuntimeError("too large")
                try:
                    await status.edit_text(t(lang, "error_too_large_final"))
                except Exception:
                    pass
                return
            if file_size > settings.MAX_FILE_SIZE:
                cleanup_file(mp3_path)
                mp3_path = None
                if raise_on_error:
                    raise RuntimeError("too large")
                try:
                    await status.edit_text(t(lang, "error_too_large_final"))
                except Exception:
                    pass
                return
        # Count how many alts are stored for the button
        _num_alts = 0
        if alt_sid:
            try:
                _alt_list = await cache.get_search(alt_sid)
                _num_alts = len(_alt_list) if _alt_list else 0
            except Exception:
                pass
        _wt_kb = _group_track_keyboard(alt_sid, _num_alts, None, lang) if _num_alts > 0 else None
        # Curated pins / some results carry no duration -> caption showed "?:??".
        # Read it from the downloaded file so the caption matches the audio bubble.
        if not track_info.get("duration_fmt") and mp3_path:
            try:
                from mutagen import File as _MutFile
                _mf = _MutFile(str(mp3_path))
                if _mf and _mf.info and getattr(_mf.info, "length", 0):
                    _sec = int(_mf.info.length)
                    track_info["duration"] = _sec
                    track_info["duration_fmt"] = _fmt_duration(_sec)
            except Exception:
                logger.debug("duration read failed for %s", mp3_path, exc_info=True)
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_wt_kb,
            **_audio_tag_kwargs(track_info),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        if tid:  # add the lyrics button once the track DB id is known
            try:
                await sent.edit_reply_markup(
                    reply_markup=_group_track_keyboard(alt_sid, _num_alts, tid, lang)
                )
            except Exception:
                pass
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
    except Exception as e:
        err_msg = str(e)
        logger.error("Group auto-play error for %s: %s", video_id, err_msg)
        if raise_on_error:
            raise
        try:
            await status.edit_text(t(lang, _classify_download_error(err_msg)))
        except Exception:
            pass
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _delete_msgs(bot, chat_id: int, msg_ids: list[int]) -> None:
    """Silently delete messages in a group chat."""
    for mid in msg_ids:
        if mid:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                logger.debug("delete_msgs mid=%s failed", mid, exc_info=True)


# ── "🔁 Не тот трек?" — wrong-track picker ────────────────────────────────

async def _delayed_delete(message, session_id: str, delay: int = 30) -> None:
    """Delete the keyboard message after `delay` seconds and clean up Redis keys."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.debug("delayed_delete: could not delete message: %s", e)
    try:
        await cache.redis.delete(f"picked:{session_id}", f"delete_timer:{session_id}")
    except Exception:
        pass


async def _mark_picked_and_refresh(callback, session_id: str, idx: int) -> None:
    """Mark idx as picked, refresh the keyboard checkmarks, and schedule deletion."""
    try:
        await cache.redis.sadd(f"picked:{session_id}", idx)
        await cache.redis.expire(f"picked:{session_id}", 300)
        raw_picked = await cache.redis.smembers(f"picked:{session_id}")
        picked = {int(x) for x in raw_picked}
        results = await cache.get_search(session_id)
        if results:
            new_kb = _build_results_keyboard(results, session_id, picked=picked)
            try:
                await callback.message.edit_reply_markup(reply_markup=new_kb)
            except Exception as e:
                logger.debug("mark_picked: edit_reply_markup failed: %s", e)
        timer_key = f"delete_timer:{session_id}"
        was_set = await cache.redis.setnx(timer_key, "1")
        if was_set:
            await cache.redis.expire(timer_key, 60)
            asyncio.create_task(_delayed_delete(callback.message, session_id, 30))
    except Exception as e:
        logger.warning("mark_picked_and_refresh error: %s", e)
        try:
            await callback.message.delete()
        except Exception:
            pass


async def _try_download_track(track: dict, bitrate: int) -> tuple[Path | None, str]:
    """Try to download a single track. Returns (mp3_path, error_message)."""
    video_id = track.get("video_id", "")
    _dl_id = uuid.uuid4().hex[:8]
    try:
        if track.get("source") == "yandex" and track.get("ym_track_id"):
            logger.info(
                "TryDownload: src=yandex ym_track_id=%s vid=%s",
                track.get("ym_track_id"), video_id,
            )
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_yandex(
                track["ym_track_id"], mp3_path, bitrate, token=track.get("_ym_token")
            )
            return mp3_path, ""
        elif track.get("source") == "vk" and track.get("vk_url"):
            logger.info("TryDownload: src=vk vid=%s", video_id)
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_vk(track["vk_url"], mp3_path)
            return mp3_path, ""
        elif track.get("source") == "spotify":
            logger.info("TryDownload: src=spotify vid=%s", video_id)
            mp3_path = await _download_spotify_track(track, bitrate)
            return mp3_path, ""
        else:
            dl_vid = video_id if _is_valid_yt_id(video_id) else None
            if not dl_vid:
                dl_vid = await _resolve_yt_video_id(track)
            if not dl_vid:
                return None, "no YouTube ID resolved"
            logger.info("TryDownload: src=%s yt_vid=%s", track.get("source", "yt"), dl_vid)
            mp3_path = await download_track(dl_vid, bitrate, dl_id=_dl_id)
            return mp3_path, ""
    except Exception as e:
        return None, str(e)


@router.callback_query(WrongTrackPickCb.filter())
async def cb_wrong_track_pick(callback: CallbackQuery, callback_data: WrongTrackPickCb) -> None:
    """Handle user picking an alternative track. Auto-retries through the alts list."""
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    alts = await cache.get_search(callback_data.sid)
    if not alts or callback_data.i >= len(alts):
        await callback.answer("Трек больше недоступен", show_alert=True)
        return
    primary = alts[callback_data.i]
    await callback.answer(f"⬇ {primary.get('title', '')[:40]}")
    chat_id = callback.message.chat.id
    orig_msg_id = callback.message.message_id
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    status = await callback.bot.send_message(chat_id, t(lang, "downloading"))
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else default_br

    # Build candidate queue: primary first, then other alts (different video_id)
    seen_vids = {primary.get("video_id", "")}
    candidates = [primary]
    for alt in alts:
        vid = alt.get("video_id", "")
        if vid and vid not in seen_vids:
            candidates.append(alt)
            seen_vids.add(vid)
    # Also fall back to a fresh YouTube search if everything fails
    fallback_query = f"{primary.get('uploader', '')} {primary.get('title', '')}".strip()

    from bot.services.downloader import _is_permanently_failed as _pf_check
    await callback.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

    sent_track: dict | None = None
    sent_path: Path | None = None
    final_err = ""
    for idx, track in enumerate(candidates[:5]):
        vid = track.get("video_id", "")
        if vid and _pf_check(vid):
            logger.info("WrongTrackPick: skipping permanently-failed %s", vid)
            continue
        logger.info(
            "WrongTrackPick try #%d: src=%s vid=%s title=%s",
            idx, track.get("source"), vid, track.get("title"),
        )
        mp3_path, err = await _try_download_track(track, bitrate)
        if mp3_path and mp3_path.exists():
            sent_track = track
            sent_path = mp3_path
            break
        final_err = err
        logger.warning(
            "WrongTrackPick try #%d failed src=%s vid=%s: %s",
            idx, track.get("source"), vid, err,
        )
        # cleanup partial file if any
        if mp3_path:
            cleanup_file(mp3_path)

    # Last-resort: fresh YouTube search by artist+title
    if sent_track is None and fallback_query:
        try:
            logger.info("WrongTrackPick fallback: fresh YouTube search '%s'", fallback_query[:80])
            yt_results = await search_tracks(fallback_query, max_results=2, source="youtube")
            for yt_cand in yt_results:
                yt_vid = yt_cand.get("video_id", "")
                if yt_vid in seen_vids or (yt_vid and _pf_check(yt_vid)):
                    continue
                logger.info("WrongTrackPick fallback try: yt_vid=%s", yt_vid)
                mp3_path, err = await _try_download_track(yt_cand, bitrate)
                if mp3_path and mp3_path.exists():
                    sent_track = yt_cand
                    sent_path = mp3_path
                    break
                final_err = err
                if mp3_path:
                    cleanup_file(mp3_path)
        except Exception as e:
            logger.debug("WrongTrackPick fresh-search fallback failed: %s", e)

    if sent_track is None or sent_path is None:
        logger.error(
            "WrongTrackPick: ALL %d candidates failed. last_err=%s",
            len(candidates), final_err,
        )
        try:
            await status.edit_text(t(lang, _classify_download_error(final_err)))
        except Exception:
            pass
        return

    try:
        _af = _is_ad_free(user)
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
            **_audio_tag_kwargs(sent_track),
        )
        await cache.set_file_id(sent_track.get("video_id", ""), sent.audio.file_id, bitrate)
        await _post_download(user.id, sent_track, sent.audio.file_id, bitrate)
        # Learn: this corrected pick is the right track for the original query.
        try:
            _learn_q = primary.get("_query") or sent_track.get("_query")
            if _learn_q:
                from bot.services.search_memory import remember_correction
                await remember_correction(_learn_q, sent_track)
                # The answer for this query just changed — drop its cached results.
                await cache.bust_result_cache(normalize_query(_learn_q))
        except Exception:
            logger.debug("search_memory remember (wrong-pick) failed", exc_info=True)
        for mid in [status.message_id, orig_msg_id]:
            try:
                await callback.bot.delete_message(chat_id, mid)
            except Exception:
                pass
    except Exception as e:
        logger.error("WrongTrackPick: send_audio failed: %s", e, exc_info=True)
        try:
            await status.edit_text(t(lang, "error_download"))
        except Exception:
            pass
    finally:
        if sent_path:
            cleanup_file(sent_path)


# fmt_duration imported from bot.utils
_fmt_duration = fmt_duration


# ── DMCA Appeal handler ───────────────────────────────────────────────────

from bot.callbacks import AppealCb


@router.callback_query(AppealCb.filter())
async def cb_dmca_appeal(callback: CallbackQuery, callback_data: AppealCb) -> None:
    """Handle DMCA appeal button click."""
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    source_id = callback_data.sid

    # Find the blocked track in DB
    from bot.models.blocked_track import BlockedTrack
    from bot.models.base import async_session as _async_session
    from sqlalchemy import select as _select

    async with _async_session() as session:
        result = await session.execute(
            _select(BlockedTrack).where(BlockedTrack.source_id == source_id)
        )
        blocked = result.scalar_one_or_none()

    if not blocked:
        await callback.answer(t(lang, "dmca_appeal_not_found"), show_alert=True)
        return

    from bot.services.dmca_filter import create_appeal
    appeal_id = await create_appeal(
        user_id=user.id,
        blocked_track_id=blocked.id,
        reason=f"User appeal for {source_id}",
    )
    if appeal_id:
        await callback.answer()
        await callback.message.edit_text(
            t(lang, "dmca_appeal_sent", appeal_id=appeal_id),
            parse_mode="HTML",
        )
    else:
        await callback.answer(t(lang, "dmca_appeal_error"), show_alert=True)


_GROUP_SEARCH_PREFIXES = (
    "включи ", "поставь ", "хочу послушать ", "play ", "найди ", "трек ",
    "музыка ", "песня ",
)


def _strip_bot_mention_text(text: str, bot_username: str | None) -> tuple[str, bool]:
    if not bot_username:
        return text, False
    lower = text.lower()
    at_tag = f"@{bot_username}"
    idx = lower.find(at_tag.lower())
    if idx == -1:
        return text, False
    return (text[:idx] + text[idx + len(at_tag):]).strip(), True


def _strip_bot_mention_entities(
    text: str, message: Message, bot_id: int, bot_username: str | None,
) -> tuple[str, bool]:
    if not message.entities or not message.text:
        return text, False
    matched = False
    spans: list[tuple[int, int]] = []
    for ent in message.entities:
        if ent.type == MessageEntityType.MENTION and bot_username:
            mention = message.text[ent.offset : ent.offset + ent.length]
            if mention.lstrip("@").lower() == bot_username.lower():
                matched = True
                spans.append((ent.offset, ent.length))
        elif ent.type == MessageEntityType.TEXT_MENTION and ent.user and ent.user.id == bot_id:
            matched = True
            spans.append((ent.offset, ent.length))
    if not matched:
        return text, False
    raw = message.text
    for offset, length in sorted(spans, reverse=True):
        raw = raw[:offset] + raw[offset + length :]
    return raw.strip()[:500], True


def _is_reply_to_bot(message: Message, bot_id: int) -> bool:
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.id == bot_id)


def _strip_search_prefix(text: str) -> tuple[str, bool]:
    lower = text.lower()
    for prefix in _GROUP_SEARCH_PREFIXES:
        if lower.startswith(prefix):
            return text[len(prefix):].strip(), True
    return text, False


async def _parse_group_search_text(message: Message) -> tuple[str, bool]:
    """Extract query from a group message; return (query, should_search)."""
    text = (message.text or "").strip()[:500]
    if not text:
        return "", False

    bot_me = await message.bot.me()
    triggered = _is_reply_to_bot(message, bot_me.id)

    text, mention = _strip_bot_mention_text(text, bot_me.username)
    if mention:
        triggered = True

    text, ent_mention = _strip_bot_mention_entities(text, message, bot_me.id, bot_me.username)
    if ent_mention:
        triggered = True

    text, prefix = _strip_search_prefix(text)
    if prefix:
        triggered = True

    if not triggered:
        if is_spotify_url(text) or is_yandex_music_url(text):
            return text, True
        return text, False

    return text, True


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    query = message.text.removeprefix("/search").strip()
    # In groups the command may be "/search@BotName query" — strip the bot mention.
    if query.startswith("@"):
        parts = query.split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
    query = query[:500]
    if not query:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "search_prompt"))
        return
    await _do_search(message, query)


@router.message(lambda m: m.text and not m.text.startswith("/"))
async def handle_text(message: Message) -> None:
    text = message.text.strip()[:500]
    lower = text.lower()

    # "что играет" / "что за трек" → radio.py
    if any(phrase in lower for phrase in ("что играет", "что за трек")):
        return
    # "выключи" → radio.py
    if lower in ("стоп", "stop", "пауза", "pause", "дальше", "скип", "next", "skip", "выключи"):
        return

    is_group = message.chat.type in ("group", "supergroup")

    if is_group:
        text, triggered = await _parse_group_search_text(message)
        if not triggered:
            return
    else:
        text, prefix = _strip_search_prefix(text)
        # prefix stripping optional in DM — keep going even without prefix

    # In groups: links already handled inside _parse_group_search_text
    if is_group and not text:
        return

    if not is_group and not text:
        return

    # Intent detection: "random", "рандом", "что-нибудь", "любой трек", etc.
    _RANDOM_INTENTS = (
        "рандом", "случайный", "что-нибудь", "что нибудь", "любой трек",
        "любую песню", "любой", "что угодно", "наугад", "сюрприз",
        "random", "anything", "surprise", "any track", "whatever",
    )
    if text.lower().strip() in _RANDOM_INTENTS:
        track = await get_random_popular_track()
        if track and track.source_id:
            track_info = {
                "video_id": track.source_id,
                "title": track.title or "Unknown",
                "uploader": track.artist or "Unknown",
                "duration": track.duration or 0,
                "duration_fmt": fmt_duration(track.duration) if track.duration else "?:??",
                "source": track.source or "channel",
                "file_id": track.file_id,
            }
            if is_group:
                user = await get_or_create_user(message.from_user)
                status = await message.answer("🎲")
                await _group_auto_play(message, status, user, track_info)
                return
            # DM: still do normal search but with a popular artist
            pass

    await _do_search(message, text)


@router.callback_query(TrackCallback.filter())
async def handle_track_select(
    callback: CallbackQuery, callback_data: TrackCallback
) -> None:
    await callback.answer()

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return
    lang = user.language
    is_group = callback.message.chat.type in ("group", "supergroup")

    if user.is_banned:
        return

    results = await cache.get_search(callback_data.sid)
    if not results or callback_data.i >= len(results):
        await callback.message.answer(t(lang, "session_expired"))
        return

    track_info = results[callback_data.i]
    _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
    video_id = track_info["video_id"]

    # ── Selection audit log ───────────────────────────────────────────────
    try:
        _sel_audit = _json.dumps({
            "t": "pick",
            "ts": int(time.time()),
            "uid": user.id,
            "grp": is_group,
            "q": (track_info.get("_query") or "")[:300],
            "idx": callback_data.i,
            "n": len(results),
            "artist": track_info.get("uploader", "")[:120],
            "title": track_info.get("title", "")[:120],
            "src": track_info.get("source", "?"),
        }, ensure_ascii=False)
        await cache.redis.lpush("search:audit", _sel_audit)
        await cache.redis.ltrim("search:audit", 0, 49999)
    except Exception:
        logger.debug("selection audit log failed", exc_info=True)

    if not await _acquire_download_lock(user.id, video_id):
        return

    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else _smart_bitrate(
        track_info.get("source"), track_info.get("duration"), default_br
    )
    _af = _is_ad_free(user)

    try:

        # If track already has a file_id from local DB (channel tracks)
        local_fid = track_info.get("file_id")
        if local_fid:
            caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
            await callback.message.answer_audio(
                audio=local_fid,
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=caption,
                message_effect_id=_EFFECT_FIRE if not is_group else None,
                **_audio_tag_kwargs(track_info),
            )
            tid = await _post_download(user.id, track_info, local_fid, bitrate)
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                _bot_me = await callback.bot.me()
                _share_url = f"https://t.me/{_bot_me.username}?start=tr_{tid}" if tid else ""
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(lang, tid, _share_q, share_url=_share_url),
                )
            return

        # Проверяем Redis кэш
        file_id = await cache.get_file_id(video_id, bitrate)
        if file_id:
            cache_hits.inc()
            caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
            await callback.message.answer_audio(
                audio=file_id,
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=caption,
                message_effect_id=_EFFECT_FIRE if not is_group else None,
                **_audio_tag_kwargs(track_info),
            )
            tid = await _post_download(user.id, track_info, file_id, bitrate)
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                _bot_me = await callback.bot.me()
                _share_url = f"https://t.me/{_bot_me.username}?start=tr_{tid}" if tid else ""
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(lang, tid, _share_q, share_url=_share_url),
                )
            return

        status = await callback.message.answer(t(lang, "downloading"))
        await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        cache_misses.inc()

        progress_cb = _make_progress_cb(status, lang)
        mp3_path: Path | None = None
        _dl_id = uuid.uuid4().hex[:8]
        _dl_t0 = time.monotonic()
        _dl_src = track_info.get("source", "youtube")

        try:
            if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
                logger.info(
                    "DM download: src=yandex ym_track_id=%s vid=%s",
                    track_info.get("ym_track_id"), video_id,
                )
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
            elif track_info.get("source") == "vk" and track_info.get("vk_url"):
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_vk(track_info["vk_url"], mp3_path)
            elif track_info.get("source") == "spotify":
                mp3_path = await _download_spotify_track(track_info, bitrate)
            else:
                # For Yandex tracks missing ym_track_id, log the anomaly
                if track_info.get("source") == "yandex":
                    logger.warning(
                        "DM download: src=yandex but ym_track_id missing! vid=%s keys=%s",
                        video_id, list(track_info.keys()),
                    )
                dl_vid = video_id
                if not _is_valid_yt_id(video_id):
                    dl_vid = await _resolve_yt_video_id(track_info)
                    if not dl_vid:
                        await status.edit_text(t(lang, "error_download"))
                        return
                mp3_path = await download_track(dl_vid, bitrate, progress_cb=progress_cb, dl_id=_dl_id)
            file_size = mp3_path.stat().st_size

            if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
                cleanup_file(mp3_path)
                mp3_path = None
                await status.edit_text(t(lang, "error_too_large"))
                try:
                    dl_vid_fb = video_id if _is_valid_yt_id(video_id) else (await _resolve_yt_video_id(track_info) or video_id)
                    mp3_path = await download_track(dl_vid_fb, 128, dl_id=_dl_id)
                    bitrate = 128
                    file_size = mp3_path.stat().st_size
                except Exception:
                    mp3_path = None
                    await status.edit_text(t(lang, "error_too_large_final"))
                    return
                if file_size > settings.MAX_FILE_SIZE:
                    cleanup_file(mp3_path)
                    mp3_path = None
                    await status.edit_text(t(lang, "error_too_large_final"))
                    return

            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                message_effect_id=_EFFECT_FIRE if not is_group else None,
                **_audio_tag_kwargs(track_info),
            )

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
            record_provider_event(_dl_src, "download", time.monotonic() - _dl_t0, True)
            tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
            await status.delete()
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                _bot_me = await callback.bot.me()
                _share_url = f"https://t.me/{_bot_me.username}?start=tr_{tid}" if tid else ""
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(lang, tid, _share_q, share_url=_share_url),
                )

        except Exception as e:
            err_msg = str(e)
            record_provider_event(_dl_src, "download", time.monotonic() - _dl_t0, False, err_msg)
            logger.error("Download error for %s: %s", video_id, err_msg)
            # C-07: Auto-retry with a different source (only if the original source was not YouTube)
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            # Only do YouTube fallback when Yandex/VK/etc. failed AND the error is NOT a YouTube error
            # (If err_msg already contains a YouTube error, we're already in YouTube path — don't double-retry)
            _already_youtube_err = "youtube" in err_msg.lower() or "ytdl" in err_msg.lower()
            if retry_query and failed_source != "youtube" and not _already_youtube_err:
                try:
                    await status.edit_text(t(lang, "searching") + "...")
                    alt_results = await search_tracks(retry_query, max_results=1, source="youtube")
                    if alt_results:
                        retry_id = uuid.uuid4().hex[:8]
                        retry_path = await download_track(alt_results[0]["video_id"], bitrate, dl_id=retry_id)
                        try:
                            sent = await callback.message.answer_audio(
                                audio=FSInputFile(retry_path),
                                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                                **_audio_tag_kwargs(track_info),
                            )
                            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
                            tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
                            await status.delete()
                            if not is_group:
                                _bot_me = await callback.bot.me()
                                _share_url = f"https://t.me/{_bot_me.username}?start=tr_{tid}" if tid else ""
                                await callback.message.answer(
                                    t(lang, "rate_track"),
                                    reply_markup=_feedback_keyboard(lang, tid, _share_q, share_url=_share_url),
                                )
                            return
                        finally:
                            cleanup_file(retry_path)
                except Exception as retry_err:
                    logger.debug("Auto-retry also failed: %s", retry_err)
            # Add a retry button so the user can try again
            retry_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 " + t(lang, "retry_btn"),
                    callback_data=TrackCallback(sid=callback_data.sid, i=callback_data.i).pack(),
                )]
            ])
            await status.edit_text(
                t(lang, _classify_download_error(err_msg)),
                reply_markup=retry_kb,
            )
        finally:
            if mp3_path:
                cleanup_file(mp3_path)
    finally:
        await _release_download_lock(user.id, video_id)


async def _post_download(user_id: int, track_info: dict, file_id: str, bitrate: int) -> int:
    """Records track in DB and listening event. Returns track DB id (0 on DB error)."""
    await increment_request_count(user_id)
    try:
        _tags = _audio_tag_kwargs(track_info)
        track = await upsert_track(
            source_id=track_info["video_id"],
            title=_tags["title"],
            artist=_tags["performer"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            file_id=file_id,
            source=track_info.get("source", "youtube"),
            channel="external",
            cover_url=track_info.get("cover_url"),
            album=track_info.get("album"),
            release_year=track_info.get("upload_year") or track_info.get("release_year"),
        )
    except Exception as e:
        logger.warning("_post_download: upsert_track failed: %s", e)
        return 0
    await record_listening_event(
        user_id=user_id,
        track_id=track.id,
        action="play",
        source="search",
    )
    # E-01: Check referral activation on 3rd download
    try:
        from bot.handlers.referral import check_referral_activation
        from bot.models.base import async_session as _async_session2
        from bot.models.user import User as _User2
        async with _async_session2() as session:
            from sqlalchemy import select as _sel2
            u_dl = (await session.execute(_sel2(_User2).where(_User2.id == user_id))).scalar()
            if u_dl:
                await check_referral_activation(user_id, u_dl.request_count)
    except Exception:
        logger.debug("check_referral_activation failed user=%s", user_id, exc_info=True)
    # Auto-update user taste profile every 10 listens
    try:
        from bot.models.base import async_session as _async_session
        from bot.models.user import User as _User
        async with _async_session() as session:
            from sqlalchemy import select as _sel
            u = (await session.execute(_sel(_User).where(_User.id == user_id))).scalar()
            if u and u.request_count and u.request_count % 10 == 0:
                from bot.config import settings as _cfg
                if _cfg.SUPABASE_AI_ENABLED:
                    from bot.services.supabase_ai import supabase_ai
                    try:
                        await supabase_ai.update_profile(user_id)
                    except Exception:
                        logger.debug("supabase_ai.update_profile failed user=%s", user_id, exc_info=True)
                else:
                    from recommender.ai_dj import update_user_profile
                    try:
                        await update_user_profile(user_id)
                    except Exception:
                        logger.debug("update_user_profile failed user=%s", user_id, exc_info=True)
    except Exception as e:
        logger.warning("_post_download: profile update failed: %s", e)
    return track.id


def _feedback_keyboard(
    lang: str,
    track_id: int,
    share_query: str = "",
    share_url: str = "",
    *,
    expanded: bool = False,
) -> InlineKeyboardMarkup:
    """Vibe reactions attached to the track bubble; '‹ Ещё' reveals add-actions.

    Collapsed  →  one vibe row + '‹ Ещё'.
    Expanded   →  vibe row + like/dislike + favorite/playlist/queue
                  + similar/lyrics/share + card/story/'‹ Свернуть'.
    All callback_data is reused so existing handlers keep working.
    """
    vibe_row = [
        InlineKeyboardButton(
            text=t(lang, "tb_vibe_fire"),
            callback_data=FeedbackCallback(tid=track_id, act="vibe_fire").pack(),
        ),
        InlineKeyboardButton(
            text=t(lang, "tb_vibe_sad"),
            callback_data=FeedbackCallback(tid=track_id, act="vibe_sad").pack(),
        ),
        InlineKeyboardButton(
            text=t(lang, "tb_vibe_night"),
            callback_data=FeedbackCallback(tid=track_id, act="vibe_night").pack(),
        ),
        InlineKeyboardButton(
            text=t(lang, "tb_vibe_drive"),
            callback_data=FeedbackCallback(tid=track_id, act="vibe_drive").pack(),
        ),
        InlineKeyboardButton(
            text=t(lang, "tb_vibe_love"),
            callback_data=FeedbackCallback(tid=track_id, act="vibe_love").pack(),
        ),
    ]
    if not expanded:
        return InlineKeyboardMarkup(inline_keyboard=[
            vibe_row,
            [
                InlineKeyboardButton(
                    text=t(lang, "tb_more"),
                    callback_data=TrackMenuCb(tid=track_id, act="more").pack(),
                )
            ],
        ])

    rows = [
        vibe_row,
        [
            InlineKeyboardButton(
                text=t(lang, "tb_like"),
                callback_data=FeedbackCallback(tid=track_id, act="like").pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_dislike"),
                callback_data=FeedbackCallback(tid=track_id, act="dislike").pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=t(lang, "tb_favorite"),
                callback_data=FavoriteCb(tid=track_id, act="add").pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_playlist"),
                callback_data=AddToPlCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_queue"),
                callback_data=AddToQueueCb(tid=track_id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=t(lang, "tb_similar"),
                callback_data=SimilarCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_lyrics"),
                callback_data=LyricsCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_share"),
                callback_data=ShareTrackCb(tid=track_id, act="mk").pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=t(lang, "tb_card"),
                callback_data=TrackCardCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_story"),
                callback_data=StoryCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "tb_less"),
                callback_data=TrackMenuCb(tid=track_id, act="hide").pack(),
            ),
        ],
    ]
    # Copy-to-clipboard: share link
    if share_url:
        rows[4].insert(
            0,
            InlineKeyboardButton(
                text=t(lang, "tb_copy_link"),
                copy_text=CopyTextButton(text=share_url),
            ),
        )
    # E-03: inline share (switch_inline_query)
    if share_query:
        rows[3].append(
            InlineKeyboardButton(
                text=t(lang, "tb_share"),
                switch_inline_query=share_query[:64],
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(TrackMenuCb.filter())
async def handle_track_menu(callback: CallbackQuery, callback_data: TrackMenuCb) -> None:
    """Expand/collapse the post-track action keyboard on the track bubble."""
    await callback.answer()
    try:
        user = await get_or_create_user(callback.from_user)
        lang = user.language
    except Exception:
        lang = "ru"
    share_url = ""
    if callback_data.act == "more":
        try:
            bot_me = await callback.bot.me()
            share_url = f"https://t.me/{bot_me.username}?start=tr_{callback_data.tid}"
        except Exception:
            logger.debug("track menu share url build failed", exc_info=True)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=_feedback_keyboard(
                lang,
                callback_data.tid,
                share_url=share_url,
                expanded=callback_data.act == "more",
            )
        )
    except Exception:
        logger.debug("track menu edit failed", exc_info=True)


@router.callback_query(FeedbackCallback.filter())
async def handle_feedback(
    callback: CallbackQuery, callback_data: FeedbackCallback
) -> None:
    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    await record_listening_event(
        user_id=user.id,
        track_id=callback_data.tid,
        action=callback_data.act,
        source="search",
    )
    if callback_data.act.startswith("vibe_"):
        vibe_labels = {
            "vibe_fire": "огонь",
            "vibe_sad": "грусть",
            "vibe_night": "ночь",
            "vibe_drive": "дорога",
            "vibe_love": "black love",
        }
        try:
            from bot.models.base import async_session as _async_session
            from bot.models.user import User as _User
            from sqlalchemy import update as _update

            async with _async_session() as session:
                await session.execute(
                    _update(_User)
                    .where(_User.id == user.id)
                    .values(fav_vibe=vibe_labels.get(callback_data.act, "black"))
                )
                await session.commit()
        except Exception:
            logger.debug("vibe fav update failed user=%s", user.id, exc_info=True)
        await callback.answer(f"Запомнил вайб: {vibe_labels.get(callback_data.act, 'black')}")
        return
    emoji = "✓" if callback_data.act == "like" else "✗"
    await callback.answer(t(user.language, "feedback_recorded", emoji=emoji))
    # Keyboard now lives on the audio bubble (a media caption, not text) — collapse
    # it back to the default vibe row instead of editing text, which media rejects.
    try:
        await callback.message.edit_reply_markup(
            reply_markup=_feedback_keyboard(user.language, callback_data.tid)
        )
    except Exception:
        logger.debug("feedback collapse edit failed", exc_info=True)


@router.callback_query(ShareTrackCb.filter())
async def handle_share_track(callback: CallbackQuery, callback_data: ShareTrackCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        from sqlalchemy import select as _sel

        track = (
            await session.execute(_sel(Track).where(Track.id == callback_data.tid))
        ).scalar_one_or_none()

    if not track:
        await callback.answer(t(lang, "pl_not_found"), show_alert=True)
        return

    if callback_data.act == "mk":
        try:
            share_id = await create_share_link(
                owner_id=user.id,
                entity_type="track",
                entity_id=track.id,
                ttl_seconds=_TRACK_SHARE_TTL,
            )
        except Exception:
            await callback.answer("⚠️", show_alert=True)
            return

        try:
            from bot.services.leaderboard import add_xp, XP_SHARE
            await add_xp(user.id, XP_SHARE)
        except Exception:
            logger.debug("add_xp share failed user=%s", user.id, exc_info=True)
        bot_me = await callback.bot.me()
        link = f"https://t.me/{bot_me.username}?start=tr_{share_id}"
        await callback.answer()
        await callback.message.answer(
            t(lang, "share_track_created", title=track.title or "?", link=link),
            parse_mode="HTML",
        )
        await track_event(user.id, "track_share", track_id=track.id, share_id=share_id)
        return

    # act == "dl"
    if track.file_id:
        await callback.answer()
        await callback.message.answer_audio(
            audio=track.file_id,
            duration=int(track.duration) if track.duration else None,
            caption=t(lang, "shared_track_caption"),
            **_audio_tag_kwargs({"uploader": track.artist, "title": track.title}),
        )
    else:
        await callback.answer()
        await callback.message.answer(t(lang, "share_track_no_file"))


async def _load_track_by_id(track_id: int):
    from bot.models.base import async_session
    from bot.models.track import Track
    from sqlalchemy import select as _sel

    async with async_session() as session:
        return (await session.execute(_sel(Track).where(Track.id == track_id))).scalar_one_or_none()


async def _fetch_cover_bytes(cover_url: str | None) -> bytes | None:
    if not cover_url:
        return None
    try:
        from bot.services.http_session import get_session

        async with get_session().get(cover_url, timeout=8) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type:
                return None
            return await resp.read()
    except Exception:
        logger.debug("cover fetch failed url=%s", cover_url, exc_info=True)
        return None


async def _send_track_card(callback: CallbackQuery, track_id: int, *, story: bool) -> None:
    """Generate and send either a compact card or a story-style card."""
    try:
        user = await get_or_create_user(callback.from_user)
        lang = user.language
    except Exception:
        lang = "ru"
    track = await _load_track_by_id(track_id)

    if not track:
        await callback.answer("⚠️ Трек не найден", show_alert=True)
        return

    await callback.answer("Генерирую карточку...")
    from bot.services.story_cards import generate_track_card
    from bot.utils import fmt_duration

    cover_bytes = await _fetch_cover_bytes(track.cover_url)

    card_bytes = await asyncio.to_thread(
        generate_track_card,
        artist=track.artist or "Unknown",
        title=track.title or "Unknown",
        track_id=track.id,
        duration=fmt_duration(track.duration or 0),
        cover_bytes=cover_bytes,
    )
    if card_bytes:
        filename = "black_room_story.png" if story else "black_room_card.png"
        caption = (
            "Готово. Вертикальная Story-карточка для Telegram Stories."
            if story
            else f"◉ BLACK ROOM\n{track.artist or 'Unknown'} — {track.title or 'Unknown'}"
        )
        await callback.message.answer_photo(
            photo=BufferedInputFile(card_bytes, filename=filename),
            caption=caption,
        )
    else:
        await callback.message.answer(t(lang, "story_card_error"))


@router.callback_query(TrackCardCb.filter())
async def handle_track_card(callback: CallbackQuery, callback_data: TrackCardCb) -> None:
    """Generate and send a visual track card."""
    await _send_track_card(callback, callback_data.tid, story=False)


@router.callback_query(StoryCb.filter())
async def handle_story_card(callback: CallbackQuery, callback_data: StoryCb) -> None:
    """Generate and send a story card for a track."""
    await _send_track_card(callback, callback_data.tid, story=True)


async def show_shared_track(message: Message, share_id: str) -> None:
    """Display shared track from deep-link /start tr_<share_id>."""
    user = await get_or_create_user(message.from_user)
    lang = user.language

    data = await resolve_share_link(share_id)
    if not data or data.get("entity_type") != "track":
        await message.answer(t(lang, "share_track_expired"))
        return

    track_id = int(data.get("entity_id") or 0)
    await track_event(user.id, "shared_track_open", share_id=share_id, track_id=track_id)

    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        from sqlalchemy import select as _sel

        track = (
            await session.execute(_sel(Track).where(Track.id == track_id))
        ).scalar_one_or_none()

    if not track:
        await message.answer(t(lang, "share_track_expired"))
        return

    text = t(
        lang,
        "share_track_open_header",
        artist=track.artist or "?",
        title=track.title or "?",
        duration=fmt_duration(track.duration or 0),
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "share_track_download_btn"),
                    callback_data=ShareTrackCb(tid=track.id, act="dl").pack(),
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(LyricsCb.filter())
async def handle_lyrics(callback: CallbackQuery, callback_data: LyricsCb) -> None:
    """Fetch and display lyrics for a track."""
    from bot.services.lyrics_provider import get_lyrics
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        result = await session.execute(
            _sel(Track).where(Track.id == callback_data.tid)
        )
        track = result.scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    artist = track.artist or ""
    title = track.title or ""
    lyrics_data = await get_lyrics(artist, title)

    if not lyrics_data or not lyrics_data.get("lines"):
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    lines = lyrics_data["lines"]
    url = lyrics_data.get("url", "")
    footer = f"\n<a href=\"{url}\">{t(lang, 'lyrics_full_link')}</a>" if url else ""

    # Build lyrics with expandable blockquote
    lyrics_text = "\n".join(lines)
    # Trim to fit Telegram message limit (4096 chars)
    max_lyrics = 3600
    if len(lyrics_text) > max_lyrics:
        lyrics_text = lyrics_text[:max_lyrics] + "\n…"
    header = f"\U0001f3b5 <b>{artist} — {title}</b>\n\n"
    body = f"<blockquote expandable>{lyrics_text}</blockquote>"
    text = header + body + footer

    translate_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001f30d Перевод", callback_data=LyrTransCb(tid=callback_data.tid).pack()),
        InlineKeyboardButton(
            text="\U0001f4cb Копировать",
            copy_text=CopyTextButton(text=f"{artist} — {title}\n\n{lyrics_text}"[:256]),
        ),
    ]])

    await callback.message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=translate_kb,
    )


@router.callback_query(LyrTransCb.filter())
async def handle_lyrics_translate(callback: CallbackQuery, callback_data: LyrTransCb) -> None:
    """Translate lyrics for a track."""
    from bot.services.lyrics_provider import get_lyrics, translate_lyrics
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language or "ru"
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        result = await session.execute(
            _sel(Track).where(Track.id == callback_data.tid)
        )
        track = result.scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    artist = track.artist or ""
    title_str = track.title or ""
    lyrics_data = await get_lyrics(artist, title_str)

    if not lyrics_data or not lyrics_data.get("lines"):
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    target = "ru" if lang != "ru" else "en"
    translated = await translate_lyrics(lyrics_data["lines"], target_lang=target)

    if not translated:
        await callback.message.answer(t(lang, "lyrics_translate_fail"))
        return

    chunks = _split_long_text_lines(
        header=f"🌐 <b>{artist} — {title_str}</b> ({target.upper()})",
        lines=translated,
        max_len=3900,
    )
    for chunk in chunks:
        await callback.message.answer(
            chunk,
            parse_mode="HTML",
        )


def _split_long_text_lines(
    header: str,
    lines: list[str],
    footer: str = "",
    max_len: int = 3900,
) -> list[str]:
    chunks: list[str] = []
    current = (header or "").strip()

    for raw_line in lines or []:
        line = str(raw_line)
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if footer:
        candidate = f"{current}\n\n{footer}" if current else footer
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = footer
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


@router.callback_query(SimilarCb.filter())
async def handle_similar(callback: CallbackQuery, callback_data: SimilarCb) -> None:
    """Find similar tracks based on the given track's artist/genre."""
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        track = (
            await session.execute(_sel(Track).where(Track.id == callback_data.tid))
        ).scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    # Build a search query from artist + genre
    artist = track.artist or ""
    title = track.title or ""
    query = f"{artist} {track.genre or ''}".strip() if artist else title

    if not query:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    await callback.message.answer(t(lang, "similar_searching"))

    # Search for similar tracks
    results = await search_tracks(query, max_results=5, source="youtube")

    # Also try other sources
    if len(results) < 5:
        try:
            ym = await search_yandex(query, limit=5)
            results.extend(ym)
        except Exception:
            logger.debug("search_yandex fallback failed query=%s", query, exc_info=True)

    if not results:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    # Deduplicate and remove the original track
    results = deduplicate_results(results)
    results = [r for r in results if r.get("video_id") != track.source_id][:5]

    if not results:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)

    buttons = []
    for i, tr in enumerate(results):
        dur = tr.get("duration_fmt", "?:??")
        label = f"♪ {tr.get('uploader', '?')} — {tr.get('title', '?')[:35]} ({dur})"
        buttons.append(
            [InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(
        t(lang, "similar_header", artist=artist, title=title[:30]),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
