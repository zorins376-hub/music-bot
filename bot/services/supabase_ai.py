"""
supabase_ai.py — Python client for the Supabase AI recommendation service.

Drop-in replacement for the local recommender module.
All AI/ML computation happens on Supabase (pgvector + Edge Functions).
The bot only calls HTTP endpoints.

Usage:
    from bot.services.supabase_ai import supabase_ai

    # Get recommendations
    recs = await supabase_ai.get_recommendations(user_id=123, limit=10)

    # Ingest listening event
    await supabase_ai.ingest_event(
        event="play",
        user_id=123,
        track={"source_id": "yt_xxx", "title": "...", "artist": "..."},
    )

    # Generate AI playlist
    playlist = await supabase_ai.generate_ai_playlist(
        user_id=123,
        prompt="грустный плейлист на вечер",
    )

    # Find similar tracks
    similar = await supabase_ai.get_similar(source_id="yt_xxx", limit=10)

    # Get AI analytics
    stats = await supabase_ai.get_analytics(days=7)

Environment variables required:
    SUPABASE_URL           — e.g. https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY   — service_role key (NOT anon key)
"""

import asyncio
import logging
from typing import Any

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_SUPABASE_URL: str = getattr(settings, "SUPABASE_URL", "") or ""
_SUPABASE_KEY: str = getattr(settings, "SUPABASE_SERVICE_KEY", "") or ""
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Rate-limit repeated error logging (avoid log spam)
_ingest_error_count: int = 0
_INGEST_ERROR_LOG_INTERVAL: int = 50


def _fn_url(fn_name: str) -> str:
    """Build Edge Function URL."""
    base = _SUPABASE_URL.rstrip("/")
    return f"{base}/functions/v1/{fn_name}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "apikey": _SUPABASE_KEY,
    }


# ── Shared HTTP session ──────────────────────────────────────────────────────

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=_TIMEOUT)
    return _session


