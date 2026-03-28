const API_BASE = "/api";

// Parse initData from URL hash fragment (fallback if Telegram SDK not loaded)
function getInitDataFromHash(): string {
  const hash = window.location.hash;
  if (!hash.includes("tgWebAppData=")) return "";
  const match = hash.match(/tgWebAppData=([^&]+)/);
  if (!match) return "";
  return decodeURIComponent(match[1]);
}

// Get initData from Telegram SDK or URL hash
export function getInitData(): string {
  // Try Telegram SDK first
  const sdkData = window.Telegram?.WebApp?.initData;
  if (sdkData) return sdkData;
  // Fallback to URL hash parsing
  return getInitDataFromHash();
}

// Parse initDataUnsafe from initData string or URL hash
export function getInitDataUnsafe(): { 
  user?: { id: number; first_name?: string; username?: string; language_code?: string; is_premium?: boolean };
  start_param?: string;
} | undefined {
  // Try SDK first
  if (window.Telegram?.WebApp?.initDataUnsafe) {
    return window.Telegram.WebApp.initDataUnsafe;
  }
  // Fallback: parse from initData string
  const initData = getInitData();
  if (!initData) return undefined;
  try {
    const params = new URLSearchParams(initData);
    const result: { user?: { id: number; first_name?: string; username?: string; language_code?: string; is_premium?: boolean }; start_param?: string } = {};
    const userStr = params.get("user");
    if (userStr) {
      result.user = JSON.parse(userStr);
    }
    const startParam = params.get("start_param");
    if (startParam) {
      result.start_param = startParam;
    }
    if (result.user || result.start_param) return result;
  } catch {}
  return undefined;
}

// Debug: log Telegram SDK state on first call
let _debugLogged = false;
function getHeaders(): Record<string, string> {
  const initData = getInitData();
  if (!_debugLogged) {
    _debugLogged = true;
    const debugInfo = {
      telegram: typeof window.Telegram,
      webApp: typeof window.Telegram?.WebApp,
      initDataLen: initData.length,
      initDataUnsafe: window.Telegram?.WebApp?.initDataUnsafe,
      url: window.location.href,
      userAgent: navigator.userAgent,
    };
    console.log("[TMA_DEBUG]", debugInfo);
    // Send debug info to server
    fetch("/api/debug-auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(debugInfo),
    }).catch(() => {});
  }
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initData,
  };
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json().catch(() => ({} as Record<string, unknown>));
      const msg =
        (typeof data.detail === "string" && data.detail) ||
        (typeof data.error === "string" && data.error) ||
        (typeof data.message === "string" && data.message) ||
        "";
      if (msg) return msg;
    }
    const text = await response.text().catch(() => "");
    if (text) return text;
  } catch {}
  return fallback;
}

async function throwApiError(response: Response, fallback: string): Promise<never> {
  const msg = await readErrorMessage(response, fallback);
  throw new Error(msg);
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
  startAt?: number;
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
  if (!r.ok) await throwApiError(r, `State ${r.status}: ${r.statusText}`);
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
  if (!r.ok) await throwApiError(r, `${r.status}: ${r.statusText}`);
  return r.json();
}

export async function fetchPlaylists(userId: number): Promise<Playlist[]> {
  const r = await fetch(`${API_BASE}/playlists/${userId}`, { headers: getHeaders() });
  if (!r.ok) await throwApiError(r, "Failed to fetch playlists");
  return r.json();
}

export async function fetchUserProfile(): Promise<UserProfile> {
  const r = await fetch(`${API_BASE}/user/me`, { headers: getHeaders() });
  if (!r.ok) await throwApiError(r, "Failed to fetch user profile");
  return r.json();
}

export async function updateUserAudioSettings(quality: string): Promise<UserProfile> {
  const r = await fetch(`${API_BASE}/user/audio-settings`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ quality }),
  });
  if (!r.ok) await throwApiError(r, "Failed to update audio settings");
  return r.json();
}

export async function fetchPlaylistTracks(playlistId: number): Promise<Track[]> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/tracks`, { headers: getHeaders() });
  if (!r.ok) await throwApiError(r, "Failed to fetch tracks");
  return r.json();
}

export async function playPlaylist(playlistId: number): Promise<PlayerState> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/play`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to play playlist");
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
  const initData = encodeURIComponent(getInitData());
  return `${API_BASE}/stream/${videoId}?token=${initData}`;
}

