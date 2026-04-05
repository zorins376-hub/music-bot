"""
Gamification — event ingestion, feedback, music battles, activity feed.
Extracted from webapp/api.py for modularity.
"""
import logging
import random

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from bot.config import settings
from webapp.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gamification"])


# ── Request models ───────────────────────────────────────────────────────

class IngestEventRequest(BaseModel):
    event: str  # "play" | "skip" | "like" | "dislike"
    track: dict
    listen_duration: int | None = None
    source: str = "wave"


class FeedbackRequest(BaseModel):
    feedback: str  # "like" | "dislike" | "skip" | "save" | "share" | "repeat"
    source_id: str | None = None
    context: str | None = None


@router.post("/api/ingest")
async def ingest_event(body: IngestEventRequest, user: dict = Depends(get_current_user)):
    """Send a play/skip/like event, upsert track in DB, record listening history."""
    user_id = int(user.get("id", 0))
    track_info = body.track or {}
    source_id = track_info.get("source_id") or ""

    # --- Upsert track & record listening history ---
    track_db_id: int | None = None
    try:
        from bot.db import upsert_track, record_listening_event
        if source_id:
            db_track = await upsert_track(
                source_id=source_id,
                title=track_info.get("title"),
                artist=track_info.get("artist"),
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                source=track_info.get("source", "youtube"),
                cover_url=track_info.get("cover_url"),
            )
            track_db_id = db_track.id
        await record_listening_event(
            user_id=user_id,
            track_id=track_db_id,
            query=track_info.get("title"),
            action=body.event,
            source=body.source,
            listen_duration=body.listen_duration,
        )
    except Exception as exc:
        import logging
        logging.getLogger("webapp.ingest").warning("ingest DB error user=%s: %s", user_id, exc)

    # --- Gamification: award XP for like/dislike (play XP handled in record_listening_event) ---
    try:
        from bot.models.base import async_session
        from bot.models.user import User
        from sqlalchemy import select, update
        from datetime import date as dt_date
        xp_map = {"like": 5, "dislike": 1}
        xp_gain = xp_map.get(body.event, 0)
        if xp_gain > 0:
            async with async_session() as session:
                q = await session.execute(select(User).where(User.id == user["id"]))
                u = q.scalar()
                if u:
                    u.xp = (u.xp or 0) + xp_gain
                    u.level = max(1, ((u.xp or 0) // 100) + 1)
                    badges = list(u.badges or [])
                    if "meloman" not in badges and (u.xp or 0) >= 200:
                        badges.append("meloman")
                    u.badges = badges
                    await session.commit()
    except Exception:
        pass

    if not settings.SUPABASE_AI_ENABLED:
        return {"ok": True}
    from bot.services.supabase_ai import supabase_ai
    ok = await supabase_ai.ingest_event(
        event=body.event,
        user_id=user_id,
        track=body.track,
        listen_duration=body.listen_duration,
        source=body.source,
    )
    return {"ok": ok}


@router.post("/api/feedback")
async def send_feedback(body: FeedbackRequest, user: dict = Depends(get_current_user)):
    """Send explicit like/dislike feedback to Supabase AI."""
    if not settings.SUPABASE_AI_ENABLED:
        return {"ok": False, "reason": "AI not enabled"}
    from bot.services.supabase_ai import supabase_ai
    ok = await supabase_ai.send_feedback(
        user_id=user["id"],
        feedback=body.feedback,
        source_id=body.source_id,
        context=body.context,
    )
    return {"ok": ok}


@router.post("/api/battle/start")
async def start_battle(user: dict = Depends(get_current_user)):
    """Start a music quiz battle — returns 5 rounds with audio snippets and 4 answer choices."""
    from bot.models.base import async_session
    from bot.models.track import Track
    from sqlalchemy import select, func

    async with async_session() as session:
        q = await session.execute(
            select(Track).where(Track.downloads > 0, Track.title.isnot(None), Track.artist.isnot(None))
            .order_by(func.random()).limit(50)
        )
        all_tracks = q.scalars().all()

    if len(all_tracks) < 8:
        raise HTTPException(status_code=400, detail="Not enough tracks for a battle")

    rounds = []
    used = set()
    for i in range(min(5, len(all_tracks) // 4)):
        correct = None
        for t in all_tracks:
            if t.source_id not in used:
                correct = t
                used.add(t.source_id)
                break
        if not correct:
            break

        wrong = [t for t in all_tracks if t.source_id not in used and t.source_id != correct.source_id]
        random.shuffle(wrong)
        wrong = wrong[:3]
        for w in wrong:
            used.add(w.source_id)

        options = [{"title": correct.title, "artist": correct.artist, "video_id": correct.source_id}]
        for w in wrong:
            options.append({"title": w.title, "artist": w.artist, "video_id": w.source_id})
        random.shuffle(options)

        correct_idx = next(i for i, o in enumerate(options) if o["video_id"] == correct.source_id)

        rounds.append({
            "round": i + 1,
            "stream_id": correct.source_id,
            "correct_idx": correct_idx,
            "options": options,
            "cover_url": correct.cover_url,
        })

    return {"rounds": rounds, "total": len(rounds)}


@router.post("/api/battle/score")
async def submit_battle_score(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Submit battle score — awards XP based on correct answers."""
    correct = body.get("correct", 0)
    total = body.get("total", 5)
    user_id = user["id"]

    xp_earned = correct * 15
    if correct == total:
        xp_earned += 25

    try:
        from bot.services.leaderboard import add_xp
        await add_xp(user_id, xp_earned)
    except Exception:
        pass

    return {"correct": correct, "total": total, "xp_earned": xp_earned}


@router.get("/api/challenges/{user_id}")
async def user_challenges(user_id: int, user: dict = Depends(get_current_user)):
    """Get active weekly challenges and user's progress."""
    try:
        from bot.services.challenges import get_user_challenges
        return await get_user_challenges(user_id)
    except Exception as exc:
        logger.error("Challenges failed for user %s: %s", user_id, exc)
        return {"challenges": [], "week": ""}