async def close() -> None:
    """Close the HTTP session (call on shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# ── Core API ─────────────────────────────────────────────────────────────────


class SupabaseAI:
    """Client for the Supabase AI recommendation service."""

    @property
    def enabled(self) -> bool:
        return bool(_SUPABASE_URL and _SUPABASE_KEY)

    async def get_recommendations(
        self,
        user_id: int,
        limit: int = 10,
        log_ab: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Fetch hybrid AI recommendations for a user.

        Returns list of track dicts with:
            track_id, source_id, video_id, title, artist, genre,
            duration, cover_url, downloads, score, algo, components
        """
        if not self.enabled:
            logger.warning("Supabase AI not configured, returning empty recs")
            return []

        try:
            session = await _get_session()
            params = {"user_id": str(user_id), "limit": str(limit)}
            if log_ab:
                params["log_ab"] = "1"

            async with session.get(
                _fn_url("recommend"),
                headers=_headers(),
                params=params,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Recommend API error %d: %s", resp.status, text)
                    return []
                data = await resp.json()
                return data.get("recommendations", [])
        except Exception as e:
            logger.error("Recommend API failed: %s", e)
            return []

    async def ingest_event(
        self,
        event: str,
        user_id: int,
        track: dict[str, Any],
        listen_duration: int | None = None,
        source: str = "search",
        query: str | None = None,
    ) -> bool:
        """
        Send a listening event to Supabase.

        Args:
            event: "play" | "skip" | "like" | "dislike"
            user_id: Telegram user ID
            track: dict with source_id, title, artist, genre, etc.
            listen_duration: seconds actually listened
            source: "search" | "radio" | "automix" | "recommend" | "wave"
            query: search query (if applicable)

        Returns True on success.
        """
        if not self.enabled:
            return False

        try:
            session = await _get_session()
            payload: dict[str, Any] = {
                "event": event,
                "user_id": user_id,
                "track": track,
            }
            if listen_duration is not None:
                payload["listen_duration"] = listen_duration
            if source:
                payload["source"] = source
            if query:
                payload["query"] = query

            async with session.post(
                _fn_url("ingest"),
                headers=_headers(),
                json=payload,
            ) as resp:
                if resp.status != 200:
                    global _ingest_error_count
                    _ingest_error_count += 1
                    if _ingest_error_count <= 3 or _ingest_error_count % _INGEST_ERROR_LOG_INTERVAL == 0:
                        text = await resp.text()
                        logger.error("Ingest API error %d: %s (count=%d)", resp.status, text, _ingest_error_count)
                    return False
                return True
        except Exception as e:
            logger.error("Ingest API failed: %s", e)
            return False

    async def generate_ai_playlist(
        self,
        user_id: int,
        prompt: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Generate an AI playlist from a text prompt.

        Returns list of track dicts.
        """
        if not self.enabled:
            return []

        try:
            session = await _get_session()
            async with session.post(
                _fn_url("ai-playlist"),
                headers=_headers(),
                json={
                    "user_id": user_id,
                    "prompt": prompt,
                    "limit": limit,
                },
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("AI-playlist API error %d: %s", resp.status, text)
                    return []
                data = await resp.json()
                return data.get("playlist", [])
        except Exception as e:
            logger.error("AI-playlist API failed: %s", e)
            return []

    async def get_similar(
        self,
        track_id: int | None = None,
        source_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find tracks similar to a given track.

        Provide either track_id or source_id.
        """
        if not self.enabled:
            return []

        try:
            session = await _get_session()
            params: dict[str, str] = {"limit": str(limit)}
            if track_id:
                params["track_id"] = str(track_id)
            elif source_id:
                params["source_id"] = source_id
            else:
                return []

            async with session.get(
                _fn_url("similar"),
                headers=_headers(),
                params=params,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("similar", [])
        except Exception as e:
            logger.error("Similar API failed: %s", e)
            return []

    async def update_profile(self, user_id: int) -> bool:
        """Trigger user profile recalculation."""
        if not self.enabled:
            return False

        try:
            session = await _get_session()
            async with session.post(
                _fn_url("update-profile"),
                headers=_headers(),
                json={"user_id": user_id},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error("Update-profile API failed: %s", e)
            return False

    async def get_analytics(self, days: int = 7) -> dict[str, Any]:
        """Get AI system analytics and A/B test report."""
        if not self.enabled:
            return {}

        try:
            session = await _get_session()
            async with session.get(
                _fn_url("analytics"),
                headers=_headers(),
                params={"days": str(days)},
            ) as resp:
                if resp.status != 200:
                    return {}
                return await resp.json()
        except Exception as e:
            logger.error("Analytics API failed: %s", e)
            return {}

    async def log_recommendation_click(
        self,
        user_id: int,
        track_id: int | None = None,
        source_id: str | None = None,
    ) -> bool:
        """Log that a user clicked on a recommended track (for CTR)."""
        if not self.enabled:
            return False

        # This is done directly via Supabase REST (no Edge Function needed)
        try:
            session = await _get_session()
            base = _SUPABASE_URL.rstrip("/")
            # Update recommendation_log where user_id + track_id, set clicked=true
            url = f"{base}/rest/v1/recommendation_log"
            params = {
                "user_id": f"eq.{user_id}",
                "clicked": "eq.false",
            }
            if track_id:
                params["track_id"] = f"eq.{track_id}"

            async with session.patch(
                url,
                headers={**_headers(), "Prefer": "return=minimal"},
                params=params,
                json={"clicked": True},
            ) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            logger.error("Log click failed: %s", e)
            return False

    # ── New endpoints ────────────────────────────────────────────────────

    async def get_trending(
        self,
        hours: int = 24,
        limit: int = 20,
        genre: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get currently trending tracks by play velocity."""
        if not self.enabled:
            return []

        try:
            session = await _get_session()
            params: dict[str, str] = {
                "hours": str(hours),
                "limit": str(limit),
            }
            if genre:
                params["genre"] = genre

            async with session.get(
                _fn_url("trending"),
                headers=_headers(),
                params=params,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("trending", [])
        except Exception as e:
            logger.error("Trending API failed: %s", e)
            return []

    async def send_feedback(
        self,
        user_id: int,
        feedback: str,
        track_id: int | None = None,
        source_id: str | None = None,
        context: str | None = None,
    ) -> bool:
        """
        Send explicit user feedback.

        feedback: "like" | "dislike" | "skip" | "save" | "share" | "repeat"
        context:  "recommend" | "search" | "radio" | "playlist" | "trending"
        """
        if not self.enabled:
            return False

        try:
            session = await _get_session()
            payload: dict[str, Any] = {
                "user_id": user_id,
                "feedback": feedback,
            }
            if track_id:
                payload["track_id"] = track_id
            if source_id:
                payload["source_id"] = source_id
            if context:
                payload["context"] = context

            async with session.post(
                _fn_url("feedback"),
                headers=_headers(),
                json=payload,
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error("Feedback API failed: %s", e)
            return False

    async def search_catalog(
        self,
        query: str,
        limit: int = 20,
        genre: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search across the Supabase tracks catalog."""
        if not self.enabled:
            return []

        try:
            session = await _get_session()
            params: dict[str, str] = {
                "q": query,
                "limit": str(limit),
            }
            if genre:
                params["genre"] = genre

            async with session.get(
                _fn_url("search"),
                headers=_headers(),
                params=params,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("results", [])
        except Exception as e:
            logger.error("Search API failed: %s", e)
            return []

    async def get_taste_summary(self, user_id: int) -> dict[str, Any]:
        """Get rich user taste summary (top genres, artists, stats)."""
        if not self.enabled:
            return {}

        try:
            session = await _get_session()
            base = _SUPABASE_URL.rstrip("/")
            url = f"{base}/rest/v1/rpc/user_taste_summary"
            async with session.post(
                url,
                headers=_headers(),
                json={"p_user_id": user_id},
            ) as resp:
                if resp.status != 200:
                    return {}
                return await resp.json()
        except Exception as e:
            logger.error("Taste summary failed: %s", e)
            return {}

    async def health_check(self) -> dict[str, Any]:
        """Check Supabase connectivity and return basic stats."""
        if not self.enabled:
            return {"ok": False, "error": "Not configured"}

        try:
            session = await _get_session()
            base = _SUPABASE_URL.rstrip("/")
            url = f"{base}/rest/v1/tracks?select=id&limit=1"
            async with session.get(url, headers=_headers()) as resp:
                ok = resp.status == 200
                return {
                    "ok": ok,
                    "status": resp.status,
                    "url": _SUPABASE_URL,
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ── Singleton ────────────────────────────────────────────────────────────────

supabase_ai = SupabaseAI()