export async function toggleFavorite(videoId: string): Promise<boolean> {
  const r = await fetch(`${API_BASE}/favorites/${videoId}`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to toggle favorite");
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
  if (!r.ok) await throwApiError(r, "Failed to reorder");
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
  if (!r.ok) await throwApiError(r, "Failed to create playlist");
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
  if (!r.ok) await throwApiError(r, "Failed to add track");
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
  fireAndForget(fetch(`${API_BASE}/ingest`, {
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
        cover_url: track.cover_url,
      },
      listen_duration: listenDuration,
      source,
    }),
  }), "ingestEvent");
}

export async function sendFeedback(
  feedback: "like" | "dislike",
  sourceId: string,
  context: string = "player",
): Promise<void> {
  fireAndForget(fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ feedback, source_id: sourceId, context }),
  }), "sendFeedback");
}
function fireAndForget(promise: Promise<unknown>, label: string): void {
  promise.catch((error) => {
    console.warn(`[fire-and-forget] ${label} failed`, error);
  });
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

export async function fetchTrackOfDay(): Promise<Track | null> {
  const r = await fetch(`${API_BASE}/track-of-day`, { headers: getHeaders() });
  if (!r.ok) return null;
  const data = await r.json();
  if (!data || !data.video_id) return null;
  return data as Track;
}

// ── User Stats & Profile ─────────────────────────────────────────────────

export interface UserStats {
  total_plays: number;
  total_time: number;
  total_favorites: number;
  top_artists: Array<{ name: string; count: number }>;
  top_genres: Array<{ name: string; count: number }>;
  recent_tracks: Track[];
  xp: number;
  level: number;
  streak_days: number;
  badges: string[];
  member_since: string | null;
}

export async function fetchUserStats(userId: number): Promise<UserStats> {
  const r = await fetchWithRetry(`${API_BASE}/stats/${userId}`, { headers: getHeaders(), retries: 1 });
  if (!r.ok) await throwApiError(r, "Failed to fetch stats");
  return r.json();
}

// ── Leaderboard & Challenges ────────────────────────────────────────────

export interface LeaderboardEntry {
  user_id: number;
  name: string;
  score: number;
  level: number;
}

export interface LeaderboardData {
  entries: LeaderboardEntry[];
  my_rank: number | null;
  my_xp: number;
  my_level: number;
  period: string;
}

export async function fetchLeaderboard(period: "weekly" | "alltime" = "weekly"): Promise<LeaderboardData> {
  const r = await fetchWithRetry(`${API_BASE}/leaderboard/${period}`, { headers: getHeaders(), retries: 1 });
  if (!r.ok) await throwApiError(r, "Failed to fetch leaderboard");
  return r.json();
}

export interface Challenge {
  id: string;
  title: Record<string, string>;
  icon: string;
  target: number;
  progress: number;
  completed: boolean;
  xp_reward: number;
}

export interface ChallengesData {
  challenges: Challenge[];
  week: string;
  week_end: string;
}

export async function fetchChallenges(userId: number): Promise<ChallengesData> {
  const r = await fetchWithRetry(`${API_BASE}/challenges/${userId}`, { headers: getHeaders(), retries: 1 });
  if (!r.ok) await throwApiError(r, "Failed to fetch challenges");
  return r.json();
}

// ── Story Cards ─────────────────────────────────────────────────────────

export function getStoryCardUrl(videoId: string): string {
  const initData = encodeURIComponent(getInitData());
  return `${API_BASE}/story-card/${videoId}?token=${initData}`;
}

// ── Music Battles ───────────────────────────────────────────────────────

export interface BattleOption {
  title: string;
  artist: string;
  video_id: string;
}

export interface BattleRound {
  round: number;
  stream_id: string;
  correct_idx: number;
  options: BattleOption[];
  cover_url?: string;
}

export interface BattleData {
  rounds: BattleRound[];
  total: number;
}

export async function startBattle(): Promise<BattleData> {
  const r = await fetchWithRetry(`${API_BASE}/battle/start`, {
    method: "POST",
    headers: getHeaders(),
    retries: 1,
  });
  if (!r.ok) await throwApiError(r, "Failed to start battle");
  return r.json();
}

export interface BattleScoreResult {
  correct: number;
  total: number;
  xp_earned: number;
}

export async function submitBattleScore(correct: number, total: number): Promise<BattleScoreResult> {
  const r = await fetch(`${API_BASE}/battle/score`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ correct, total }),
  });
  if (!r.ok) await throwApiError(r, "Failed to submit score");
  return r.json();
}

