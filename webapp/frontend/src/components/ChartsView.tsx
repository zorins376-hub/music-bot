import { useState, useEffect } from "preact/hooks";
import {
  fetchChartSources, fetchChart, fetchPlaylists, addTrackToPlaylist,
  type ChartSource, type Track, type Playlist,
} from "../api";
import { IconMusic, IconSpinner, IconPlus } from "./Icons";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function ChartsView({ userId, onPlayTrack, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const warm = themeId === "tequila";
  const [sources, setSources] = useState<ChartSource[]>([]);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [addMenuTrack, setAddMenuTrack] = useState<Track | null>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [addingTo, setAddingTo] = useState<number | null>(null);

  const hintColor = warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)";
  const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
  const cardBg = warm ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)";
  const cardBorder = warm ? "1px solid rgba(255, 213, 79, 0.1)" : "1px solid rgba(255,255,255,0.06)";
  const activeBg = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))"
    : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.3))`;

  useEffect(() => {
    fetchChartSources()
      .then((s) => {
        setSources(s);
        if (s.length > 0) setActiveSource(s[0].id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!activeSource) return;
    setLoading(true);
    fetchChart(activeSource, 30)
      .then(setTracks)
      .catch(() => setTracks([]))
      .finally(() => setLoading(false));
  }, [activeSource]);

  const openAddMenu = (t: Track) => {
    haptic("light");
    setAddMenuTrack(t);
    fetchPlaylists(userId).then(setPlaylists).catch(() => setPlaylists([]));
  };

  const handleAdd = async (playlistId: number) => {
    if (!addMenuTrack) return;
    haptic("medium");
    setAddingTo(playlistId);
    try {
      await addTrackToPlaylist(playlistId, addMenuTrack);
    } catch {}
    setAddingTo(null);
    setAddMenuTrack(null);
  };

  return (
    <div>
      <div style={{ fontSize: 15, fontWeight: 600, color: textColor, letterSpacing: 0.4, marginBottom: 10 }}>Чарты</div>

      {/* Source tabs */}
      <div style={{ display: "flex", gap: 6, overflowX: "auto", marginBottom: 14, paddingBottom: 4, WebkitOverflowScrolling: "touch" }}>
        {sources.map((s) => (
          <button key={s.id} onClick={() => { haptic("light"); setActiveSource(s.id); }}
            style={{
              padding: "6px 14px", borderRadius: 14, border: activeSource === s.id
                ? (warm ? "1px solid rgba(255,213,79,0.3)" : "none")
                : cardBorder,
              background: activeSource === s.id ? activeBg : cardBg,
              color: activeSource === s.id ? (warm ? "#ffd54f" : "#fff") : hintColor,
              fontSize: 12, fontWeight: activeSource === s.id ? 600 : 400,
              cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
              backdropFilter: warm ? "blur(12px)" : undefined,
            }}>
            {s.label}
          </button>
        ))}
      </div>

      {/* Track list */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={hintColor} /></div>
      ) : tracks.length === 0 ? (
        <div style={{ textAlign: "center", color: hintColor, padding: 32 }}>Нет данных</div>
      ) : (
        tracks.map((t, idx) => (
          <div key={`${t.video_id}-${idx}`}
            style={{ display: "flex", alignItems: "center", padding: "10px 12px", borderRadius: 14, marginBottom: 6, background: cardBg, border: cardBorder, backdropFilter: warm ? "blur(12px)" : undefined }}>
            <div style={{ width: 20, fontSize: 12, color: idx < 3 ? (warm ? "#ffd54f" : accentColor) : hintColor, fontWeight: 700, marginRight: 8, textAlign: "center", flexShrink: 0 }}>
              {idx + 1}
            </div>
            <div onClick={() => { haptic("light"); onPlayTrack(t); }}
              style={{ width: 44, height: 44, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12, cursor: "pointer",
                background: warm ? "rgba(255, 213, 79, 0.08)" : "rgba(124,77,255,0.08)",
                border: warm ? "1px solid rgba(255, 213, 79, 0.14)" : "1px solid rgba(255,255,255,0.06)",
                display: "flex", alignItems: "center", justifyContent: "center" }}>
              {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={22} color={hintColor} />}
            </div>
            <div onClick={() => { haptic("light"); onPlayTrack(t); }} style={{ flex: 1, minWidth: 0, cursor: "pointer" }}>
              <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: textColor }}>{t.title}</div>
              <div style={{ fontSize: 12, color: hintColor }}>{t.artist}</div>
            </div>
            <button onClick={() => openAddMenu(t)}
              style={{ width: 32, height: 32, borderRadius: 8, border: "none", background: "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <IconPlus size={16} color={hintColor} />
            </button>
          </div>
        ))
      )}

      {/* Add-to-playlist modal */}
      {addMenuTrack && (
        <div onClick={() => setAddMenuTrack(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 10000, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 420, maxHeight: "60vh", overflowY: "auto", padding: "16px 16px 24px",
              borderRadius: "20px 20px 0 0",
              background: warm ? "rgba(40, 25, 15, 0.95)" : "var(--tg-theme-bg-color, #1a1a2e)",
              border: warm ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(255,255,255,0.08)",
              backdropFilter: "blur(20px)",
            }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: hintColor, opacity: 0.3, margin: "0 auto 12px" }} />
            <div style={{ fontSize: 13, color: hintColor, marginBottom: 4 }}>Добавить в плейлист</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: textColor, marginBottom: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {addMenuTrack.artist} — {addMenuTrack.title}
            </div>
            {playlists.length === 0 ? (
              <div style={{ textAlign: "center", color: hintColor, padding: 20 }}>Нет плейлистов</div>
            ) : (
              playlists.map((p) => (
                <button key={p.id} onClick={() => handleAdd(p.id)} disabled={addingTo === p.id}
                  style={{
                    display: "flex", alignItems: "center", width: "100%", padding: "10px 14px",
                    borderRadius: 12, border: cardBorder, background: cardBg,
                    marginBottom: 6, cursor: "pointer", textAlign: "left",
                    opacity: addingTo === p.id ? 0.5 : 1,
                  }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: activeBg, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                    <IconMusic size={16} color="#fff" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, color: textColor }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: hintColor }}>{p.track_count} треков</div>
                  </div>
                  {addingTo === p.id ? <IconSpinner size={16} color={hintColor} /> : <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
