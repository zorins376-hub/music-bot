import { useState, useEffect } from "preact/hooks";
import { memo } from "preact/compat";
import {
  fetchChartSources, fetchChart, fetchPlaylists, addTrackToPlaylist,
  createPlaylist, searchTracks,
  type ChartSource, type Track, type Playlist,
} from "../api";
import { getThemeById, themeColors } from "../themes";
import { IconMusic, IconSpinner, IconPlus, IconSave } from "./Icons";
import { showToast } from "./Toast";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export const ChartsView = memo(function ChartsView({ userId, onPlayTrack, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [sources, setSources] = useState<ChartSource[]>([]);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [addMenuTrack, setAddMenuTrack] = useState<Track | null>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [addingTo, setAddingTo] = useState<number | null>(null);
  const [showSaveChart, setShowSaveChart] = useState(false);
  const [saveChartName, setSaveChartName] = useState("");
  const [savingChart, setSavingChart] = useState(false);
  const [saveProgress, setSaveProgress] = useState<{ done: number; total: number } | null>(null);
  const [showSaveMenu, setShowSaveMenu] = useState(false);

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
    fetchChart(activeSource, 100)
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

  const handlePlayTrack = async (t: Track) => {
    haptic("light");
    let track = t;
    if (!track.video_id) {
      // Track has no video_id (Apple chart) — search YouTube first
      try {
        const results = await searchTracks(`${track.artist} - ${track.title}`, 1);
        if (results.length > 0) {
          track = {
            ...track,
            video_id: results[0].video_id,
            source: results[0].source || "youtube",
            duration: track.duration || results[0].duration,
            duration_fmt: track.duration_fmt || results[0].duration_fmt,
            cover_url: track.cover_url || results[0].cover_url,
          };
        } else {
          return;
        }
      } catch {
        return;
      }
    }
    onPlayTrack(track);
  };

  // Save entire chart as new playlist
  const handleSaveChartAsNew = async () => {
    if (!saveChartName.trim() || tracks.length === 0) return;
    haptic("medium");
    setSavingChart(true);
    setSaveProgress({ done: 0, total: tracks.length });
    try {
      const pl = await createPlaylist(saveChartName.trim());
      for (let i = 0; i < tracks.length; i++) {
        let t = tracks[i];
        // Resolve video_id for Apple chart tracks
        if (!t.video_id) {
          try {
            const results = await searchTracks(`${t.artist} - ${t.title}`, 1);
            if (results.length > 0) {
              t = { ...t, video_id: results[0].video_id, source: results[0].source || "youtube",
                duration: t.duration || results[0].duration, duration_fmt: t.duration_fmt || results[0].duration_fmt,
                cover_url: t.cover_url || results[0].cover_url };
            } else { setSaveProgress({ done: i + 1, total: tracks.length }); continue; }
          } catch { setSaveProgress({ done: i + 1, total: tracks.length }); continue; }
        }
        try { await addTrackToPlaylist(pl.id, t); } catch {}
        setSaveProgress({ done: i + 1, total: tracks.length });
      }
      haptic("heavy");
      showToast("Chart saved as playlist!", "success");
    } catch {
      showToast("Failed to save chart", "error");
    }
    setSavingChart(false);
    setSaveProgress(null);
    setShowSaveChart(false);
  };

  // Save chart to existing playlist
  const handleSaveChartToExisting = async (playlistId: number) => {
    if (tracks.length === 0) return;
    haptic("medium");
    setAddingTo(playlistId);
    setSaveProgress({ done: 0, total: tracks.length });
    for (let i = 0; i < tracks.length; i++) {
      let t = tracks[i];
      if (!t.video_id) {
        try {
          const results = await searchTracks(`${t.artist} - ${t.title}`, 1);
          if (results.length > 0) {
            t = { ...t, video_id: results[0].video_id, source: results[0].source || "youtube",
              duration: t.duration || results[0].duration, duration_fmt: t.duration_fmt || results[0].duration_fmt,
              cover_url: t.cover_url || results[0].cover_url };
          } else { setSaveProgress({ done: i + 1, total: tracks.length }); continue; }
        } catch { setSaveProgress({ done: i + 1, total: tracks.length }); continue; }
      }
      try { await addTrackToPlaylist(playlistId, t); } catch {}
      setSaveProgress({ done: i + 1, total: tracks.length });
    }
    haptic("heavy");
    setAddingTo(null);
    setSaveProgress(null);
    setShowSaveMenu(false);
  };

  return (
    <div>
      <div style={{ fontSize: 15, fontWeight: 600, color: tc.textColor, letterSpacing: 0.4, marginBottom: 10 }}>Чарты</div>

      {/* Source tabs */}
      <div style={{ display: "flex", gap: 6, overflowX: "auto", marginBottom: 14, paddingBottom: 4, WebkitOverflowScrolling: "touch" }}>
        {sources.map((s) => (
          <button key={s.id} onClick={() => { haptic("light"); setActiveSource(s.id); }}
            style={{
              padding: "6px 14px", borderRadius: 14, border: activeSource === s.id
                ? (tc.isTequila ? `1px solid ${tc.accentBorderAlpha}` : "none")
                : tc.cardBorder,
              background: activeSource === s.id ? tc.activeBg : tc.cardBg,
              color: activeSource === s.id ? tc.highlight : tc.hintColor,
              fontSize: 12, fontWeight: activeSource === s.id ? 600 : 400,
              cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
              backdropFilter: tc.isTequila ? "blur(12px)" : undefined,
            }}>
            {s.label}
          </button>
        ))}
      </div>

      {/* Save chart as playlist button */}
      {tracks.length > 0 && !loading && (
        <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
          <button onClick={() => {
            haptic("light");
            const label = sources.find(s => s.id === activeSource)?.label || "Chart";
            setSaveChartName(label);
            setShowSaveChart(true);
          }} style={{
            flex: 1, padding: "8px 14px", borderRadius: 12, border: tc.cardBorder,
            background: tc.cardBg, backdropFilter: tc.isTequila ? "blur(12px)" : undefined,
            color: tc.highlight, fontSize: 12, fontWeight: 600,
            cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            <IconSave size={14} color={tc.highlight} /> Новый плейлист из чарта
          </button>
          <button onClick={() => {
            haptic("light");
            setShowSaveMenu(true);
            fetchPlaylists(userId).then(setPlaylists).catch(() => setPlaylists([]));
          }} style={{
            padding: "8px 14px", borderRadius: 12, border: tc.cardBorder,
            background: tc.cardBg, backdropFilter: tc.isTequila ? "blur(12px)" : undefined,
            color: tc.highlight, fontSize: 12, fontWeight: 600,
            cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            <IconPlus size={14} color={tc.highlight} /> В существующий
          </button>
        </div>
      )}

      {/* Track list */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={tc.hintColor} /></div>
      ) : tracks.length === 0 ? (
        <div style={{ textAlign: "center", color: tc.hintColor, padding: 32 }}>Нет данных</div>
      ) : (
        tracks.map((t, idx) => (
          <div key={`${t.video_id}-${idx}`}
            style={{ display: "flex", alignItems: "center", padding: "10px 12px", borderRadius: 14, marginBottom: 6, background: tc.cardBg, border: tc.cardBorder, backdropFilter: tc.isTequila ? "blur(12px)" : undefined }}>
            <div style={{ width: 20, fontSize: 12, color: idx < 3 ? tc.highlight : tc.hintColor, fontWeight: 700, marginRight: 8, textAlign: "center", flexShrink: 0 }}>
              {idx + 1}
            </div>
            <div onClick={() => handlePlayTrack(t)}
              style={{ width: 44, height: 44, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12, cursor: "pointer",
                background: tc.coverPlaceholderBg,
                border: `1px solid ${tc.accentBorderAlpha}`,
                display: "flex", alignItems: "center", justifyContent: "center" }}>
              {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={22} color={tc.hintColor} />}
            </div>
            <div onClick={() => handlePlayTrack(t)} style={{ flex: 1, minWidth: 0, cursor: "pointer" }}>
              <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: tc.textColor }}>{t.title}</div>
              <div style={{ fontSize: 12, color: tc.hintColor }}>{t.artist}</div>
            </div>
            <button onClick={() => openAddMenu(t)}
              style={{ width: 32, height: 32, borderRadius: 8, border: "none", background: "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <IconPlus size={16} color={tc.hintColor} />
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
              background: tc.isTequila ? "rgba(40, 25, 15, 0.95)" : "var(--tg-theme-bg-color, #1a1a2e)",
              border: `1px solid ${tc.accentBorderAlpha}`,
              backdropFilter: "blur(20px)",
            }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: tc.hintColor, opacity: 0.3, margin: "0 auto 12px" }} />
            <div style={{ fontSize: 13, color: tc.hintColor, marginBottom: 4 }}>Добавить в плейлист</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: tc.textColor, marginBottom: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {addMenuTrack.artist} — {addMenuTrack.title}
            </div>
            {playlists.length === 0 ? (
              <div style={{ textAlign: "center", color: tc.hintColor, padding: 20 }}>Нет плейлистов</div>
            ) : (
              playlists.map((p) => (
                <button key={p.id} onClick={() => handleAdd(p.id)} disabled={addingTo === p.id}
                  style={{
                    display: "flex", alignItems: "center", width: "100%", padding: "10px 14px",
                    borderRadius: 12, border: tc.cardBorder, background: tc.cardBg,
                    marginBottom: 6, cursor: "pointer", textAlign: "left",
                    opacity: addingTo === p.id ? 0.5 : 1,
                  }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: tc.activeBg, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                    <IconMusic size={16} color="#fff" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, color: tc.textColor }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: tc.hintColor }}>{p.track_count} треков</div>
                  </div>
                  {addingTo === p.id ? <IconSpinner size={16} color={tc.hintColor} /> : <IconPlus size={16} color={tc.highlight} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Save chart as NEW playlist modal */}
      {showSaveChart && (
        <div onClick={() => { if (!savingChart) setShowSaveChart(false); }}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 10000, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 420, padding: "16px 16px 24px",
              borderRadius: "20px 20px 0 0",
              background: tc.isTequila ? "rgba(40, 25, 15, 0.95)" : "var(--tg-theme-bg-color, #1a1a2e)",
              border: `1px solid ${tc.accentBorderAlpha}`,
              backdropFilter: "blur(20px)",
            }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: tc.hintColor, opacity: 0.3, margin: "0 auto 12px" }} />
            <div style={{ fontSize: 14, fontWeight: 600, color: tc.textColor, marginBottom: 4 }}>Сохранить чарт как плейлист</div>
            <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 14 }}>{tracks.length} треков</div>
            <input
              type="text" value={saveChartName} disabled={savingChart}
              onInput={(e) => setSaveChartName((e.target as HTMLInputElement).value)}
              placeholder="Название плейлиста"
              style={{
                width: "100%", padding: "10px 14px", borderRadius: 12, fontSize: 14,
                border: `1px solid ${tc.accentBorderAlpha}`,
                background: tc.isTequila ? "rgba(30, 18, 10, 0.6)" : "rgba(255,255,255,0.05)",
                color: tc.textColor, outline: "none", marginBottom: 12, boxSizing: "border-box",
              }}
            />
            {saveProgress && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 4 }}>
                  {saveProgress.done}/{saveProgress.total}
                </div>
                <div style={{ width: "100%", height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)" }}>
                  <div style={{
                    width: `${(saveProgress.done / saveProgress.total) * 100}%`, height: "100%", borderRadius: 2,
                    background: tc.accentGradient,
                    transition: "width 0.2s ease",
                  }} />
                </div>
              </div>
            )}
            <button onClick={handleSaveChartAsNew} disabled={savingChart || !saveChartName.trim()}
              style={{
                width: "100%", padding: "12px", borderRadius: 12, border: "none",
                background: tc.accentGradient,
                color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer",
                opacity: savingChart || !saveChartName.trim() ? 0.5 : 1,
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              }}>
              {savingChart ? <><IconSpinner size={16} color="#fff" /> Сохраняю...</> : <><IconSave size={16} color="#fff" /> Сохранить</>}
            </button>
          </div>
        </div>
      )}

      {/* Save chart to EXISTING playlist modal */}
      {showSaveMenu && (
        <div onClick={() => { if (!addingTo) setShowSaveMenu(false); }}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 10000, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 420, maxHeight: "60vh", overflowY: "auto", padding: "16px 16px 24px",
              borderRadius: "20px 20px 0 0",
              background: tc.isTequila ? "rgba(40, 25, 15, 0.95)" : "var(--tg-theme-bg-color, #1a1a2e)",
              border: `1px solid ${tc.accentBorderAlpha}`,
              backdropFilter: "blur(20px)",
            }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: tc.hintColor, opacity: 0.3, margin: "0 auto 12px" }} />
            <div style={{ fontSize: 14, fontWeight: 600, color: tc.textColor, marginBottom: 4 }}>Добавить чарт в плейлист</div>
            <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 14 }}>{tracks.length} треков</div>
            {saveProgress && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 4 }}>
                  {saveProgress.done}/{saveProgress.total}
                </div>
                <div style={{ width: "100%", height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)" }}>
                  <div style={{
                    width: `${(saveProgress.done / saveProgress.total) * 100}%`, height: "100%", borderRadius: 2,
                    background: tc.accentGradient,
                    transition: "width 0.2s ease",
                  }} />
                </div>
              </div>
            )}
            {playlists.length === 0 ? (
              <div style={{ textAlign: "center", color: tc.hintColor, padding: 20 }}>Нет плейлистов</div>
            ) : (
              playlists.map((p) => (
                <button key={p.id} onClick={() => handleSaveChartToExisting(p.id)} disabled={addingTo !== null}
                  style={{
                    display: "flex", alignItems: "center", width: "100%", padding: "10px 14px",
                    borderRadius: 12, border: tc.cardBorder, background: tc.cardBg,
                    marginBottom: 6, cursor: "pointer", textAlign: "left",
                    opacity: addingTo === p.id ? 0.5 : 1,
                  }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: tc.activeBg, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                    <IconMusic size={16} color="#fff" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, color: tc.textColor }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: tc.hintColor }}>{p.track_count} треков</div>
                  </div>
                  {addingTo === p.id ? <IconSpinner size={16} color={tc.hintColor} /> : <IconPlus size={16} color={tc.highlight} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
});