// ── Activity Feed ───────────────────────────────────────────────────────

export interface ActivityItem {
  user_id: number;
  user_name: string;
  track_title: string;
  track_artist: string;
  video_id: string;
  cover_url?: string;
  played_at: string | null;
}

export async function fetchActivityFeed(limit = 30): Promise<ActivityItem[]> {
  const r = await fetchWithRetry(`${API_BASE}/activity/feed?limit=${limit}`, {
    headers: getHeaders(),
    retries: 1,
  });
  if (!r.ok) return [];
  const data = await r.json();
  return data.feed;
}

// ── Collaborative Playlists ──────────────────────────────────────────────

export interface CollabInfo {
  enabled: boolean;
  invite_code?: string;
  member_count: number;
  is_member: boolean;
  is_owner: boolean;
}

export async function enableCollab(playlistId: number): Promise<{ invite_code: string }> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/collab/enable`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to enable collab");
  return r.json();
}

export async function joinCollab(code: string): Promise<{ playlist_id: number }> {
  const r = await fetch(`${API_BASE}/playlist/collab/join/${encodeURIComponent(code)}`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to join collab");
  return r.json();
}

export async function fetchCollabInfo(playlistId: number): Promise<CollabInfo> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/collab/info`, { headers: getHeaders() });
  if (!r.ok) return { enabled: false, member_count: 0, is_member: false, is_owner: false };
  return r.json();
}

export async function disableCollab(playlistId: number): Promise<void> {
  const r = await fetch(`${API_BASE}/playlist/${playlistId}/collab/disable`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to disable collab");
}

// ── Radio Mode ───────────────────────────────────────────────────────

export async function fetchRadioNext(seedVideoId: string, exclude: string[] = [], limit = 8): Promise<Track[]> {
  const r = await fetchWithRetry(`${API_BASE}/radio/next`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ seed_video_id: seedVideoId, exclude, limit }),
    retries: 1,
  });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks;
}

// ── Wrapped / Music Recap ────────────────────────────────────────────

export interface WrappedData {
  total_plays: number;
  total_time: number;
  total_favorites: number;
  unique_artists: number;
  unique_tracks: number;
  top_artists: Array<{ name: string; count: number }>;
  top_genres: Array<{ name: string; count: number }>;
  top_track: { video_id: string; title: string; artist: string; cover_url?: string; play_count: number } | null;
  top_tracks: Array<Track & { play_count: number }>;
  listening_hours: number[];
  peak_hour: number;
  personality: string;
  level: number;
  xp: number;
  streak_days: number;
  member_since: string | null;
  error?: string;
  detail?: string;
}

export async function fetchWrapped(): Promise<WrappedData> {
  const r = await fetchWithRetry(`${API_BASE}/wrapped`, { headers: getHeaders(), retries: 1, timeout: 10000 });
  const data = await r.json().catch(() => ({} as WrappedData));
  if (!r.ok) {
    const msg = (typeof data.detail === "string" && data.detail) || (typeof data.error === "string" && data.error) || "Failed to fetch wrapped";
    throw new Error(msg);
  }
  if (!data.error && typeof data.detail === "string" && data.detail) {
    data.error = data.detail;
  }
  return data;
}

// ── Smart Playlists (auto-generated) ──────────────────────────────────

export interface SmartPlaylist {
  id: string;
  name: string;
  icon: string;
  description: string;
  tracks: Track[];
}

