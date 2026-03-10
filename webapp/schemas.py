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
