import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchPlaylists, fetchPlaylistTracks, createPlaylist, deletePlaylist,
  renamePlaylist, removeTrackFromPlaylist,
  type Playlist, type Track,
} from "../api";
import { IconArrowLeft, IconMusic, IconSpinner, IconClose, IconPlus, IconEdit } from "./Icons";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  onPlayAll?: (tracks: Track[]) => void;
  onPlayPlaylist?: (playlistId: number) => void;
  accentColor?: string;
  themeId?: string;
  currentTrack?: Track | null;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function PlaylistView({ userId, onPlayTrack, onPlayAll, onPlayPlaylist, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom", currentTrack }: Props) {
  const warm = themeId === "tequila";
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [swipedTrackId, setSwipedTrackId] = useState<string | null>(null);
  const touchStartX = useRef(0);

  const hintColor = warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)";
  const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
  const cardBg = warm ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)";
  const cardBorder = warm ? "1px solid rgba(255, 213, 79, 0.1)" : "1px solid rgba(255,255,255,0.06)";
  const activeBg = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))"
    : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.3))`;

  const reload = useCallback(() => {
    setLoading(true);
    fetchPlaylists(userId)
      .then(setPlaylists)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (selectedId !== null) {
      setLoading(true);
      fetchPlaylistTracks(selectedId)
        .then(setTracks)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [selectedId]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    haptic("medium");
    try {
      await createPlaylist(name);
      setNewName("");
      setShowCreate(false);
      reload();
    } catch {}
  };

  const handleRename = async (id: number) => {
    const name = editName.trim();
    if (!name) return;
    haptic("light");
    try {
      await renamePlaylist(id, name);
      setEditingId(null);
      reload();
    } catch {}
  };

  const handleDelete = async (id: number) => {
    haptic("heavy");
    try {
      await deletePlaylist(id);
      setConfirmDeleteId(null);
      if (selectedId === id) { setSelectedId(null); setTracks([]); }
      reload();
    } catch {}
  };

  const handleRemoveTrack = async (videoId: string) => {
    if (selectedId === null) return;
    haptic("medium");
    setTracks((prev) => prev.filter((t) => t.video_id !== videoId));
    try {
      await removeTrackFromPlaylist(selectedId, videoId);
      reload();
    } catch {}
    setSwipedTrackId(null);
  };

  const onTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    setSwipedTrackId(null);
  };

  const onTouchEnd = (e: TouchEvent, videoId: string) => {
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (dx < -60) setSwipedTrackId(videoId);
  };

  const trackRow = (t: Track, idx: number) => {
    const swiped = swipedTrackId === t.video_id;
    return (
      <div key={t.video_id} style={{ position: "relative", overflow: "hidden", borderRadius: 14, marginBottom: 6 }}>
        {swiped && (
          <button
            onClick={() => handleRemoveTrack(t.video_id)}
            style={{
              position: "absolute", right: 0, top: 0, bottom: 0, width: 70,
              background: "linear-gradient(135deg, #e53935, #ff1744)", border: "none",
              color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: "0 14px 14px 0",
            }}
          >Удалить</button>
        )}
        <div
          onTouchStart={(e: any) => onTouchStart(e)}
          onTouchEnd={(e: any) => onTouchEnd(e, t.video_id)}
          onClick={() => { if (!swiped) { haptic("light"); onPlayTrack(t); } else setSwipedTrackId(null); }}
          style={{
            display: "flex", alignItems: "center", padding: "10px 12px",
            background: cardBg, border: cardBorder, borderRadius: 14, cursor: "pointer",
            transition: "transform 0.25s ease",
            transform: swiped ? "translateX(-70px)" : "translateX(0)",
            backdropFilter: warm ? "blur(12px)" : undefined,
          }}
        >
          <div style={{ width: 14, fontSize: 11, color: hintColor, fontWeight: 600, marginRight: 8, textAlign: "center", flexShrink: 0 }}>{idx + 1}</div>
          <div style={{
            width: 44, height: 44, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12,
            background: warm ? "rgba(255, 213, 79, 0.08)" : "rgba(124,77,255,0.08)",
            border: warm ? "1px solid rgba(255, 213, 79, 0.14)" : "1px solid rgba(255,255,255,0.06)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={22} color={hintColor} />}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: textColor }}>{t.title}</div>
            <div style={{ fontSize: 12, color: hintColor }}>{t.artist}</div>
          </div>
          <div style={{ fontSize: 12, color: hintColor, flexShrink: 0 }}>{t.duration_fmt}</div>
        </div>
      </div>
    );
  };

  if (loading && !playlists.length && selectedId === null) {
    return <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={hintColor} /></div>;
  }

  // ── Tracks view ──
  if (selectedId !== null) {
    return (
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <button onClick={() => { setSelectedId(null); setTracks([]); setSwipedTrackId(null); }}
            style={{ background: "none", border: "none", color: warm ? "#ffd54f" : accentColor, cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontSize: 14 }}>
            <IconArrowLeft size={16} /> Назад
          </button>
          <div style={{ flex: 1, fontSize: 15, fontWeight: 600, color: textColor, textAlign: "center" }}>{selectedName}</div>
          <div style={{ width: 44 }} />
        </div>

        {tracks.length > 0 && (
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <button onClick={() => { haptic("medium"); if (onPlayPlaylist && selectedId) onPlayPlaylist(selectedId); else if (onPlayAll) onPlayAll(tracks); else if (tracks[0]) onPlayTrack(tracks[0]); }}
              style={{ flex: 1, padding: "10px 0", borderRadius: 14, border: "none", background: activeBg, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              ▶ Воспроизвести всё
            </button>
          </div>
        )}

        <div style={{ fontSize: 11, color: hintColor, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
          {tracks.length} треков · свайп влево — удалить
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={hintColor} /></div>
        ) : tracks.length === 0 ? (
          <div style={{ textAlign: "center", color: hintColor, padding: 32 }}>Плейлист пуст</div>
        ) : tracks.map((t, idx) => trackRow(t, idx))}
      </div>
    );
  }

  // ── Playlists list ──
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: textColor, letterSpacing: 0.4 }}>Мои плейлисты</div>
        <button onClick={() => { haptic("light"); setShowCreate(true); }}
          style={{ padding: "6px 14px", borderRadius: 14, border: "none", background: activeBg, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
          + Создать
        </button>
      </div>

      {showCreate && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12, padding: 12, borderRadius: 16, background: cardBg, border: cardBorder }}>
          <input type="text" placeholder="Название плейлиста" maxLength={100} value={newName}
            onInput={(e: any) => setNewName(e.target.value)}
            onKeyDown={(e: any) => { if (e.key === "Enter") handleCreate(); }}
            style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)", background: "transparent", color: textColor, fontSize: 14, outline: "none" }} />
          <button onClick={handleCreate} style={{ padding: "8px 16px", borderRadius: 10, border: "none", background: accentColor, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>OK</button>
          <button onClick={() => { setShowCreate(false); setNewName(""); }} style={{ padding: "8px 12px", borderRadius: 10, border: cardBorder, background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer" }}><IconClose size={14} /></button>
        </div>
      )}

      {playlists.length === 0 && !showCreate ? (
        <div style={{ textAlign: "center", color: hintColor, padding: 32 }}>Нет плейлистов — нажмите «+ Создать»</div>
      ) : (
        playlists.map((p) => (
          <div key={p.id} style={{ marginBottom: 6 }}>
            {confirmDeleteId === p.id ? (
              <div style={{ display: "flex", gap: 8, padding: 12, borderRadius: 14, background: "rgba(229, 57, 53, 0.15)", border: "1px solid rgba(229, 57, 53, 0.3)", alignItems: "center" }}>
                <span style={{ flex: 1, fontSize: 13, color: "#ef5350" }}>Удалить «{p.name}»?</span>
                <button onClick={() => handleDelete(p.id)} style={{ padding: "6px 14px", borderRadius: 10, border: "none", background: "#e53935", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Да</button>
                <button onClick={() => setConfirmDeleteId(null)} style={{ padding: "6px 14px", borderRadius: 10, border: cardBorder, background: "transparent", color: hintColor, fontSize: 12, cursor: "pointer" }}>Нет</button>
              </div>
            ) : editingId === p.id ? (
              <div style={{ display: "flex", gap: 8, padding: 12, borderRadius: 14, background: cardBg, border: cardBorder }}>
                <input type="text" maxLength={100} value={editName}
                  onInput={(e: any) => setEditName(e.target.value)}
                  onKeyDown={(e: any) => { if (e.key === "Enter") handleRename(p.id); }}
                  style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)", background: "transparent", color: textColor, fontSize: 14, outline: "none" }} />
                <button onClick={() => handleRename(p.id)} style={{ padding: "8px 14px", borderRadius: 10, border: "none", background: accentColor, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>✓</button>
                <button onClick={() => setEditingId(null)} style={{ padding: "8px 10px", borderRadius: 10, border: cardBorder, background: "transparent", color: hintColor, fontSize: 12, cursor: "pointer" }}><IconClose size={14} /></button>
              </div>
            ) : (
              <div onClick={() => { haptic("light"); setSelectedId(p.id); setSelectedName(p.name); }}
                style={{ display: "flex", alignItems: "center", padding: "12px 14px", borderRadius: 14, cursor: "pointer", background: cardBg, border: cardBorder, backdropFilter: warm ? "blur(12px)" : undefined }}>
                <div style={{ width: 42, height: 42, borderRadius: 12, marginRight: 12, flexShrink: 0, background: activeBg, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <IconMusic size={20} color="#fff" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, color: textColor }}>{p.name}</div>
                  <div style={{ fontSize: 12, color: hintColor }}>{p.track_count} треков</div>
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  <button onClick={(e) => { e.stopPropagation(); haptic("light"); setEditingId(p.id); setEditName(p.name); }}
                    style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: hintColor, fontSize: 14, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><IconEdit size={14} /></button>
                  <button onClick={(e) => { e.stopPropagation(); haptic("light"); setConfirmDeleteId(p.id); }}
                    style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: "#ef5350", fontSize: 14, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><IconClose size={14} /></button>
                </div>
              </div>
            )}
          </div>
        ))
      )}

      {currentTrack && playlists.length > 0 && (
        <div style={{ marginTop: 16, padding: 12, borderRadius: 14, background: warm ? "rgba(255, 213, 79, 0.06)" : "rgba(124, 77, 255, 0.06)", border: warm ? "1px solid rgba(255,213,79,0.12)" : "1px solid rgba(124,77,255,0.1)", fontSize: 12, color: hintColor, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
          Чтобы добавить трек в плейлист — нажми <IconPlus size={12} /> в плеере
        </div>
      )}
    </div>
  );
}