export async function fetchSmartPlaylists(): Promise<SmartPlaylist[]> {
  const r = await fetchWithRetry(`${API_BASE}/smart-playlists`, { headers: getHeaders(), retries: 1, timeout: 8000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.playlists;
}

export async function fetchFavoritesList(limit?: number): Promise<Track[]> {
  const params = new URLSearchParams();
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  const url = params.size > 0
    ? `${API_BASE}/favorites/list?${params.toString()}`
    : `${API_BASE}/favorites/list`;
  const r = await fetch(url, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return Array.isArray(data.tracks) ? data.tracks : [];
}

// ── Last.fm Discovery ────────────────────────────────────────────────────

export async function fetchLastfmTagTop(tag: string, limit = 15): Promise<Track[]> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/tag-top?tag=${encodeURIComponent(tag)}&limit=${limit}`, { headers: getHeaders(), retries: 1, timeout: 12000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks || [];
}

export async function fetchLastfmGeoTop(country = "russia", limit = 15): Promise<Track[]> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/geo-top?country=${encodeURIComponent(country)}&limit=${limit}`, { headers: getHeaders(), retries: 1, timeout: 12000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks || [];
}

export async function fetchLastfmChart(limit = 20): Promise<Track[]> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/chart?limit=${limit}`, { headers: getHeaders(), retries: 1, timeout: 12000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks || [];
}

export async function fetchLastfmNewReleases(limit = 15): Promise<{ tracks: Track[]; artists: string[] }> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/new-releases?limit=${limit}`, { headers: getHeaders(), retries: 1, timeout: 12000 });
  if (!r.ok) return { tracks: [], artists: [] };
  const data = await r.json();
  return { tracks: data.tracks || [], artists: data.artists || [] };
}

export async function fetchLastfmArtistMix(artist: string, limit = 15): Promise<Track[]> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/artist-mix?artist=${encodeURIComponent(artist)}&limit=${limit}`, { headers: getHeaders(), retries: 1, timeout: 12000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tracks || [];
}

export interface LastfmTag {
  name: string;
  reach: number;
  count: number;
}

export async function fetchLastfmTags(): Promise<LastfmTag[]> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/tags`, { headers: getHeaders(), retries: 1, timeout: 8000 });
  if (!r.ok) return [];
  const data = await r.json();
  return data.tags || [];
}

export interface LastfmArtistInfo {
  name: string;
  listeners: number;
  playcount: number;
  tags: string[];
  bio: string;
  similar: string[];
}

export async function fetchLastfmArtistInfo(artist: string): Promise<LastfmArtistInfo | null> {
  const r = await fetchWithRetry(`${API_BASE}/lastfm/artist-info?artist=${encodeURIComponent(artist)}`, { headers: getHeaders(), retries: 1, timeout: 8000 });
  if (!r.ok) return null;
  const data = await r.json();
  return data.name ? data as LastfmArtistInfo : null;
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

export async function createParty(name = "Party"): Promise<Party> {
  const r = await fetch(`${API_BASE}/party`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ name }),
  });
  if (!r.ok) await throwApiError(r, "Failed to create party");
  return r.json();
}

export async function fetchParty(code: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}`, { headers: getHeaders() });
  if (!r.ok) await throwApiError(r, "Party not found");
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
  if (!r.ok) await throwApiError(r, `Failed to add party track (${r.status})`);
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
  if (!r.ok) await throwApiError(r, "Failed to skip");
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
  if (!r.ok) await throwApiError(r, "Failed to move track to play next");
  return r.json();
}

export async function reorderPartyTrack(code: string, fromPosition: number, toPosition: number): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/reorder`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ from_position: fromPosition, to_position: toPosition }),
  });
  if (!r.ok) await throwApiError(r, "Failed to reorder party tracks");
  return r.json();
}

export async function updatePartyMemberRole(code: string, memberUserId: number, role: "cohost" | "listener"): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/members/${memberUserId}/role`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ role }),
  });
  if (!r.ok) await throwApiError(r, "Failed to update member role");
  return r.json();
}

export async function syncPartyPlayback(code: string, action: "play" | "pause" | "seek", trackPosition = 0, seekPosition = 0): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/playback`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ action, track_position: trackPosition, seek_position: seekPosition }),
  });
  if (!r.ok) await throwApiError(r, "Failed to sync playback");
  return r.json();
}

export async function savePartyAsPlaylist(code: string): Promise<Playlist> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/save-playlist`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to save party as playlist");
  return r.json();
}

export async function sendPartyChat(code: string, message: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ message }),
  });
  if (!r.ok) await throwApiError(r, "Failed to send party chat");
  return r.json();
}

export async function deletePartyChatMessage(code: string, messageId: number): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat/${messageId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to delete party chat message");
  return r.json();
}

export async function clearPartyChat(code: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/chat/clear`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to clear party chat");
  return r.json();
}

export async function reactToPartyTrack(code: string, emoji: string): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/react`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ emoji }),
  });
  if (!r.ok) await throwApiError(r, "Failed to react");
  return r.json();
}

export async function runPartyAutoDj(code: string, limit = 5): Promise<Party> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/auto-dj?limit=${limit}`, {
    method: "POST",
    headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to run Auto-DJ");
  return r.json();
}

export async function fetchPartyRecap(code: string): Promise<PartyRecap> {
  const r = await fetch(`${API_BASE}/party/${encodeURIComponent(code)}/recap`, { headers: getHeaders() });
  if (!r.ok) await throwApiError(r, "Failed to fetch recap");
  return r.json();
}

