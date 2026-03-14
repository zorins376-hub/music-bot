const API_BASE = "/api";

function getHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": window.Telegram?.WebApp?.initData || "",
  };
}

// ── Resilient fetch with timeout + retry ────────────────────────────────

const DEFAULT_TIMEOUT = 15_000; // 15s
const STREAM_TIMEOUT = 60_000; // 60s for stream/download

async function fetchWithTimeout(
  input: RequestInfo,
  init?: RequestInit & { timeout?: number },
): Promise<Response> {
  const timeout = init?.timeout ?? DEFAULT_TIMEOUT;
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  // If caller provided an external signal, forward its abort
  if (init?.signal) {
    init.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  try {
    const resp = await fetch(input, { ...init, signal: controller.signal });
    return resp;
  } finally {
    clearTimeout(id);
  }
}

async function fetchWithRetry(
  input: RequestInfo,
  init?: RequestInit & { timeout?: number; retries?: number },
): Promise<Response> {
  const retries = init?.retries ?? 1;
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fetchWithTimeout(input, init);
    } catch (e: unknown) {
      lastError = e;
      // Only retry on network / timeout errors, not HTTP errors
      if (e instanceof DOMException && e.name === "AbortError") {
        if (attempt < retries) continue;
        throw new Error("Request timed out");
      }
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
        continue;
      }
    }
  }
  throw lastError;
}

// ── Network status ──────────────────────────────────────────────────────

let _isOnline = navigator.onLine;
const _onlineListeners: Array<(online: boolean) => void> = [];

window.addEventListener("online", () => { _isOnline = true; _onlineListeners.forEach((l) => l(true)); });
window.addEventListener("offline", () => { _isOnline = false; _onlineListeners.forEach((l) => l(false)); });

export function isOnline(): boolean { return _isOnline; }
export function onNetworkChange(cb: (online: boolean) => void): () => void {
  _onlineListeners.push(cb);
  return () => { const i = _onlineListeners.indexOf(cb); if (i >= 0) _onlineListeners.splice(i, 1); };
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

export type EqPreset = "flat" | "bass" | "vocal" | "club" | "bright" | "night" | "soft" | "techno" | "vocal_boost";

export interface UserProfile {
  id: number;
  first_name: string;
  username?: string;
  is_premium: boolean;
  is_admin: boolean;
  quality: string;
}

export async function fetchPlayerState(userId: number): Promise<PlayerState> {
  const r = await fetchWithRetry(`${API_BASE}/player/state/${userId}`, { headers: getHeaders(), retries: 2 });
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
  const r = await fetchWithRetry(`${API_BASE}/player/action`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(body),
    retries: 1,
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

export async function fetchUserProfile(): Promise<UserProfile> {
  const r = await fetch(`${API_BASE}/user/me`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Failed to fetch user profile");
  return r.json();
}

export async function updateUserAudioSettings(quality: string): Promise<UserProfile> {
  const r = await fetch(`${API_BASE}/user/audio-settings`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ quality }),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(text || "Failed to update audio settings");
  }
  return r.json();
}

export async function fetchPlaylistTracks(playlistId: number): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/tracks`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Failed to fetch tracks");
  return r.json();
}

export async function playPlaylist(playlistId: number): Promise<PlayerState> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/play`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to play playlist");
  return r.json();
}

export async function fetchLyrics(trackId: string): Promise<string | null> {
  const r = await fetch(`${API_BASE}/lyrics/${trackId}`, { headers: getHeaders() });
  if (!r.ok) return null;
  const data = await r.json();
  return data.lyrics;
}

export async function searchTracks(query: string, limit = 10, signal?: AbortSignal): Promise<Track[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const r = await fetchWithTimeout(`${API_BASE}/search?${params}`, { headers: getHeaders(), timeout: 20_000, signal });
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

export async function fetchWave(userId: number, limit = 10, mood: string | null = null): Promise<Track[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (mood) {
    params.set("mood", mood);
  }
  const r = await fetch(`${API_BASE}/wave/${userId}?${params}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

// ── Charts ──────────────────────────────────────────────────────────────

export interface ChartSource {
  id: string;
  label: string;
}

export async function fetchChartSources(): Promise<ChartSource[]> {
  const r = await fetch(`${API_BASE}/charts`, { headers: getHeaders() });
  if (!r.ok) return [];
  return r.json();
}

export async function fetchChart(source: string, limit = 100): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/charts/${source}?limit=${limit}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

// ── Playlist CRUD ───────────────────────────────────────────────────────

export async function createPlaylist(name: string): Promise<Playlist> {
  const r = await fetch(`${API_BASE}/playlists`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error("Failed to create playlist");
  return r.json();
}

export async function addTrackToPlaylist(playlistId: number, track: Track): Promise<Playlist> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/tracks`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      video_id: track.video_id,
      title: track.title,
      artist: track.artist,
      duration: track.duration,
      source: track.source,
      cover_url: track.cover_url,
    }),
  });
  if (!r.ok) throw new Error("Failed to add track");
  return r.json();
}

export async function removeTrackFromPlaylist(playlistId: number, videoId: string): Promise<void> {
  await fetch(`${API_BASE}/playlist/${playlistId}/tracks/${videoId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
}

export async function renamePlaylist(playlistId: number, name: string): Promise<void> {
  await fetch(`${API_BASE}/playlist/${playlistId}`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify({ name }),
  });
}

export async function deletePlaylist(playlistId: number): Promise<void> {
  await fetch(`${API_BASE}/playlist/${playlistId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
}

// ── Supabase AI ─────────────────────────────────────────────────────────

export async function ingestEvent(
  event: "play" | "skip" | "like" | "dislike",
  track: Track,
  listenDuration?: number,
  source: string = "wave",
): Promise<void> {
  fetch(`${API_BASE}/ingest`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      event,
      track: {
        source_id: track.video_id,
        title: track.title,
        artist: track.artist,
        duration: track.duration,
        source: track.source,
      },
      listen_duration: listenDuration,
      source,
    }),
  }).catch(() => {}); // fire-and-forget
}

