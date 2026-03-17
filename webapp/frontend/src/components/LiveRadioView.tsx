import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchBroadcast, startBroadcast, stopBroadcast, loadBroadcastChannel,
  skipBroadcast, syncBroadcastPlayback, advanceBroadcast, removeBroadcastTrack,
  reorderBroadcast, broadcastEventsUrl, fetchBroadcastChannels, importBroadcastChannel,
  type Broadcast, type BroadcastTrack, type Track, type ChannelInfo,
} from "../api";
import { getThemeById, themeColors } from "../themes";
import { IconBroadcast, IconPlaySmall, IconSpinner, IconMusic, IconTrash, IconDragHandle } from "./Icons";

interface Props {
  userId: number;
  currentTrack?: Track | null;
  onPlayTrack: (track: Track) => void;
  onBroadcastAdvance?: () => Promise<void>;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function LiveRadioView({
  userId,
  onPlayTrack,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [channel, setChannel] = useState("tequila");
  const [expandedQueue, setExpandedQueue] = useState(false);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [importInput, setImportInput] = useState("");
  const [importing, setImporting] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  // Fetch initial state
  const loadState = useCallback(async () => {
    try {
      const data = await fetchBroadcast();
      setBroadcast(data);
      // Load available channels if DJ
      if (data.is_dj) {
        fetchBroadcastChannels().then(setChannels).catch(() => {});
      }
    } catch {
      setBroadcast(null);
    } finally {
      setLoading(false);
    }
  }, []);

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
          return;
        }
        if (msg.event === "stopped") {
          setBroadcast(prev => prev ? { ...prev, is_live: false, tracks: [] } : null);
          return;
        }
        if (msg.event === "started") {
          loadState();
          return;
        }
        // For next, playback_sync, queue_updated — refetch full state
        if (["next", "playback_sync", "queue_updated", "listener_count"].includes(msg.event)) {
          if (msg.event === "next" && msg.data?.track) {
            // Auto-play next track for listeners
            const t = msg.data.track;
            if (t.video_id) {
              onPlayTrack({
                video_id: t.video_id,
                title: t.title || "",
                artist: t.artist || "",
                duration: t.duration || 0,
                duration_fmt: t.duration_fmt || "0:00",
                source: t.source || "channel",
                cover_url: t.cover_url,
              });
            }
          }
          // Lightweight update for listener_count
          if (msg.event === "listener_count" && msg.data?.count !== undefined) {
            setBroadcast(prev => prev ? { ...prev, listener_count: msg.data.count } : null);
            return;
          }
          loadState();
        }
      } catch {}
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      reconnectTimer.current = window.setTimeout(connectSSE, 3000);
    };
  }, [loadState, onPlayTrack]);

  useEffect(() => {
    loadState();
    connectSSE();
    return () => {
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
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
      loadState();
    } catch {}
  };

  const handleTrackClick = (track: BroadcastTrack) => {
    haptic("light");
    onPlayTrack({
      video_id: track.video_id, title: track.title, artist: track.artist,
      duration: track.duration, duration_fmt: track.duration_fmt,
      source: track.source, cover_url: track.cover_url,
    });
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

  const isDJ = broadcast?.is_dj ?? false;
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
          border: `1px solid ${isLive ? "rgba(255, 50, 50, 0.3)" : tc.border}`,
          animation: isLive ? "bcast-glow 2s ease infinite" : undefined,
        }}>
          <IconBroadcast size={20} color={isLive ? "#ff3232" : tc.hint} />
          <span style={{
            fontSize: 16, fontWeight: 700,
            color: isLive ? "#ff3232" : tc.text,
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
            marginTop: 8, fontSize: 12, color: tc.hint,
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
          border: `1px solid ${tc.border}`,
          marginBottom: 16, animation: "bcast-slideIn 0.5s ease",
          textAlign: "center",
        }}>
          {/* Cover Art */}
          <div style={{
            width: 180, height: 180, borderRadius: 16, margin: "0 auto 16px",
            overflow: "hidden", background: "rgba(255,255,255,0.05)",
            border: `2px solid ${tc.border}`,
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
                <IconMusic size={64} color={tc.hint} />
              </div>
            )}
          </div>

          {/* Track Info */}
          <div style={{
            fontSize: 18, fontWeight: 700, color: tc.text,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {currentTrackData.title}
          </div>
          <div style={{
            fontSize: 14, color: tc.hint, marginTop: 4,
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
          <div style={{ fontSize: 12, color: tc.hint, marginTop: 8 }}>
            {currentTrackData.duration_fmt}
          </div>
        </div>
      )}

      {/* DJ Controls */}
      {isDJ && (
        <div style={{
          background: tc.cardBg, borderRadius: 16, padding: 16,
          border: `1px solid ${tc.border}`, marginBottom: 16,
          animation: "bcast-slideIn 0.6s ease",
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: tc.text, marginBottom: 12 }}>
            DJ Panel
          </div>

          {!isLive ? (
            <>
              {/* Channel Selector */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 11, color: tc.hint, marginBottom: 6 }}>
                  Source channel
                </div>
                <div style={{
                  display: "flex", flexWrap: "wrap", gap: 6,
                }}>
                  {(channels.length > 0 ? channels : [{ label: "tequila", track_count: 0 }, { label: "fullmoon", track_count: 0 }]).map(ch => (
                    <button
                      key={ch.label}
                      onClick={() => { haptic("light"); setChannel(ch.label); }}
                      style={{
                        padding: "8px 14px", borderRadius: 10, border: "none",
                        background: channel === ch.label ? tc.highlight : "rgba(255,255,255,0.06)",
                        color: channel === ch.label ? "#fff" : tc.hint,
                        fontSize: 12, fontWeight: 600, cursor: "pointer",
                        transition: "all 0.2s",
                      }}
                    >
                      {ch.label} {ch.track_count > 0 && <span style={{ opacity: 0.6 }}>({ch.track_count})</span>}
                    </button>
                  ))}
                </div>
              </div>

              {/* Import Channel */}
              <div style={{ marginBottom: 12 }}>
                <button
                  onClick={() => setShowImport(!showImport)}
                  style={{
                    padding: "6px 12px", borderRadius: 8, border: "none",
                    background: "rgba(255,255,255,0.06)", color: tc.hint,
                    fontSize: 11, cursor: "pointer",
                  }}
                >
                  {showImport ? "Hide" : "Import from Telegram channel"}
                </button>

                {showImport && (
                  <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
                    <input
                      value={importInput}
                      onInput={(e) => setImportInput((e.target as HTMLInputElement).value)}
                      placeholder="@channel_name"
                      style={{
                        flex: 1, padding: "8px 12px", borderRadius: 10,
                        border: `1px solid ${tc.border}`, background: "rgba(255,255,255,0.04)",
                        color: tc.text, fontSize: 13, outline: "none",
                      }}
                    />
                    <button
                      onClick={handleImport}
                      disabled={importing || !importInput.trim()}
                      style={{
                        padding: "8px 16px", borderRadius: 10, border: "none",
                        background: tc.highlight, color: "#fff",
                        fontSize: 12, fontWeight: 600, cursor: "pointer",
                        opacity: importing || !importInput.trim() ? 0.5 : 1,
                      }}
                    >
                      {importing ? "..." : "Import"}
                    </button>
                  </div>
                )}
              </div>

              {/* Start Button */}
              <button
                onClick={handleStart}
                disabled={starting}
                style={{
                  width: "100%", padding: "14px 0", borderRadius: 14, border: "none",
                  background: "linear-gradient(135deg, #ff3232, #ff6b35)",
                  color: "#fff", fontSize: 16, fontWeight: 700, cursor: "pointer",
                  opacity: starting ? 0.6 : 1,
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                }}
              >
                {starting ? <IconSpinner size={18} color="#fff" /> : <IconBroadcast size={18} color="#fff" />}
                {starting ? "Starting..." : "GO LIVE"}
              </button>
            </>
          ) : (
            <>
              {/* Live Controls */}
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <button
                  onClick={handleSkip}
                  style={{
                    flex: 1, padding: "10px 0", borderRadius: 12, border: "none",
                    background: "rgba(255,255,255,0.08)", color: tc.text,
                    fontSize: 13, fontWeight: 600, cursor: "pointer",
                  }}
                >
                  Skip
                </button>
                <button
                  onClick={handleLoadMore}
                  style={{
                    flex: 1, padding: "10px 0", borderRadius: 12, border: "none",
                    background: "rgba(255,255,255,0.08)", color: tc.text,
                    fontSize: 13, fontWeight: 600, cursor: "pointer",
                  }}
                >
                  + Tracks
                </button>
                <button
                  onClick={handleStop}
                  style={{
                    flex: 1, padding: "10px 0", borderRadius: 12, border: "none",
                    background: "rgba(255, 50, 50, 0.15)", color: "#ff3232",
                    fontSize: 13, fontWeight: 700, cursor: "pointer",
                  }}
                >
                  Stop
                </button>
              </div>

              {/* Channel Switch */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(channels.length > 0 ? channels : [{ label: "tequila", track_count: 0 }, { label: "fullmoon", track_count: 0 }]).map(ch => (
                  <button
                    key={ch.label}
                    onClick={() => { haptic("light"); setChannel(ch.label); }}
                    style={{
                      padding: "6px 10px", borderRadius: 8, border: "none",
                      background: channel === ch.label ? "rgba(255,255,255,0.12)" : "transparent",
                      color: channel === ch.label ? tc.text : tc.hint,
                      fontSize: 11, fontWeight: 500, cursor: "pointer",
                    }}
                  >
                    {ch.label} {ch.track_count > 0 && <span style={{ opacity: 0.5 }}>({ch.track_count})</span>}
                  </button>
                ))}
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
          <IconBroadcast size={48} color={tc.hint} />
          <div style={{
            fontSize: 16, fontWeight: 600, color: tc.text, marginTop: 16,
          }}>
            No broadcast right now
          </div>
          <div style={{
            fontSize: 13, color: tc.hint, marginTop: 8,
          }}>
            Come back when the DJ goes live
          </div>
        </div>
      )}

      {/* Upcoming Queue */}
      {isLive && tracks.length > 0 && (
        <div style={{
          background: tc.cardBg, borderRadius: 16, padding: 16,
          border: `1px solid ${tc.border}`,
          animation: "bcast-slideIn 0.7s ease",
        }}>
          <div
            onClick={() => setExpandedQueue(!expandedQueue)}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              cursor: "pointer", userSelect: "none",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: tc.text }}>
              Queue ({tracks.length} tracks)
            </span>
            <span style={{
              fontSize: 11, color: tc.hint,
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
                return (
                  <div
                    key={`${t.video_id}-${i}`}
                    onClick={() => handleTrackClick(t)}
                    style={{
                      display: "flex", alignItems: "center", padding: "8px 10px",
                      borderRadius: 10, marginBottom: 4, cursor: "pointer",
                      background: isCurrent ? `${tc.highlight}22` : "transparent",
                      border: isCurrent ? `1px solid ${tc.highlight}44` : "1px solid transparent",
                      transition: "background 0.15s",
                    }}
                  >
                    {/* Position / Playing Indicator */}
                    <div style={{
                      width: 28, textAlign: "center", flexShrink: 0,
                      fontSize: 11, fontWeight: 600,
                      color: isCurrent ? tc.highlight : tc.hint,
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
                        <IconMusic size={16} color={tc.hint} />
                      )}
                    </div>

                    {/* Info */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 13, fontWeight: isCurrent ? 600 : 400, color: tc.text,
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      }}>
                        {t.title}
                      </div>
                      <div style={{ fontSize: 11, color: tc.hint }}>
                        {t.artist}
                      </div>
                    </div>

                    {/* Duration */}
                    <div style={{ fontSize: 11, color: tc.hint, marginLeft: 8, flexShrink: 0 }}>
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
}