export async function fetchMyParties(): Promise<Party[]> {
  const r = await fetch(`${API_BASE}/my-parties`, { headers: getHeaders() });
  if (!r.ok) return [];
  return r.json();
}

export function partyEventsUrl(code: string): string {
  const initData = encodeURIComponent(getInitData());
  return `${API_BASE}/party/${encodeURIComponent(code)}/events?token=${initData}`;
}

// ── Live Broadcast (DJ Radio) ────────────────────────────────────────

export interface BroadcastTrack {
  video_id: string;
  title: string;
  artist: string;
  duration: number;
  duration_fmt: string;
  source: string;
  cover_url?: string;
  position: number;
}

export interface Broadcast {
  is_live: boolean;
  is_dj: boolean;
  dj_id: number | null;
  dj_name: string | null;
  current_idx: number;
  seek_pos: number;
  elapsed_pos?: number;
  action: string;
  started_at: string | null;
  updated_at: string | null;
  channel: string | null;
  listener_count: number;
  tracks: BroadcastTrack[];
}

export async function fetchBroadcast(): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast`, { headers: getHeaders(), retries: 1 });
  if (!r.ok) await throwApiError(r, "Failed to fetch broadcast");
  return r.json();
}

export async function startBroadcast(channel = "tequila", limit = 30): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/start`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify({ channel, limit }),
  });
  if (!r.ok) await throwApiError(r, "Failed to start broadcast");
  return r.json();
}

export async function stopBroadcast(): Promise<void> {
  await fetchWithRetry(`${API_BASE}/broadcast/stop`, { method: "POST", headers: getHeaders() });
}

export async function loadBroadcastChannel(channel: string, limit = 30): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/load-channel`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify({ channel, limit }),
  });
  if (!r.ok) await throwApiError(r, "Failed to load channel");
  return r.json();
}

export async function addBroadcastTrack(track: Track): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/tracks`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify(track),
  });
  if (!r.ok) await throwApiError(r, "Failed to add track");
  return r.json();
}

export async function removeBroadcastTrack(videoId: string): Promise<void> {
  await fetchWithRetry(`${API_BASE}/broadcast/tracks/${encodeURIComponent(videoId)}`, {
    method: "DELETE", headers: getHeaders(),
  });
}

export async function reorderBroadcast(fromPos: number, toPos: number): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/reorder`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify({ from_position: fromPos, to_position: toPos }),
  });
  if (!r.ok) await throwApiError(r, "Failed to reorder");
  return r.json();
}

export async function skipBroadcast(): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/skip`, {
    method: "POST", headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to skip");
  return r.json();
}

export async function syncBroadcastPlayback(action: string, seekPos = 0, currentIdx?: number): Promise<Broadcast> {
  const body: Record<string, unknown> = { action, seek_pos: seekPos };
  if (currentIdx !== undefined) body.current_idx = currentIdx;
  const r = await fetchWithRetry(`${API_BASE}/broadcast/playback`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) await throwApiError(r, "Failed to sync playback");
  return r.json();
}

export async function advanceBroadcast(): Promise<Broadcast> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/advance`, {
    method: "POST", headers: getHeaders(),
  });
  if (!r.ok) await throwApiError(r, "Failed to advance");
  return r.json();
}

export interface ChannelInfo {
  label: string;
  track_count: number;
}

export async function fetchBroadcastChannels(): Promise<ChannelInfo[]> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/channels`, { headers: getHeaders() });
  if (!r.ok) return [];
  const data = await r.json();
  return data.channels;
}

export async function importBroadcastChannel(channelRef: string, label?: string): Promise<{ status: string; label: string }> {
  const r = await fetchWithRetry(`${API_BASE}/broadcast/import-channel`, {
    method: "POST", headers: getHeaders(),
    body: JSON.stringify({ channel_ref: channelRef, label: label || "" }),
  });
  if (!r.ok) await throwApiError(r, "Failed to import channel");
  return r.json();
}

export async function uploadBroadcastVoice(blob: Blob): Promise<{ url: string }> {
  const form = new FormData();
  form.append("file", blob, "voice.webm");
  const r = await fetch(`${API_BASE}/broadcast/voice`, {
    method: "POST",
    headers: { "X-Telegram-Init-Data": getInitData() },
    body: form,
  });
  if (!r.ok) throw new Error("Voice upload failed");
  return r.json();
}

export function broadcastEventsUrl(): string {
  const initData = encodeURIComponent(getInitData());
  return `${API_BASE}/broadcast/events?token=${initData}`;
}