export async function sendFeedback(
  feedback: "like" | "dislike",
  sourceId: string,
  context: string = "player",
): Promise<void> {
  fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ feedback, source_id: sourceId, context }),
  }).catch(() => {});
}

export async function fetchSimilar(videoId: string, limit = 10): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/similar/${videoId}?limit=${limit}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

export async function generateAiPlaylist(prompt: string, limit = 10): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/ai-playlist`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ prompt, limit }),
  });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

export async function fetchTrending(hours = 24, limit = 20): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/trending?hours=${hours}&limit=${limit}`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

// ── Party Playlists ─────────────────────────────────────────────────────

export interface PartyTrack extends Track {
  added_by: number;
  added_by_name?: string;
  skip_votes: number;
  position: number;
}

export interface PartyMember {
  user_id: number;
  display_name?: string;
  role: string;
  is_online: boolean;
}

export interface PartyEvent {
  id: number;
  event_type: string;
  actor_id?: number;
  actor_name?: string;
  message: string;
  payload?: Record<string, unknown>;
  created_at?: string;
}

export interface PartyChatMessage {
  id: number;
  user_id: number;
  display_name?: string;
  message: string;
  created_at?: string;
}

export interface PartyPlaybackState {
  track_position: number;
  action: string;
  seek_position: number;
  updated_by?: number;
  updated_at?: string;
}

export interface PartyRecapStat {
  label: string;
  value: number;
}

export interface PartyRecap {
  total_tracks: number;
  total_members: number;
  online_members: number;
  total_duration: number;
  total_skip_votes: number;
  events_count: number;
  top_contributors: PartyRecapStat[];
  top_artists: PartyRecapStat[];
}

export interface Party {
  id: number;
  invite_code: string;
  creator_id: number;
  name: string;
  is_active: boolean;
  current_position: number;
  track_count?: number;
  tracks: PartyTrack[];
  member_count: number;
  skip_threshold: number;
  viewer_role: string;
  members: PartyMember[];
  events: PartyEvent[];
  chat_messages: PartyChatMessage[];
  playback: PartyPlaybackState;
  current_reactions: Record<string, number>;
}

export async function createParty(name = "Party 🎉"): Promise<Party> {
  const r = await fetch(`${API_BASE}/party`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error("Failed to create party");
  return r.json();
}

export async function fetchParty(code: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Party not found");
  return r.json();
}

export async function addPartyTrack(code: string, track: Track): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/tracks`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({
      video_id: track.video_id,
      title: track.title,
      artist: track.artist,
      duration: track.duration,
      duration_fmt: track.duration_fmt,
      source: track.source,
      cover_url: track.cover_url,
    }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

export async function removePartyTrack(code: string, videoId: string): Promise<void> {
  await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/tracks/${encodeURIComponent(videoId)}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
}

export async function skipPartyTrack(code: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/skip`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to skip");
  return r.json();
}

export async function closeParty(code: string): Promise<void> {
  await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/close`, {
    method: "POST",
    headers: getHeaders(),
  });
}

export async function playNextPartyTrack(code: string, videoId: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/tracks/${encodeURIComponent(videoId)}/play-next`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to move track to play next");
  return r.json();
}

export async function reorderPartyTrack(code: string, fromPosition: number, toPosition: number): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/reorder`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ from_position: fromPosition, to_position: toPosition }),
  });
  if (!r.ok) throw new Error("Failed to reorder party tracks");
  return r.json();
}

export async function updatePartyMemberRole(code: string, memberUserId: number, role: "cohost" | "listener"): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/members/${memberUserId}/role`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ role }),
  });
  if (!r.ok) throw new Error("Failed to update member role");
  return r.json();
}

export async function syncPartyPlayback(code: string, action: "play" | "pause" | "seek", trackPosition = 0, seekPosition = 0): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/playback`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ action, track_position: trackPosition, seek_position: seekPosition }),
  });
  if (!r.ok) throw new Error("Failed to sync playback");
  return r.json();
}

export async function savePartyAsPlaylist(code: string): Promise<Playlist> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/save-playlist`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to save party as playlist");
  return r.json();
}

export async function sendPartyChat(code: string, message: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ message }),
  });
  if (!r.ok) throw new Error("Failed to send party chat");
  return r.json();
}

export async function deletePartyChatMessage(code: string, messageId: number): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat/${messageId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to delete party chat message");
  return r.json();
}

export async function clearPartyChat(code: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat/clear`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to clear party chat");
  return r.json();
}

export async function reactToPartyTrack(code: string, emoji: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/react`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ emoji }),
  });
  if (!r.ok) throw new Error("Failed to react");
  return r.json();
}

export async function runPartyAutoDj(code: string, limit = 5): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/auto-dj?limit=${limit}`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) throw new Error("Failed to run Auto-DJ");
  return r.json();
}

export async function fetchPartyRecap(code: string): Promise<PartyRecap> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/recap`, { headers: getHeaders() });
  if (!r.ok) throw new Error("Failed to fetch recap");
  return r.json();
}

export async function fetchMyParties(): Promise<Party[]> {
  const r = await fetch(`${API_BASE}/my-parties`, { headers: getHeaders() });
  if (!r.ok) return [];
  return r.json();
}

export function partyEventsUrl(code: string): string {
  const initData = encodeURIComponent(window.Telegram?.WebApp?.initData || "");
  return `${API_BASE}/party/${encodeURIComponent(code)}/events?token=${initData}`;
}
