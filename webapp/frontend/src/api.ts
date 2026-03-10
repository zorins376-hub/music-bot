const API_BASE = "/api";

function getHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": window.Telegram.WebApp.initData,
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
  if (!r.ok) throw new Error("Failed to fetch state");
  return r.json();
}

export async function sendAction(action: string, trackId?: string, seekPos?: number): Promise<PlayerState> {
  const body: Record<string, unknown> = { action };
  if (trackId) body.track_id = trackId;
  if (seekPos !== undefined) body.position = seekPos;
  const r = await fetch(`${API_BASE}/player/action`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("Action failed");
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
  const initData = encodeURIComponent(window.Telegram.WebApp.initData);
  return `${API_BASE}/stream/${videoId}?token=${initData}`;
}
