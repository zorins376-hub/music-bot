import { memo } from "preact/compat";
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchBroadcast, startBroadcast, stopBroadcast, loadBroadcastChannel,
  skipBroadcast, syncBroadcastPlayback, removeBroadcastTrack,
  broadcastEventsUrl, fetchBroadcastChannels, importBroadcastChannel,
  uploadBroadcastVoice,
  type Broadcast, type BroadcastTrack, type Track, type ChannelInfo,
} from "../api";
import { getThemeById, themeColors } from "../themes";
import { IconBroadcast, IconSpinner, IconMusic, IconTrash, IconMic } from "./Icons";

interface Props {
  userId: number;
  currentTrack?: Track | null;
  elapsed?: number;
  onPlayTrack: (track: Track) => void;
  onBroadcastAdvance?: () => Promise<void>;
  isAdmin?: boolean;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

function toPlayerTrack(track: BroadcastTrack, startAt?: number): Track {
  return {
    video_id: track.video_id,
    title: track.title || "",
    artist: track.artist || "",
    duration: track.duration || 0,
    duration_fmt: track.duration_fmt || "0:00",
    source: track.source || "channel",
    cover_url: track.cover_url,
    startAt: startAt && startAt > 1 ? startAt : undefined,
  };
}

export const LiveRadioView = memo(function LiveRadioView({
  userId,
  onPlayTrack,
  currentTrack,
  elapsed = 0,
  isAdmin = false,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [starting, setStarting] = useState(false);
  const [channel, setChannel] = useState("tequila");
  const [expandedQueue, setExpandedQueue] = useState(false);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [importInput, setImportInput] = useState("");
  const [importing, setImporting] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [recording, setRecording] = useState(false);
  const [djMuted, setDjMuted] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const refreshTimer = useRef<number | null>(null);
  const voiceAudioRef = useRef<HTMLAudioElement | null>(null);

  // Fetch initial state
  const loadState = useCallback(async () => {
    let timeoutId: number | undefined;
    try {
      setError(false);
      const data = await Promise.race([
        fetchBroadcast(),
        new Promise<never>((_, reject) => {
          timeoutId = window.setTimeout(() => reject(new Error("broadcast timeout")), 7000);
        }),
      ]);
      setBroadcast(data);
      // Load available channels if DJ
      if (data.is_dj || isAdmin) {
        fetchBroadcastChannels().then(setChannels).catch(() => {});
      }
    } catch {
      setBroadcast(null);
      setError(true);
    } finally {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      setLoading(false);
    }
  }, [isAdmin]);

  const scheduleRefresh = useCallback((delay = 300) => {
    if (refreshTimer.current) {
      clearTimeout(refreshTimer.current);
    }

    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      void loadState();
    }, delay);
  }, [loadState]);

  // Import channel handler
  const handleImport = async () => {
    if (!importInput.trim()) return;
    setImporting(true);
    haptic("medium");
    try {
      await importBroadcastChannel(importInput.trim());
      setImportInput("");
      setShowImport(false);
      // Refresh channel list after a delay (import runs in background)
      setTimeout(() => { fetchBroadcastChannels().then(setChannels).catch(() => {}); }, 3000);
    } catch (e) {
      console.error("Import failed:", e);
    } finally {
      setImporting(false);
    }
  };

  // ── DJ Monitor mute toggle ────────────────────────────────────
  const toggleDjMute = useCallback(() => {
    const audio = document.querySelector("audio") as HTMLAudioElement | null;
    if (audio) {
      const next = !djMuted;
      audio.muted = next;
      setDjMuted(next);
      haptic("light");
    }
  }, [djMuted]);

  // ── Voice recording (DJ) ──────────────────────────────────────
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (blob.size > 500) {
          try { await uploadBroadcastVoice(blob); } catch (e) { console.error("Voice upload failed:", e); }
        }
        setRecording(false);
      };
      mediaRecorderRef.current = mr;
      mr.start();
      setRecording(true);
      haptic("heavy");
    } catch (e) {
      console.error("Mic access denied:", e);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
      haptic("medium");
    }
  }, []);

  // ── Play DJ voice for listeners (duck music) ───────────────────
  const playVoiceMessage = useCallback((url: string) => {
    // Duck the main player volume
    const mainAudio = document.querySelector("audio") as HTMLAudioElement | null;
    const prevVolume = mainAudio?.volume ?? 1;
    if (mainAudio) mainAudio.volume = 0.15;

    const va = new Audio(url);
    voiceAudioRef.current = va;
    va.volume = 1;
    va.onended = () => {
      if (mainAudio) mainAudio.volume = prevVolume;
      voiceAudioRef.current = null;
    };
    va.onerror = () => {
      if (mainAudio) mainAudio.volume = prevVolume;
      voiceAudioRef.current = null;
    };
    va.play().catch(() => {
      if (mainAudio) mainAudio.volume = prevVolume;
    });
  }, []);

  // SSE connection
  const connectSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }
    const es = new EventSource(broadcastEventsUrl());
    esRef.current = es;

    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.event === "connected" && msg.data) {
          setBroadcast(msg.data);
          // Auto-play current track for listeners joining a live broadcast
          // Use elapsed_pos so listener hears the same moment as the DJ
          if (msg.data.is_live && msg.data.tracks?.length > 0) {
            const idx = msg.data.current_idx ?? 0;
            const t = msg.data.tracks[idx];
            if (t?.video_id) {
              const elapsed = typeof msg.data.elapsed_pos === "number" ? msg.data.elapsed_pos : 0;
              onPlayTrack(toPlayerTrack(t, elapsed));
            }
          }
          return;
        }
        if (msg.event === "stopped") {
          setBroadcast(prev => prev ? {
            ...prev,
            is_live: false,
            current_idx: 0,
            seek_pos: 0,
            action: "idle",
            tracks: [],
          } : null);
          return;
        }
        if (msg.event === "started") {
          scheduleRefresh(0);
          return;
        }
        if (msg.event === "listener_count" && msg.data?.count !== undefined) {
          setBroadcast(prev => prev ? { ...prev, listener_count: msg.data.count } : null);
          return;
        }
        if (msg.event === "next" && msg.data?.track) {
          const nextTrack = msg.data.track as BroadcastTrack;
          const nextPosition = typeof msg.data?.position === "number" ? msg.data.position : undefined;

          if (nextTrack.video_id) {
            onPlayTrack(toPlayerTrack(nextTrack));
          }

          setBroadcast(prev => {
            if (!prev) return prev;

            const currentIdx = nextPosition ?? prev.current_idx;
            const nextTracks = [...prev.tracks];
            if (currentIdx >= 0) {
              nextTracks[currentIdx] = { ...nextTrack, position: currentIdx };
            }

            return {
              ...prev,
              is_live: true,
              current_idx: currentIdx,
              seek_pos: 0,
              action: "play",
              tracks: nextTracks,
            };
          });
          scheduleRefresh(500);
          return;
        }
        if (msg.event === "playback_sync") {
          setBroadcast(prev => prev ? {
            ...prev,
            action: typeof msg.data?.action === "string" ? msg.data.action : prev.action,
            seek_pos: typeof msg.data?.seek_pos === "number" ? msg.data.seek_pos : prev.seek_pos,
            current_idx: typeof msg.data?.current_idx === "number" ? msg.data.current_idx : prev.current_idx,
          } : null);
          scheduleRefresh(400);
          return;
        }
        if (msg.event === "voice" && msg.data?.url) {
          playVoiceMessage(msg.data.url);
          return;
        }
        if (msg.event === "queue_updated") {
          scheduleRefresh(200);
        }
      } catch {}
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      reconnectTimer.current = window.setTimeout(connectSSE, 3000);
    };
  }, [isAdmin, onPlayTrack, scheduleRefresh, playVoiceMessage]);

  useEffect(() => {
    loadState();
    connectSSE();
    return () => {
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [loadState, connectSSE]);

  // DJ actions
  const handleStart = async () => {
    setStarting(true);
    haptic("heavy");
    try {
      const data = await startBroadcast(channel, 30);
      setBroadcast(data);
      // Auto-play first track
      if (data.tracks.length > 0) {
        const t = data.tracks[0];
        onPlayTrack({
          video_id: t.video_id, title: t.title, artist: t.artist,
          duration: t.duration, duration_fmt: t.duration_fmt,
          source: t.source, cover_url: t.cover_url,
        });
      }
    } catch (e) {
      console.error("Start broadcast failed:", e);
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    haptic("heavy");
    try {
      await stopBroadcast();
      setBroadcast(prev => prev ? { ...prev, is_live: false, tracks: [] } : null);
    } catch {}
  };

  const handleSkip = async () => {
    haptic("medium");
    try {
      const data = await skipBroadcast();
      setBroadcast(data);
      const t = data.tracks[data.current_idx];
      if (t) {
        onPlayTrack({
          video_id: t.video_id, title: t.title, artist: t.artist,
          duration: t.duration, duration_fmt: t.duration_fmt,
          source: t.source, cover_url: t.cover_url,
        });
      }
    } catch {}
  };

  const handleLoadMore = async () => {
    haptic("light");
    try {
      const data = await loadBroadcastChannel(channel, 20);
      setBroadcast(data);
    } catch {}
  };

  const handleRemoveTrack = async (videoId: string) => {
    haptic("medium");
    try {
      await removeBroadcastTrack(videoId);
      setBroadcast(prev => {
        if (!prev) return prev;

        const removedIndex = prev.tracks.findIndex((track) => track.video_id === videoId);
        if (removedIndex === -1) {
          return prev;
        }

        const nextTracks = prev.tracks
          .filter((track) => track.video_id !== videoId)
          .map((track, index) => ({ ...track, position: index }));
        const nextCurrentIdx = removedIndex < prev.current_idx
          ? Math.max(prev.current_idx - 1, 0)
          : Math.min(prev.current_idx, Math.max(nextTracks.length - 1, 0));

        return {
          ...prev,
          current_idx: nextCurrentIdx,
          tracks: nextTracks,
        };
      });
      scheduleRefresh(150);
    } catch {}
  };

  const handleTrackClick = (track: BroadcastTrack) => {
    const isCurrentTrack = track.position === (broadcast?.current_idx ?? 0);
    if (!isDJ && !isCurrentTrack) {
      return;
    }

    haptic("light");
    onPlayTrack(toPlayerTrack(track));

    // If admin, sync playback position
    if (isDJ && broadcast) {
      syncBroadcastPlayback("play", 0, track.position).then(setBroadcast).catch(() => {});
    }
  };

  // ── Render ────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 300 }}>
        <IconSpinner size={32} color={tc.highlight} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: "center", padding: 48 }}>
        <IconBroadcast size={36} color={tc.hintColor} />
        <div style={{ fontSize: 15, fontWeight: 600, color: tc.textColor, marginTop: 12 }}>
          Не удалось загрузить эфир
        </div>
        <div style={{ fontSize: 12, color: tc.hintColor, marginTop: 8, marginBottom: 16 }}>
          Если сеть или Telegram initData запаздывают, экран больше не будет висеть бесконечно.
        </div>
        <button
          onClick={() => { setLoading(true); loadState(); }}
          style={{
            padding: "10px 18px",
            borderRadius: 12,
            border: "none",
            background: tc.highlight,
            color: "#fff",
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Повторить
        </button>
      </div>
    );
  }

  const isDJ = Boolean(isAdmin || broadcast?.is_dj);
  const isLive = broadcast?.is_live ?? false;
  const currentIdx = broadcast?.current_idx ?? 0;
  const tracks = broadcast?.tracks ?? [];
  const currentTrackData = tracks[currentIdx];
  const upcomingTracks = tracks.slice(currentIdx + 1);

  return (
    <div style={{ padding: "0 12px 100px", maxWidth: 480, margin: "0 auto" }}>
      {/* CSS Animations */}
      <style>{`
        @keyframes bcast-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes bcast-eq { from { height: 4px; } to { height: 16px; } }
        @keyframes bcast-glow { 0%, 100% { box-shadow: 0 0 20px rgba(255,50,50,0.3); } 50% { box-shadow: 0 0 40px rgba(255,50,50,0.6); } }
        @keyframes bcast-slideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      {/* Header */}
      <div style={{
        textAlign: "center", padding: "24px 0 16px",
        animation: "bcast-slideIn 0.4s ease",
      }}>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 10,
          padding: "8px 20px", borderRadius: 24,
          background: isLive ? "rgba(255, 50, 50, 0.15)" : tc.cardBg,
          border: isLive ? "1px solid rgba(255, 50, 50, 0.3)" : tc.cardBorder,
          animation: isLive ? "bcast-glow 2s ease infinite" : undefined,
        }}>
          <IconBroadcast size={20} color={isLive ? "#ff3232" : tc.hintColor} />
          <span style={{
            fontSize: 16, fontWeight: 700,
            color: isLive ? "#ff3232" : tc.textColor,
          }}>
            {isLive ? "ON AIR" : "Offline"}
          </span>
          {isLive && (
            <span style={{
              width: 8, height: 8, borderRadius: "50%", background: "#ff3232",
              animation: "bcast-pulse 1.5s ease infinite",
            }} />
          )}
        </div>

        {isLive && broadcast && (
          <div style={{
            marginTop: 8, fontSize: 12, color: tc.hintColor,
            display: "flex", justifyContent: "center", gap: 16,
          }}>
            <span>DJ: {broadcast.dj_name || "Unknown"}</span>
            <span>{broadcast.listener_count} {broadcast.listener_count === 1 ? "listener" : "listeners"}</span>
          </div>
        )}
      </div>

      {/* Current Track Card */}
      {isLive && currentTrackData && (
        <div style={{
          background: tc.cardBg, borderRadius: 20, padding: 20,
          border: tc.cardBorder,
          marginBottom: 16, animation: "bcast-slideIn 0.5s ease",
          textAlign: "center",
        }}>
          {/* Cover Art */}
          <div style={{
            width: 180, height: 180, borderRadius: 16, margin: "0 auto 16px",
            overflow: "hidden", background: "rgba(255,255,255,0.05)",
            border: `2px solid ${tc.accentBorderAlpha}`,
          }}>
            {currentTrackData.cover_url ? (
              <img src={currentTrackData.cover_url} alt="" style={{
                width: "100%", height: "100%", objectFit: "cover",
              }} />
            ) : (
              <div style={{
                width: "100%", height: "100%", display: "flex",
                alignItems: "center", justifyContent: "center",
              }}>
                <IconMusic size={64} color={tc.hintColor} />
              </div>
            )}
          </div>

          {/* Track Info */}
          <div style={{
            fontSize: 18, fontWeight: 700, color: tc.textColor,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {currentTrackData.title}
          </div>
          <div style={{
            fontSize: 14, color: tc.hintColor, marginTop: 4,
          }}>
            {currentTrackData.artist}
          </div>

          {/* Equalizer Animation */}
          <div style={{
            display: "flex", alignItems: "flex-end", justifyContent: "center",
            gap: 3, height: 20, marginTop: 12,
          }}>
            {[0, 0.1, 0.2, 0.15, 0.05, 0.12, 0.08].map((delay, i) => (
              <span key={i} style={{
                width: 3, borderRadius: 1,
                background: tc.highlight,
                animation: `bcast-eq 0.4s ease ${delay}s infinite alternate`,
              }} />
            ))}
          </div>

          {/* Duration */}
          <div style={{ fontSize: 12, color: tc.hintColor, marginTop: 8 }}>
            {currentTrackData.duration_fmt}
          </div>
        </div>
      )}

      {/* DJ Controls */}
      {isDJ && (
        <div style={{
          background: "linear-gradient(180deg, rgba(20,20,30,0.95), rgba(10,10,18,0.98))",
          borderRadius: 20, padding: 0, overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.08)", marginBottom: 16,
          animation: "bcast-slideIn 0.6s ease",
          boxShadow: isLive ? "0 0 30px rgba(255,50,50,0.1)" : "0 4px 20px rgba(0,0,0,0.3)",
        }}>
          {/* Console Header */}
          <div style={{
            padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between",
            background: "rgba(255,255,255,0.03)", borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14, letterSpacing: 2, fontWeight: 800, color: isLive ? "#ff3232" : tc.hintColor }}>
                DJ CONSOLE
              </span>
              {isLive && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#ff3232", animation: "bcast-pulse 1s ease infinite" }} />}
            </div>
            {isLive && <span style={{ fontSize: 10, color: tc.hintColor, fontFamily: "monospace" }}>CROSSFADE: 8s</span>}
          </div>

          {!isLive ? (
            <div style={{ padding: 16 }}>
              {/* Channel Selector */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: tc.hintColor, marginBottom: 6, letterSpacing: 1, textTransform: "uppercase" }}>Source</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {(channels.length > 0 ? channels : [{ label: "tequila", track_count: 0 }, { label: "fullmoon", track_count: 0 }]).map(ch => (
                    <button key={ch.label} onClick={() => { haptic("light"); setChannel(ch.label); }}
                      style={{ padding: "8px 14px", borderRadius: 10, border: "none",
                        background: channel === ch.label ? tc.highlight : "rgba(255,255,255,0.06)",
                        color: channel === ch.label ? "#fff" : tc.hintColor,
                        fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 0.2s" }}>
                      {ch.label} {ch.track_count > 0 && <span style={{ opacity: 0.6 }}>({ch.track_count})</span>}
                    </button>
                  ))}
                </div>
              </div>
              {/* Import */}
              <div style={{ marginBottom: 12 }}>
                <button onClick={() => setShowImport(!showImport)}
                  style={{ padding: "6px 12px", borderRadius: 8, border: "none",
                    background: "rgba(255,255,255,0.06)", color: tc.hintColor, fontSize: 11, cursor: "pointer" }}>
                  {showImport ? "Hide" : "Import from Telegram"}
                </button>
                {showImport && (
                  <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
                    <input value={importInput} onInput={(e) => setImportInput((e.target as HTMLInputElement).value)}
                      placeholder="@channel_name"
                      style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: tc.cardBorder,
                        background: "rgba(255,255,255,0.04)", color: tc.textColor, fontSize: 13, outline: "none" }} />
                    <button onClick={handleImport} disabled={importing || !importInput.trim()}
                      style={{ padding: "8px 16px", borderRadius: 10, border: "none", background: tc.highlight, color: "#fff",
                        fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: importing || !importInput.trim() ? 0.5 : 1 }}>
                      {importing ? "..." : "Import"}
                    </button>
                  </div>
                )}
              </div>
              {/* GO LIVE */}
              <button onClick={handleStart} disabled={starting}
                style={{ width: "100%", padding: "14px 0", borderRadius: 14, border: "none",
                  background: "linear-gradient(135deg, #ff3232, #ff6b35)", color: "#fff",
                  fontSize: 16, fontWeight: 700, cursor: "pointer", opacity: starting ? 0.6 : 1,
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                {starting ? <IconSpinner size={18} color="#fff" /> : <IconBroadcast size={18} color="#fff" />}
                {starting ? "Starting..." : "GO LIVE"}
              </button>
            </div>
          ) : (
            <>
              {/* ═══ DUAL DECK DISPLAY ═══ */}
              <div style={{ display: "flex", gap: 1, background: "rgba(255,255,255,0.04)" }}>
                {/* DECK A — Now Playing */}
                <div style={{ flex: 1, padding: "14px 12px", background: "rgba(255,50,50,0.05)" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 2, color: "#ff3232", marginBottom: 8 }}>DECK A — NOW</div>
                  {currentTrackData ? (
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <div style={{ width: 44, height: 44, borderRadius: 8, overflow: "hidden", flexShrink: 0, background: "rgba(255,255,255,0.05)",
                        border: "1px solid rgba(255,50,50,0.3)" }}>
                        {currentTrackData.cover_url ? <img src={currentTrackData.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                          : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                              <IconMusic size={18} color={tc.hintColor} /></div>}
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: tc.textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {currentTrackData.title}
                        </div>
                        <div style={{ fontSize: 10, color: tc.hintColor }}>{currentTrackData.artist}</div>
                        {/* Progress bar */}
                        <div style={{ marginTop: 4, height: 3, borderRadius: 2, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                          <div style={{
                            height: "100%", borderRadius: 2,
                            background: "linear-gradient(90deg, #ff3232, #ff6b35)",
                            width: `${currentTrackData.duration ? Math.min(100, (elapsed / currentTrackData.duration) * 100) : 0}%`,
                            transition: "width 1s linear",
                          }} />
                        </div>
                        <div style={{ fontSize: 9, color: tc.hintColor, marginTop: 2, fontFamily: "monospace" }}>
                          {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")} / {currentTrackData.duration_fmt}
                        </div>
                      </div>
                    </div>
                  ) : <div style={{ fontSize: 11, color: tc.hintColor }}>—</div>}
                </div>

                {/* DECK B — Next */}
                <div style={{ flex: 1, padding: "14px 12px", background: "rgba(100,100,255,0.03)" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 2, color: "#6c7aff", marginBottom: 8 }}>DECK B — NEXT</div>
                  {tracks[currentIdx + 1] ? (
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <div style={{ width: 44, height: 44, borderRadius: 8, overflow: "hidden", flexShrink: 0, background: "rgba(255,255,255,0.05)",
                        border: "1px solid rgba(100,100,255,0.2)" }}>
                        {tracks[currentIdx + 1].cover_url ? <img src={tracks[currentIdx + 1].cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                          : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                              <IconMusic size={18} color={tc.hintColor} /></div>}
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: tc.textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {tracks[currentIdx + 1].title}
                        </div>
                        <div style={{ fontSize: 10, color: tc.hintColor }}>{tracks[currentIdx + 1].artist}</div>
                        <div style={{ fontSize: 9, color: tc.hintColor, marginTop: 6, fontFamily: "monospace" }}>
                          {tracks[currentIdx + 1].duration_fmt}
                        </div>
                      </div>
                    </div>
                  ) : <div style={{ fontSize: 11, color: tc.hintColor }}>Queue empty</div>}
                </div>
              </div>

              {/* ═══ CROSSFADE VISUAL ═══ */}
              <div style={{ padding: "10px 16px", background: "rgba(255,255,255,0.02)", borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 9, color: "#ff3232", fontWeight: 700, width: 14, textAlign: "center" }}>A</span>
                  <div style={{ flex: 1, height: 4, borderRadius: 2, background: "rgba(255,255,255,0.06)", position: "relative", overflow: "hidden" }}>
                    {/* Crossfade indicator — shows zone where crossfade happens */}
                    <div style={{
                      position: "absolute", right: 0, top: 0, height: "100%", borderRadius: 2,
                      background: "linear-gradient(90deg, transparent, rgba(100,100,255,0.4))",
                      width: currentTrackData?.duration ? `${Math.min(50, (8 / currentTrackData.duration) * 100)}%` : "15%",
                    }} />
                    {/* Current position */}
                    <div style={{
                      height: "100%", borderRadius: 2,
                      background: "linear-gradient(90deg, #ff3232, #ff6b35)",
                      width: `${currentTrackData?.duration ? Math.min(100, (elapsed / currentTrackData.duration) * 100) : 0}%`,
                      transition: "width 1s linear",
                    }} />
                  </div>
                  <span style={{ fontSize: 9, color: "#6c7aff", fontWeight: 700, width: 14, textAlign: "center" }}>B</span>
                </div>
                <div style={{ textAlign: "center", fontSize: 9, color: tc.hintColor, marginTop: 4, fontFamily: "monospace" }}>
                  AUTO-MIX {currentTrackData?.duration ? `(fade at ${Math.floor(currentTrackData.duration - 8 > 0 ? currentTrackData.duration - 8 : 0)}s)` : ""}
                </div>
              </div>

              {/* ═══ CONTROLS ═══ */}
              <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                {/* Transport buttons */}
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={toggleDjMute}
                    style={{ padding: "11px 14px", borderRadius: 10,
                      border: djMuted ? "1px solid rgba(255,180,0,0.3)" : "1px solid rgba(255,255,255,0.08)",
                      background: djMuted ? "rgba(255,180,0,0.12)" : "rgba(255,255,255,0.04)",
                      color: djMuted ? "#ffb400" : tc.textColor,
                      fontSize: 12, fontWeight: 700, cursor: "pointer", letterSpacing: 1 }}>
                    {djMuted ? "MUTED" : "MUTE"}
                  </button>
                  <button onClick={handleSkip}
                    style={{ flex: 1, padding: "11px 0", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)",
                      background: "rgba(255,255,255,0.04)", color: tc.textColor,
                      fontSize: 12, fontWeight: 700, cursor: "pointer", letterSpacing: 1 }}>
                    SKIP
                  </button>
                  <button onClick={handleLoadMore}
                    style={{ flex: 1, padding: "11px 0", borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)",
                      background: "rgba(255,255,255,0.04)", color: tc.textColor,
                      fontSize: 12, fontWeight: 700, cursor: "pointer", letterSpacing: 1 }}>
                    + TRACKS
                  </button>
                  <button onClick={handleStop}
                    style={{ flex: 1, padding: "11px 0", borderRadius: 10, border: "1px solid rgba(255,50,50,0.2)",
                      background: "rgba(255,50,50,0.08)", color: "#ff3232",
                      fontSize: 12, fontWeight: 800, cursor: "pointer", letterSpacing: 1 }}>
                    STOP
                  </button>
                </div>

                {/* Mic + Channel row */}
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <button
                    onPointerDown={(e) => { e.preventDefault(); startRecording(); }}
                    onPointerUp={stopRecording}
                    onPointerLeave={stopRecording}
                    style={{
                      width: 44, height: 44, borderRadius: "50%", border: recording ? "2px solid #ff3232" : "1px solid rgba(255,255,255,0.1)",
                      background: recording ? "rgba(255,50,50,0.3)" : "rgba(255,255,255,0.04)",
                      cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                      animation: recording ? "bcast-pulse 0.6s ease infinite" : undefined,
                      transition: "all 0.2s", flexShrink: 0,
                    }}>
                    <IconMic size={20} color={recording ? "#ff3232" : tc.hintColor} />
                  </button>
                  <span style={{ fontSize: 11, color: recording ? "#ff3232" : tc.hintColor, fontWeight: recording ? 600 : 400, flex: 1 }}>
                    {recording ? "REC... release to send" : "Hold to talk"}
                  </span>
                </div>

                {/* Channel chips */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {(channels.length > 0 ? channels : [{ label: "tequila", track_count: 0 }, { label: "fullmoon", track_count: 0 }]).map(ch => (
                    <button key={ch.label} onClick={() => { haptic("light"); setChannel(ch.label); }}
                      style={{ padding: "5px 10px", borderRadius: 6, border: "none",
                        background: channel === ch.label ? "rgba(255,255,255,0.1)" : "transparent",
                        color: channel === ch.label ? tc.textColor : tc.hintColor,
                        fontSize: 10, fontWeight: 500, cursor: "pointer" }}>
                      {ch.label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Not Live State (for listeners) */}
      {!isLive && !isDJ && (
        <div style={{
          textAlign: "center", padding: 40,
          animation: "bcast-slideIn 0.5s ease",
        }}>
          <IconBroadcast size={48} color={tc.hintColor} />
          <div style={{
            fontSize: 16, fontWeight: 600, color: tc.textColor, marginTop: 16,
          }}>
            No broadcast right now
          </div>
          <div style={{
            fontSize: 13, color: tc.hintColor, marginTop: 8,
          }}>
            Come back when the DJ goes live
          </div>
        </div>
      )}

      {/* Upcoming Queue */}
      {isLive && tracks.length > 0 && (
        <div style={{
          background: tc.cardBg, borderRadius: 16, padding: 16,
          border: tc.cardBorder,
          animation: "bcast-slideIn 0.7s ease",
        }}>
          <div
            onClick={() => setExpandedQueue(!expandedQueue)}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              cursor: "pointer", userSelect: "none",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: tc.textColor }}>
              Queue ({tracks.length} tracks)
            </span>
            <span style={{
              fontSize: 11, color: tc.hintColor,
              transform: expandedQueue ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
            }}>
              {expandedQueue ? "Hide" : "Show"}
            </span>
          </div>

          {expandedQueue && (
            <div style={{ marginTop: 12, maxHeight: 400, overflowY: "auto" }}>
              {tracks.map((t, i) => {
                const isCurrent = i === currentIdx;
                const canSelectTrack = isDJ || isCurrent;
                return (
                  <div
                    key={`${t.video_id}-${i}`}
                    onClick={() => {
                      if (canSelectTrack) {
                        handleTrackClick(t);
                      }
                    }}
                    style={{
                      display: "flex", alignItems: "center", padding: "8px 10px",
                      borderRadius: 10, marginBottom: 4, cursor: canSelectTrack ? "pointer" : "default",
                      background: isCurrent ? `${tc.highlight}22` : "transparent",
                      border: isCurrent ? `1px solid ${tc.highlight}44` : "1px solid transparent",
                      transition: "background 0.15s",
                    }}
                  >
                    {/* Position / Playing Indicator */}
                    <div style={{
                      width: 28, textAlign: "center", flexShrink: 0,
                      fontSize: 11, fontWeight: 600,
                      color: isCurrent ? tc.highlight : tc.hintColor,
                    }}>
                      {isCurrent ? (
                        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 2, height: 14 }}>
                          <span style={{ width: 2, borderRadius: 1, background: tc.highlight, animation: "bcast-eq 0.4s ease infinite alternate" }} />
                          <span style={{ width: 2, borderRadius: 1, background: tc.highlight, animation: "bcast-eq 0.4s ease 0.1s infinite alternate" }} />
                          <span style={{ width: 2, borderRadius: 1, background: tc.highlight, animation: "bcast-eq 0.4s ease 0.2s infinite alternate" }} />
                        </div>
                      ) : (
                        i + 1
                      )}
                    </div>

                    {/* Cover */}
                    <div style={{
                      width: 36, height: 36, borderRadius: 8, overflow: "hidden",
                      flexShrink: 0, marginRight: 10, background: "rgba(255,255,255,0.05)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      {t.cover_url ? (
                        <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      ) : (
                        <IconMusic size={16} color={tc.hintColor} />
                      )}
                    </div>

                    {/* Info */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 13, fontWeight: isCurrent ? 600 : 400, color: tc.textColor,
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      }}>
                        {t.title}
                      </div>
                      <div style={{ fontSize: 11, color: tc.hintColor }}>
                        {t.artist}
                      </div>
                    </div>

                    {/* Duration */}
                    <div style={{ fontSize: 11, color: tc.hintColor, marginLeft: 8, flexShrink: 0 }}>
                      {t.duration_fmt}
                    </div>

                    {/* Admin Remove Button */}
                    {isDJ && !isCurrent && (
                      <div
                        onClick={(e) => { e.stopPropagation(); handleRemoveTrack(t.video_id); }}
                        style={{
                          marginLeft: 6, padding: 4, cursor: "pointer", opacity: 0.5,
                          borderRadius: 6, flexShrink: 0,
                        }}
                      >
                        <IconTrash size={14} color="#ff4444" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
});






