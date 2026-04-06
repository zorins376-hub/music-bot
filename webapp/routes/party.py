"""
Party Playlists — collaborative listening rooms.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import json
import math
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select

from bot.config import settings
from bot.models.base import async_session
from bot.models.party import (
    PartyChatMessage,
    PartyEvent,
    PartyMember,
    PartyPlaybackState,
    PartyReaction,
    PartySession,
    PartyTrack,
    PartyTrackVote,
)
from webapp.auth import verify_init_data
from webapp.deps import _get_or_create_webapp_user, get_current_user, logger
from webapp.schemas import (
    PartyChatMessageSchema,
    PartyChatRequest,
    PartyAddTrackRequest,
    PartyCreateRequest,
    PartyEventSchema,
    PartyMemberSchema,
    PartyPlaybackRequest,
    PartyPlaybackStateSchema,
    PartyReactionRequest,
    PartyRecapSchema,
    PartyRecapStatSchema,
    PartyReorderRequest,
    PartyRoleUpdateRequest,
    PartySchema,
    PartyTrackSchema,
    PlaylistSchema,
    TrackSchema,
)

router = APIRouter(tags=["party"])

# In-memory SSE subscribers: invite_code -> list[asyncio.Queue]
_party_subscribers: dict[str, list[asyncio.Queue]] = {}
_PARTY_MEMBER_TOUCH_INTERVAL = timedelta(seconds=30)


def _party_skip_threshold(member_count: int) -> int:
    if member_count <= 1:
        return 1
    if member_count <= 3:
        return 2
    return min(5, max(3, math.ceil(member_count * 0.5)))


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


async def _record_party_event(
    session,
    party_id: int,
    event_type: str,
    message: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    payload: dict | None = None,
):
    session.add(
        PartyEvent(
            party_id=party_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            message=message[:500],
            payload=payload,
        )
    )


async def _get_party_or_404(session, code: str) -> PartySession:
    result = await session.execute(
        select(PartySession).where(
            PartySession.invite_code == code,
            PartySession.is_active == True,
        )
    )
    party = result.scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


async def _ensure_party_member(session, party: PartySession, user: dict, *, mark_online: bool) -> PartyMember:
    user_id = int(user["id"])
    name = user.get("first_name") or user.get("username") or f"User {user_id}"
    result = await session.execute(
        select(PartyMember).where(
            PartyMember.party_id == party.id,
            PartyMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if member is None:
        member = PartyMember(
            party_id=party.id,
            user_id=user_id,
            display_name=name,
            role="dj" if party.creator_id == user_id else "listener",
            is_online=mark_online,
            joined_at=now,
            last_seen_at=now,
        )
        session.add(member)
    else:
        if member.display_name != name:
            member.display_name = name
        if party.creator_id == user_id:
            member.role = "dj"
        should_touch_presence = mark_online or member.last_seen_at is None
        if not should_touch_presence and member.last_seen_at is not None:
            should_touch_presence = (now - member.last_seen_at) >= _PARTY_MEMBER_TOUCH_INTERVAL
        if should_touch_presence:
            member.last_seen_at = now
        if mark_online and not member.is_online:
            member.is_online = True
    return member


async def _get_or_create_party_playback(session, party_id: int) -> PartyPlaybackState:
    result = await session.execute(select(PartyPlaybackState).where(PartyPlaybackState.party_id == party_id))
    playback = result.scalar_one_or_none()
    if playback is None:
        playback = PartyPlaybackState(party_id=party_id)
        session.add(playback)
        await session.flush()
    return playback


async def _get_party_playback(session, party_id: int) -> PartyPlaybackState | None:
    result = await session.execute(select(PartyPlaybackState).where(PartyPlaybackState.party_id == party_id))
    return result.scalar_one_or_none()


async def _normalize_party_positions(session, party_id: int):
    tracks = (
        await session.execute(
            select(PartyTrack)
            .where(PartyTrack.party_id == party_id)
            .order_by(PartyTrack.position, PartyTrack.id)
        )
    ).scalars().all()
    changed = False
    for idx, track in enumerate(tracks):
        if track.position != idx:
            track.position = idx
            changed = True
    return changed


async def _build_party_schema(session, party: PartySession, viewer_id: int | None = None) -> PartySchema:
    tracks = (
        await session.execute(
            select(PartyTrack)
            .where(PartyTrack.party_id == party.id)
            .order_by(PartyTrack.position, PartyTrack.id)
        )
    ).scalars().all()
    track_ids = [t.id for t in tracks]
    vote_counts: dict[int, int] = {}
    reaction_counts: dict[str, int] = {}
    if track_ids:
        rows = await session.execute(
            select(PartyTrackVote.track_id, func.count())
            .where(
                PartyTrackVote.track_id.in_(track_ids),
                PartyTrackVote.vote_type == "skip",
            )
            .group_by(PartyTrackVote.track_id)
        )
        vote_counts = {track_id: count for track_id, count in rows.all()}

    current_track = next((t for t in tracks if t.position == party.current_position), None)
    if current_track is not None:
        reaction_rows = await session.execute(
            select(PartyReaction.emoji, func.count())
            .where(PartyReaction.track_id == current_track.id)
            .group_by(PartyReaction.emoji)
        )
        reaction_counts = {emoji: count for emoji, count in reaction_rows.all()}

    members = (
        await session.execute(
            select(PartyMember)
            .where(PartyMember.party_id == party.id)
            .order_by(PartyMember.is_online.desc(), PartyMember.joined_at.asc())
        )
    ).scalars().all()
    events = (
        await session.execute(
            select(PartyEvent)
            .where(PartyEvent.party_id == party.id)
            .order_by(PartyEvent.created_at.desc())
            .limit(12)
        )
    ).scalars().all()
    events = list(reversed(events))
    chat_messages = (
        await session.execute(
            select(PartyChatMessage)
            .where(PartyChatMessage.party_id == party.id)
            .order_by(PartyChatMessage.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    chat_messages = list(reversed(chat_messages))

    playback = await _get_party_playback(session, party.id)
    online_count = sum(1 for member in members if member.is_online)
    viewer_role = "listener"
    if viewer_id is not None:
        if viewer_id == party.creator_id:
            viewer_role = "dj"
        else:
            viewer_member = next((m for m in members if m.user_id == viewer_id), None)
            if viewer_member:
                viewer_role = viewer_member.role

    # Compute real-time seek position: stored position + elapsed time since last sync
    _raw_seek = (playback.seek_position if playback is not None else 0) or 0
    if (
        playback is not None
        and playback.action == "play"
        and playback.updated_at is not None
    ):
        elapsed = (datetime.now(timezone.utc) - playback.updated_at.replace(tzinfo=timezone.utc)).total_seconds()
        _raw_seek = _raw_seek + max(0, elapsed)

    return PartySchema(
        id=party.id,
        invite_code=party.invite_code,
        creator_id=party.creator_id,
        name=party.name,
        is_active=party.is_active,
        current_position=party.current_position,
        member_count=online_count,
        skip_threshold=_party_skip_threshold(online_count),
        viewer_role=viewer_role,
        members=[
            PartyMemberSchema(
                user_id=m.user_id,
                display_name=m.display_name,
                role=m.role,
                is_online=bool(m.is_online),
            )
            for m in members
        ],
        events=[
            PartyEventSchema(
                id=e.id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                actor_name=e.actor_name,
                message=e.message,
                payload=e.payload,
                created_at=_iso_dt(e.created_at),
            )
            for e in events
        ],
        chat_messages=[
            PartyChatMessageSchema(
                id=message.id,
                user_id=message.user_id,
                display_name=message.display_name,
                message=message.message,
                created_at=_iso_dt(message.created_at),
            )
            for message in chat_messages
        ],
        playback=PartyPlaybackStateSchema(
            track_position=playback.track_position if playback is not None else 0,
            action=playback.action if playback is not None else "idle",
            seek_position=_raw_seek,
            updated_by=playback.updated_by if playback is not None else None,
            updated_at=_iso_dt(playback.updated_at) if playback is not None else None,
        ),
        current_reactions=reaction_counts,
        tracks=[
            PartyTrackSchema(
                video_id=t.video_id,
                title=t.title,
                artist=t.artist,
                duration=t.duration,
                duration_fmt=t.duration_fmt,
                source=t.source,
                cover_url=t.cover_url,
                added_by=t.added_by,
                added_by_name=t.added_by_name,
                skip_votes=vote_counts.get(t.id, 0),
                position=t.position,
            )
            for t in tracks
        ],
    )


async def _get_party_with_tracks(code: str, viewer_id: int | None = None) -> PartySchema:
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        return await _build_party_schema(session, party, viewer_id)


async def _commit_and_build_party_schema(
    session,
    party: PartySession,
    viewer_id: int | None = None,
) -> PartySchema:
    if session.new or session.dirty or session.deleted:
        await session.commit()
    return await _build_party_schema(session, party, viewer_id)


async def _notify_party(code: str, event: str, data: dict | None = None):
    subs = _party_subscribers.get(code, [])
    payload = json.dumps({"event": event, "data": data or {}}, ensure_ascii=False)
    dead: list[asyncio.Queue] = []
    for q in subs:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            subs.remove(q)
        except ValueError:
            pass


async def _notify_party_state(code: str, event: str, data: dict | None = None):
    await _notify_party(code, event, data)


@router.post("/api/party", response_model=PartySchema)
async def create_party(body: PartyCreateRequest, user: dict = Depends(get_current_user)):
    await _get_or_create_webapp_user(user)
    code = secrets.token_urlsafe(8)[:10]
    async with async_session() as session:
        count_result = await session.execute(
            select(func.count()).where(
                PartySession.creator_id == user["id"],
                PartySession.is_active == True,
            )
        )
        if (count_result.scalar() or 0) >= 3:
            raise HTTPException(status_code=400, detail="Max 3 active parties")

        party = PartySession(
            invite_code=code,
            creator_id=user["id"],
            name=body.name[:100],
        )
        session.add(party)
        await session.flush()
        await _ensure_party_member(session, party, user, mark_online=False)
        await _get_or_create_party_playback(session, party.id)
        await _record_party_event(
            session,
            party.id,
            "party_created",
            f"{user.get('first_name', 'DJ')} создал пати",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    return party_schema


@router.get("/api/party/{code}", response_model=PartySchema)
async def get_party(code: str, user: dict = Depends(get_current_user)):
    await _get_or_create_webapp_user(user)
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))
    return party_schema


@router.post("/api/party/{code}/tracks", response_model=PartySchema)
async def add_party_track(code: str, body: PartyAddTrackRequest, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)

        existing_dup = await session.execute(
            select(PartyTrack.id).where(
                PartyTrack.party_id == party.id,
                PartyTrack.video_id == body.video_id,
                PartyTrack.position >= party.current_position,
            ).limit(1)
        )
        if existing_dup.scalar() is not None:
            raise HTTPException(status_code=409, detail="Track already in queue")

        max_pos_result = await session.execute(
            select(func.coalesce(func.max(PartyTrack.position), -1))
            .where(PartyTrack.party_id == party.id)
        )
        max_pos = max_pos_result.scalar() or 0

        track = PartyTrack(
            party_id=party.id,
            video_id=body.video_id,
            title=body.title,
            artist=body.artist,
            duration=body.duration,
            duration_fmt=body.duration_fmt,
            source=body.source,
            cover_url=body.cover_url,
            added_by=user["id"],
            added_by_name=user.get("first_name", "User"),
            position=max_pos + 1,
        )
        session.add(track)
        await session.flush()
        await _record_party_event(
            session,
            party.id,
            "track_added",
            f"{user.get('first_name', 'User')} добавил(а) {body.title}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"video_id": body.video_id, "title": body.title},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "track_added", {
        "video_id": body.video_id,
        "title": body.title,
        "artist": body.artist,
        "added_by_name": user.get("first_name", "User"),
    })
    return party_schema


@router.post("/api/party/{code}/tracks/{video_id}/play-next", response_model=PartySchema)
async def play_next_party_track(code: str, video_id: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can reorder tracks")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        target = next((t for t in tracks if t.video_id == video_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Track not found")
        if target.position <= party.current_position:
            raise HTTPException(status_code=400, detail="Track is already playing or finished")

        upcoming = [t for t in tracks if t.position > party.current_position]
        upcoming = [t for t in upcoming if t.video_id != video_id]
        upcoming.insert(0, target)
        start_pos = party.current_position + 1
        for idx, track in enumerate(upcoming):
            track.position = start_pos + idx
        await _record_party_event(
            session,
            party.id,
            "queue_reordered",
            f"{user.get('first_name', 'DJ')} перенёс(ла) {target.title} в play next",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"video_id": video_id, "mode": "play_next"},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "queue_reordered", {"video_id": video_id, "mode": "play_next"})
    return party_schema


@router.post("/api/party/{code}/reorder", response_model=PartySchema)
async def reorder_party_tracks(code: str, body: PartyReorderRequest, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can reorder tracks")
        if body.from_position <= party.current_position or body.to_position <= party.current_position:
            raise HTTPException(status_code=400, detail="Only upcoming tracks can be reordered")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        upcoming = [t for t in tracks if t.position > party.current_position]
        from_index = next((idx for idx, track in enumerate(upcoming) if track.position == body.from_position), None)
        to_index = next((idx for idx, track in enumerate(upcoming) if track.position == body.to_position), None)
        if from_index is None or to_index is None:
            raise HTTPException(status_code=404, detail="Track position not found")

        track = upcoming.pop(from_index)
        upcoming.insert(to_index, track)
        start_pos = party.current_position + 1
        for idx, queued_track in enumerate(upcoming):
            queued_track.position = start_pos + idx

        await _record_party_event(
            session,
            party.id,
            "queue_reordered",
            f"{user.get('first_name', 'DJ')} изменил(а) порядок очереди",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"from_position": body.from_position, "to_position": body.to_position},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "queue_reordered", {"from_position": body.from_position, "to_position": body.to_position})
    return party_schema


@router.delete("/api/party/{code}/tracks/{video_id}")
async def remove_party_track(code: str, video_id: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can remove tracks")

        track = (
            await session.execute(
                select(PartyTrack).where(
                    PartyTrack.party_id == party.id,
                    PartyTrack.video_id == video_id,
                )
            )
        ).scalar_one_or_none()
        if track is None:
            raise HTTPException(status_code=404, detail="Track not found")

        await session.execute(delete(PartyTrackVote).where(PartyTrackVote.track_id == track.id))
        removed_position = track.position
        await session.execute(delete(PartyTrack).where(PartyTrack.id == track.id))
        if removed_position < party.current_position:
            party.current_position = max(0, party.current_position - 1)
        await _normalize_party_positions(session, party.id)
        await _record_party_event(
            session,
            party.id,
            "track_removed",
            f"{user.get('first_name', 'DJ')} удалил(а) {track.title}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"video_id": video_id},
        )
        await session.commit()

    await _notify_party_state(code, "track_removed", {"video_id": video_id})
    return {"ok": True}


@router.post("/api/party/{code}/skip")
async def skip_party_track(code: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        can_control = member.role in {"dj", "cohost"} or party.creator_id == user["id"]

        track_result = await session.execute(
            select(PartyTrack).where(
                PartyTrack.party_id == party.id,
                PartyTrack.position == party.current_position,
            )
        )
        current_track = track_result.scalar_one_or_none()
        if current_track is None:
            raise HTTPException(status_code=400, detail="No active track")

        member_count = (
            await session.execute(
                select(func.count()).where(
                    PartyMember.party_id == party.id,
                    PartyMember.is_online == True,
                )
            )
        ).scalar() or 0
        threshold = _party_skip_threshold(int(member_count))

        skip = can_control
        votes = 0
        if not can_control:
            existing_vote = (
                await session.execute(
                    select(PartyTrackVote).where(
                        PartyTrackVote.track_id == current_track.id,
                        PartyTrackVote.user_id == user["id"],
                        PartyTrackVote.vote_type == "skip",
                    )
                )
            ).scalar_one_or_none()
            if existing_vote:
                raise HTTPException(status_code=400, detail="Already voted to skip")
            session.add(
                PartyTrackVote(
                    party_id=party.id,
                    track_id=current_track.id,
                    user_id=user["id"],
                    vote_type="skip",
                )
            )
            await session.flush()
            votes = (
                await session.execute(
                    select(func.count()).where(
                        PartyTrackVote.track_id == current_track.id,
                        PartyTrackVote.vote_type == "skip",
                    )
                )
            ).scalar() or 0
            skip = votes >= threshold
            await _record_party_event(
                session,
                party.id,
                "skip_vote",
                f"{user.get('first_name', 'User')} проголосовал(а) за skip",
                actor_id=user["id"],
                actor_name=user.get("first_name", "User"),
                payload={"votes": votes, "threshold": threshold},
            )

        if skip:
            await session.execute(delete(PartyTrackVote).where(PartyTrackVote.track_id == current_track.id))
            party.current_position += 1
            playback = await _get_or_create_party_playback(session, party.id)
            playback.track_position = party.current_position
            playback.action = "play"
            playback.seek_position = 0
            playback.updated_by = int(user["id"])
            playback.updated_at = datetime.now(timezone.utc)
            await _record_party_event(
                session,
                party.id,
                "next_track",
                f"{user.get('first_name', 'DJ')} переключил(а) следующий трек",
                actor_id=user["id"],
                actor_name=user.get("first_name", "DJ"),
                payload={"position": party.current_position},
            )

        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    if skip:
        await _notify_party_state(code, "next", {"position": party.current_position})
    else:
        await _notify_party_state(code, "vote_skip", {"votes": votes, "threshold": threshold})

    return party_schema


@router.post("/api/party/{code}/members/{member_user_id}/role", response_model=PartySchema)
async def update_party_member_role(
    code: str,
    member_user_id: int,
    body: PartyRoleUpdateRequest,
    user: dict = Depends(get_current_user),
):
    if body.role not in {"cohost", "listener"}:
        raise HTTPException(status_code=400, detail="Unsupported role")

    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        if party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ can change roles")
        if member_user_id == party.creator_id:
            raise HTTPException(status_code=400, detail="DJ role cannot be changed")

        target = (
            await session.execute(
                select(PartyMember).where(
                    PartyMember.party_id == party.id,
                    PartyMember.user_id == member_user_id,
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="Member not found")

        target.role = body.role
        await _record_party_event(
            session,
            party.id,
            "role_updated",
            f"{target.display_name or 'Участник'} теперь {body.role}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"user_id": member_user_id, "role": body.role},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "role_updated", {"user_id": member_user_id, "role": body.role})
    return party_schema


@router.post("/api/party/{code}/playback", response_model=PartySchema)
async def sync_party_playback(code: str, body: PartyPlaybackRequest, user: dict = Depends(get_current_user)):
    if body.action not in {"play", "pause", "seek"}:
        raise HTTPException(status_code=400, detail="Unsupported playback action")

    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can sync playback")

        playback = await _get_or_create_party_playback(session, party.id)
        playback.action = body.action
        playback.track_position = max(0, body.track_position)
        playback.seek_position = max(0, body.seek_position)
        playback.updated_by = int(user["id"])
        playback.updated_at = datetime.now(timezone.utc)
        if body.action == "play":
            party.current_position = max(0, body.track_position)

        await _record_party_event(
            session,
            party.id,
            "playback_sync",
            f"{user.get('first_name', 'DJ')} синхронизировал(а) playback: {body.action}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={
                "action": body.action,
                "track_position": body.track_position,
                "seek_position": body.seek_position,
            },
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(
        code,
        "playback_sync",
        {
            "action": body.action,
            "track_position": body.track_position,
            "seek_position": body.seek_position,
            "updated_by": user["id"],
        },
    )
    return party_schema


@router.post("/api/party/{code}/close")
async def close_party(code: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        if party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ can close")

        party.is_active = False
        await _record_party_event(
            session,
            party.id,
            "closed",
            f"{user.get('first_name', 'DJ')} завершил(а) пати",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
        )
        await session.commit()

    await _notify_party_state(code, "closed", {})
    _party_subscribers.pop(code, None)
    return {"ok": True}


@router.post("/api/party/{code}/save-playlist", response_model=PlaylistSchema)
async def save_party_as_playlist(code: str, user: dict = Depends(get_current_user)):
    from bot.db import upsert_track
    from bot.models.playlist import Playlist, PlaylistTrack

    await _get_or_create_webapp_user(user)
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        if not tracks:
            raise HTTPException(status_code=400, detail="Party queue is empty")

        playlist = Playlist(user_id=user["id"], name=f"Party • {party.name}"[:100])
        session.add(playlist)
        await session.flush()

        for idx, track in enumerate(tracks):
            db_track = await upsert_track(
                source_id=track.video_id,
                source=track.source,
                title=track.title,
                artist=track.artist,
                duration=track.duration,
                cover_url=track.cover_url,
            )
            session.add(PlaylistTrack(playlist_id=playlist.id, track_id=db_track.id, position=idx))

        await _record_party_event(
            session,
            party.id,
            "playlist_saved",
            f"{user.get('first_name', 'User')} сохранил(а) пати как плейлист",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"playlist_name": playlist.name},
        )
        await session.commit()

        cnt = (
            await session.execute(
                select(func.count(PlaylistTrack.id)).where(PlaylistTrack.playlist_id == playlist.id)
            )
        ).scalar() or 0

    await _notify_party_state(code, "playlist_saved", {"playlist_name": f"Party • {party.name}"[:100]})
    return PlaylistSchema(id=playlist.id, name=playlist.name, track_count=cnt)


@router.post("/api/party/{code}/chat", response_model=PartySchema)
async def send_party_chat_message(code: str, body: PartyChatRequest, user: dict = Depends(get_current_user)):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        session.add(
            PartyChatMessage(
                party_id=party.id,
                user_id=user["id"],
                display_name=user.get("first_name", "User"),
                message=message[:400],
            )
        )
        await _record_party_event(
            session,
            party.id,
            "chat",
            f"{user.get('first_name', 'User')}: {message[:180]}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"message": message[:400]},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat", {"message": message[:400], "actor_name": user.get("first_name", "User")})
    return party_schema


@router.delete("/api/party/{code}/chat/{message_id}", response_model=PartySchema)
async def delete_party_chat_message(code: str, message_id: int, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        message = (
            await session.execute(
                select(PartyChatMessage).where(
                    PartyChatMessage.party_id == party.id,
                    PartyChatMessage.id == message_id,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            raise HTTPException(status_code=404, detail="Chat message not found")
        can_moderate = member.role in {"dj", "cohost"} or party.creator_id == user["id"]
        if not can_moderate and message.user_id != user["id"]:
            raise HTTPException(status_code=403, detail="Not allowed to delete this message")

        deleted_preview = message.message[:120]
        await session.delete(message)
        await _record_party_event(
            session,
            party.id,
            "chat_delete",
            f"{user.get('first_name', 'User')} удалил(а) сообщение из чата",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"message_id": message_id, "preview": deleted_preview},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat_delete", {"message_id": message_id})
    return party_schema


@router.post("/api/party/{code}/chat/clear", response_model=PartySchema)
async def clear_party_chat(code: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can clear chat")

        await session.execute(
            PartyChatMessage.__table__.delete().where(PartyChatMessage.party_id == party.id)
        )
        await _record_party_event(
            session,
            party.id,
            "chat_clear",
            f"{user.get('first_name', 'User')} очистил(а) чат",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat_clear", {})
    return party_schema


@router.post("/api/party/{code}/react", response_model=PartySchema)
async def react_to_party_track(code: str, body: PartyReactionRequest, user: dict = Depends(get_current_user)):
    emoji = (body.emoji or "\U0001f525")[:8]
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        current_track = (
            await session.execute(
                select(PartyTrack).where(
                    PartyTrack.party_id == party.id,
                    PartyTrack.position == party.current_position,
                )
            )
        ).scalar_one_or_none()
        if current_track is None:
            raise HTTPException(status_code=400, detail="No active track")

        existing = (
            await session.execute(
                select(PartyReaction).where(
                    PartyReaction.track_id == current_track.id,
                    PartyReaction.user_id == user["id"],
                    PartyReaction.emoji == emoji,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                PartyReaction(
                    party_id=party.id,
                    track_id=current_track.id,
                    user_id=user["id"],
                    emoji=emoji,
                )
            )
            await _record_party_event(
                session,
                party.id,
                "reaction",
                f"{user.get('first_name', 'User')} отреагировал(а) {emoji}",
                actor_id=user["id"],
                actor_name=user.get("first_name", "User"),
                payload={"emoji": emoji, "video_id": current_track.video_id},
            )
            party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))
        else:
            party_schema = await _build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "reaction", {"emoji": emoji, "user_id": user["id"]})
    return party_schema


@router.post("/api/party/{code}/auto-dj", response_model=PartySchema)
async def auto_dj_fill_party(code: str, limit: int = Query(default=5, ge=1, le=10), user: dict = Depends(get_current_user)):
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can run Auto-DJ")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position.desc())
            )
        ).scalars().all()
        existing_ids = {t.video_id for t in tracks}
        seed_track = next((t for t in tracks if t.position == party.current_position), None) or (tracks[0] if tracks else None)

        suggestions: list[TrackSchema] = []
        if seed_track is not None and settings.SUPABASE_AI_ENABLED:
            from webapp.api import get_similar
            suggestions = (await get_similar(seed_track.video_id, limit=limit * 2, user=user)).tracks
        if not suggestions:
            from webapp.api import get_wave
            suggestions = (await get_wave(int(user["id"]), limit=limit * 2, mood=None, user=user)).tracks
        if not suggestions and seed_track is not None:
            from bot.services.downloader import search_tracks as _search_tracks
            raw_results = await _search_tracks(f"{seed_track.artist} similar", max_results=limit * 2, source="youtube")
            suggestions = [
                TrackSchema(
                    video_id=r.get("video_id", ""),
                    title=r.get("title", "Unknown"),
                    artist=r.get("artist", r.get("uploader", "Unknown")),
                    duration=r.get("duration", 0),
                    duration_fmt=r.get("duration_fmt", "0:00"),
                    source=r.get("source", "youtube"),
                    cover_url=r.get("cover_url"),
                )
                for r in raw_results
                if r.get("video_id")
            ]

        max_pos = (await session.execute(select(func.coalesce(func.max(PartyTrack.position), -1)).where(PartyTrack.party_id == party.id))).scalar() or -1
        added = 0
        for suggestion in suggestions:
            if suggestion.video_id in existing_ids:
                continue
            max_pos += 1
            session.add(
                PartyTrack(
                    party_id=party.id,
                    video_id=suggestion.video_id,
                    title=suggestion.title,
                    artist=suggestion.artist,
                    duration=suggestion.duration,
                    duration_fmt=suggestion.duration_fmt,
                    source=suggestion.source,
                    cover_url=suggestion.cover_url,
                    added_by=user["id"],
                    added_by_name="AI Auto-DJ",
                    position=max_pos,
                )
            )
            existing_ids.add(suggestion.video_id)
            added += 1
            if added >= limit:
                break

        if added == 0:
            raise HTTPException(status_code=400, detail="Auto-DJ found no new tracks")

        await _record_party_event(
            session,
            party.id,
            "auto_dj",
            f"{user.get('first_name', 'DJ')} включил(а) AI Auto-DJ (+{added} треков)",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"added": added},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "auto_dj", {"added": added})
    return party_schema


@router.get("/api/party/{code}/recap", response_model=PartyRecapSchema)
async def get_party_recap(code: str, user: dict = Depends(get_current_user)):
    async with async_session() as session:
        from collections import Counter

        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        tracks = (
            await session.execute(
                select(PartyTrack).where(PartyTrack.party_id == party.id)
            )
        ).scalars().all()
        members = (
            await session.execute(
                select(PartyMember).where(PartyMember.party_id == party.id)
            )
        ).scalars().all()
        events_count = (
            await session.execute(select(func.count(PartyEvent.id)).where(PartyEvent.party_id == party.id))
        ).scalar() or 0
        skip_votes = (
            await session.execute(select(func.count(PartyTrackVote.id)).where(PartyTrackVote.party_id == party.id, PartyTrackVote.vote_type == "skip"))
        ).scalar() or 0

        contributor_counter = Counter(t.added_by_name or "Unknown" for t in tracks)
        artist_counter = Counter(t.artist or "Unknown" for t in tracks)
        total_duration = sum(t.duration or 0 for t in tracks)

        return PartyRecapSchema(
            total_tracks=len(tracks),
            total_members=len(members),
            online_members=sum(1 for m in members if m.is_online),
            total_duration=total_duration,
            total_skip_votes=skip_votes,
            events_count=events_count,
            top_contributors=[PartyRecapStatSchema(label=label, value=value) for label, value in contributor_counter.most_common(3)],
            top_artists=[PartyRecapStatSchema(label=label, value=value) for label, value in artist_counter.most_common(3)],
        )


@router.get("/api/party/{code}/events")
async def party_events(
    code: str,
    request: Request,
    x_telegram_init_data: str | None = Header(None),
    token: str | None = Query(None),
):
    init_data = x_telegram_init_data or token
    if not init_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = verify_init_data(init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    await _get_or_create_webapp_user(user)
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=True)
        joined_message = None
        if member.display_name:
            joined_message = f"{member.display_name} присоединился(ась) к пати"
        await _record_party_event(
            session,
            party.id,
            "member_joined",
            joined_message or "Новый участник вошёл в комнату",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"user_id": user["id"]},
        )
        await session.commit()

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    if code not in _party_subscribers:
        _party_subscribers[code] = []
    _party_subscribers[code].append(queue)

    await _notify_party_state(code, "member_joined", {
        "user_id": user["id"],
        "name": user.get("first_name", "User"),
        "member_count": len(_party_subscribers.get(code, [])),
    })

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            subs = _party_subscribers.get(code, [])
            try:
                subs.remove(queue)
            except ValueError:
                pass
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(PartySession).where(PartySession.invite_code == code)
                    )
                    party = result.scalar_one_or_none()
                    if party is not None:
                        member = (
                            await session.execute(
                                select(PartyMember).where(
                                    PartyMember.party_id == party.id,
                                    PartyMember.user_id == user["id"],
                                )
                            )
                        ).scalar_one_or_none()
                        if member is not None:
                            member.is_online = False
                            member.last_seen_at = datetime.now(timezone.utc)
                        await _record_party_event(
                            session,
                            party.id,
                            "member_left",
                            f"{user.get('first_name', 'User')} вышел(шла) из комнаты",
                            actor_id=user["id"],
                            actor_name=user.get("first_name", "User"),
                            payload={"user_id": user["id"]},
                        )
                        await session.commit()
            except Exception:
                pass
            await _notify_party_state(code, "member_left", {
                "member_count": len(_party_subscribers.get(code, [])),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/my-parties", response_model=list[PartySchema])
async def my_parties(user: dict = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(PartySession).where(
                PartySession.creator_id == user["id"],
                PartySession.is_active == True,
            ).order_by(PartySession.created_at.desc())
        )
        parties = result.scalars().all()
        if not parties:
            return []

        party_ids = [party.id for party in parties]
        track_rows = await session.execute(
            select(PartyTrack.party_id, func.count(PartyTrack.id))
            .where(PartyTrack.party_id.in_(party_ids))
            .group_by(PartyTrack.party_id)
        )
        track_counts = {party_id: count for party_id, count in track_rows.all()}

        member_rows = await session.execute(
            select(PartyMember.party_id, func.count(PartyMember.id))
            .where(
                PartyMember.party_id.in_(party_ids),
                PartyMember.is_online == True,
            )
            .group_by(PartyMember.party_id)
        )
        online_counts = {party_id: count for party_id, count in member_rows.all()}

        return [
            PartySchema(
                id=party.id,
                invite_code=party.invite_code,
                creator_id=party.creator_id,
                name=party.name,
                is_active=party.is_active,
                current_position=party.current_position,
                track_count=int(track_counts.get(party.id, 0)),
                tracks=[],
                member_count=int(online_counts.get(party.id, 0)),
                skip_threshold=_party_skip_threshold(int(online_counts.get(party.id, 0))),
                viewer_role="dj",
                members=[],
                events=[],
                chat_messages=[],
                playback=PartyPlaybackStateSchema(),
                current_reactions={},
            )
            for party in parties
        ]
