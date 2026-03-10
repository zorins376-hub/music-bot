import { useState, useEffect } from "preact/hooks";
import { fetchPlaylists, fetchPlaylistTracks, type Playlist, type Track } from "../api";
import { IconArrowLeft, IconMusic, IconSpinner } from "./Icons";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

export function PlaylistView({ userId, onPlayTrack, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const isTequila = themeId === "tequila";
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPlaylists(userId)
      .then(setPlaylists)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => {
    if (selectedId !== null) {
      setLoading(true);
      fetchPlaylistTracks(selectedId)
        .then(setTracks)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [selectedId]);

  if (loading) return <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)"} /></div>;

  if (selectedId !== null) {
    return (
      <div>
        <button
          onClick={() => { setSelectedId(null); setTracks([]); }}
          style={{ background: "none", border: "none", color: isTequila ? "#ffd54f" : "var(--tg-theme-link-color, #7c4dff)", cursor: "pointer", marginBottom: 8, fontSize: 14, display: "flex", alignItems: "center", gap: 4 }}
        >
          <IconArrowLeft size={16} /> Назад
        </button>
        {tracks.length === 0 ? (
          <div style={{ textAlign: "center", color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)", padding: 32 }}>Пусто</div>
        ) : (
          tracks.map((t) => (
            <div
              key={t.video_id}
              onClick={() => onPlayTrack(t)}
              style={{
                display: "flex",
                alignItems: "center",
                padding: isTequila ? "10px 12px" : "8px 12px",
                borderRadius: 12,
                marginBottom: 6,
                cursor: "pointer",
                background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
                border: isTequila ? "1px solid rgba(255, 213, 79, 0.1)" : "none",
                backdropFilter: isTequila ? "blur(12px)" : undefined,
                boxShadow: isTequila ? "0 4px 14px rgba(0,0,0,0.18)" : "none",
              }}
            >
              <div style={{
                width: 44,
                height: 44,
                borderRadius: 10,
                overflow: "hidden",
                flexShrink: 0,
                marginRight: 12,
                background: isTequila ? "rgba(255, 213, 79, 0.08)" : "var(--tg-theme-bg-color, #1a1a2e)",
                border: isTequila ? "1px solid rgba(255, 213, 79, 0.14)" : "1px solid rgba(255,255,255,0.06)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}>
                {t.cover_url ? (
                  <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <IconMusic size={22} color={isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #888)"} />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: isTequila ? "#fef0e0" : undefined }}>{t.title}</div>
                <div style={{ fontSize: 12, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>{t.artist}</div>
              </div>
              <div style={{ fontSize: 12, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>{t.duration_fmt}</div>
            </div>
          ))
        )}
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10, color: isTequila ? "#fef0e0" : undefined, letterSpacing: isTequila ? 0.4 : 0 }}>Мои плейлисты</div>
      {playlists.length === 0 ? (
        <div style={{ textAlign: "center", color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)", padding: 32 }}>Нет плейлистов</div>
      ) : (
        playlists.map((p) => (
          <div
            key={p.id}
            onClick={() => setSelectedId(p.id)}
            style={{
              padding: isTequila ? "12px 14px" : "10px 14px",
              borderRadius: 14,
              marginBottom: 6,
              cursor: "pointer",
              background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
              border: isTequila ? "1px solid rgba(255, 213, 79, 0.1)" : "none",
              backdropFilter: isTequila ? "blur(12px)" : undefined,
              boxShadow: isTequila ? "0 4px 14px rgba(0,0,0,0.18)" : "none",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span style={{ fontWeight: 500, color: isTequila ? "#fef0e0" : undefined }}>{p.name}</span>
            <span style={{ color: isTequila ? accentColor : "var(--tg-theme-hint-color, #aaa)", fontSize: 13 }}>{p.track_count} треков</span>
          </div>
        ))
      )}
    </div>
  );
}
