const API_BASE = "/api";

function getHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": window.Telegram?.WebApp?.initData || "",
  };
}

export interface Track {
  video_id: string;
  title: string;
  artist: string;
  duration: number;
  duration_fmt: string;
  source: string;
  file_id?: string;
  cover_url?: string;
}

export interface PlayerState {
  current_track: Track | null;
  queue: Track[];
  position: number;
  is_playing: boolean;
  repeat_mode: string;
  shuffle: boolean;
}

export interface Playlist {
  id: number;
  name: string;
  track_count: number;
}

export async function fetchPlayerState(userId: number): Promise<PlayerState> {
  const r = await fetch(`${API_BASE}/player/state/${userId}`, { headers: getHeaders() });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`State ${r.status}: ${text || r.statusText}`);
  }
  return r.json();
}

export async function sendAction(action: string, trackId?: string, seekPos?: number, track?: Track): Promise<PlayerState> {
  const body: Record<string, unknown> = { action };
  if (trackId) body.track_id = trackId;
  if (seekPos !== undefined) body.position = seekPos;
  if (track) {
    body.track_title = track.title;
    body.track_artist = track.artist;
    body.track_duration = track.duration;
    body.track_source = track.source;
    body.track_cover_url = track.cover_url;
  }
  const r = await fetch(`${API_BASE}/player/action`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${r.status}: ${text || r.statusText}`);
  }
  return r.json();
}

export async function fetchPlaylists(userId: number): Promise<Playlist[]> {
  const r = await fetch(`${API_BASE}/playlists/${userId}`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Failed to fetch playlists");
  return r.json();
}

export async function fetchPlaylistTracks(playlistId: number): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/tracks`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Failed to fetch tracks");
  return r.json();
}

export async function fetchLyrics(trackId: string): Promise<string | null> {
  const r = await fetch(`${API_BASE}/lyrics/${trackId}`, { headers: getHeaders() });
  if (!r.ok) return null;
  const data = await r.json();
  return data.lyrics;
}

export async function searchTracks(query: string, limit = 10): Promise<Track[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const r = await fetch(`${API_BASE}/search?${params}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

export function getStreamUrl(videoId: string): string {
  const initData = encodeURIComponent(window.Telegram?.WebApp?.initData || "");
  return `${API_BASE}/stream/${videoId}?token=${initData}`;
}

export async function toggleFavorite(videoId: string): Promise<boolean> {
  const r = await fetch(`${API_BASE}/favorites/${videoId}`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to toggle favorite");
  const data = await r.json();
  return data.liked;
}

export async function checkFavorite(videoId: string): Promise<boolean> {
  const r = await fetch(`${API_BASE}/favorites/${videoId}`, { headers: getHeaders() });
  if (!r.ok) return false;
  const data = await r.json();
  return data.liked;
}

export async function reorderQueue(fromIndex: number, toIndex: number): Promise<PlayerState> {
  const r = await fetch(`${API_BASE}/player/reorder`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ from_index: fromIndex, to_index: toIndex }),
  });
  if (!r.ok) throw new Error("Failed to reorder");
  return r.json();
}

export async function fetchWave(userId: number, limit = 10): Promise<Track[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const r = await fetch(`${API_BASE}/wave/${userId}?${params}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}
