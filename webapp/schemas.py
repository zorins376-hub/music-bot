"""Pydantic schemas for TMA Player WebApp API."""
from typing import Optional

from pydantic import BaseModel


class TrackSchema(BaseModel):
    video_id: str
    title: str
    artist: str = "Unknown"
    duration: int = 0
    duration_fmt: str = "0:00"
    source: str = "youtube"
    file_id: Optional[str] = None
    cover_url: Optional[str] = None


class PlayerState(BaseModel):
    current_track: Optional[TrackSchema] = None
    queue: list[TrackSchema] = []
    position: int = 0  # current index in queue
    is_playing: bool = False
    repeat_mode: str = "off"  # off / one / all
    shuffle: bool = False


class PlayerAction(BaseModel):
    action: str  # play / pause / next / prev / seek / shuffle / repeat
    track_id: Optional[str] = None
    position: Optional[int] = None  # seek position in seconds
    track_title: Optional[str] = None
    track_artist: Optional[str] = None
    track_duration: Optional[int] = None
    track_source: Optional[str] = None
    track_cover_url: Optional[str] = None
    mode: Optional[str] = None  # "direct" = play without adding to queue


class PlaylistSchema(BaseModel):
    id: int
    name: str
    track_count: int = 0


class LyricsResponse(BaseModel):
    track_id: str
    lyrics: Optional[str] = None
    source: str = "genius"


class SearchRequest(BaseModel):
    q: str
    limit: int = 10


class SearchResult(BaseModel):
    tracks: list[TrackSchema]
    total: int = 0


class UserProfileSchema(BaseModel):
    id: int
    first_name: str = ""
    username: Optional[str] = None
    is_premium: bool = False
    is_admin: bool = False
    quality: str = "192"


class UserAudioSettingsSchema(BaseModel):
    quality: str


# ── Party Playlists ──────────────────────────────────────────────────────

class PartyTrackSchema(BaseModel):
    video_id: str
    title: str
    artist: str = "Unknown"
    duration: int = 0
    duration_fmt: str = "0:00"
    source: str = "youtube"
    cover_url: Optional[str] = None
    added_by: int = 0
    added_by_name: Optional[str] = None
    skip_votes: int = 0
    position: int = 0


class PartyMemberSchema(BaseModel):
    user_id: int
    display_name: Optional[str] = None
    role: str = "listener"
    is_online: bool = False


class PartyEventSchema(BaseModel):
    id: int
    event_type: str = "info"
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    message: str
    payload: Optional[dict] = None
    created_at: Optional[str] = None


class PartyChatMessageSchema(BaseModel):
    id: int
    user_id: int
    display_name: Optional[str] = None
    message: str
    created_at: Optional[str] = None


class PartyPlaybackStateSchema(BaseModel):
    track_position: int = 0
    action: str = "idle"
    seek_position: int = 0
    updated_by: Optional[int] = None
    updated_at: Optional[str] = None


class PartyRecapStatSchema(BaseModel):
    label: str
    value: int = 0


class PartyRecapSchema(BaseModel):
    total_tracks: int = 0
    total_members: int = 0
    online_members: int = 0
    total_duration: int = 0
    total_skip_votes: int = 0
    top_contributors: list[PartyRecapStatSchema] = []
    top_artists: list[PartyRecapStatSchema] = []
    events_count: int = 0


class PartyReactionRequest(BaseModel):
    emoji: str = "🔥"


class PartyChatRequest(BaseModel):
    message: str


class PartySchema(BaseModel):
    id: int
    invite_code: str
    creator_id: int
    name: str = "Party 🎉"
    is_active: bool = True
    current_position: int = 0
    track_count: int = 0
    tracks: list[PartyTrackSchema] = []
    member_count: int = 0
    skip_threshold: int = 3
    viewer_role: str = "listener"
    members: list[PartyMemberSchema] = []
    events: list[PartyEventSchema] = []
    chat_messages: list[PartyChatMessageSchema] = []
    playback: PartyPlaybackStateSchema = PartyPlaybackStateSchema()
    current_reactions: dict[str, int] = {}


class PartyAddTrackRequest(BaseModel):
    video_id: str
    title: str
    artist: str = "Unknown"
    duration: int = 0
    duration_fmt: str = "0:00"
    source: str = "youtube"
    cover_url: Optional[str] = None


class PartyCreateRequest(BaseModel):
    name: str = "Party 🎉"


class PartyReorderRequest(BaseModel):
    from_position: int
    to_position: int


class PartyPlaybackRequest(BaseModel):
    action: str
    track_position: int = 0
    seek_position: int = 0


class PartyRoleUpdateRequest(BaseModel):
    role: str
