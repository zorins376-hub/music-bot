import { useState, useEffect } from "preact/hooks";
import { fetchPlaylists, fetchPlaylistTracks, type Playlist, type Track } from "../api";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
}

export function PlaylistView({ userId, onPlayTrack }: Props) {
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

  if (loading) return <div style={{ textAlign: "center", padding: 32 }}>⏳</div>;

  if (selectedId !== null) {
    return (
      <div>
        <button
          onClick={() => { setSelectedId(null); setTracks([]); }}
          style={{ background: "none", border: "none", color: "var(--tg-theme-link-color, #7c4dff)", cursor: "pointer", marginBottom: 8, fontSize: 14 }}
        >
          ← Назад
        </button>
        {tracks.length === 0 ? (
          <div style={{ textAlign: "center", color: "var(--tg-theme-hint-color, #aaa)", padding: 32 }}>Пусто</div>
        ) : (
          tracks.map((t) => (
            <div
              key={t.video_id}
              onClick={() => onPlayTrack(t)}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "8px 12px",
                borderRadius: 8,
                marginBottom: 4,
                cursor: "pointer",
                background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)" }}>{t.artist}</div>
              </div>
              <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)" }}>{t.duration_fmt}</div>
            </div>
          ))
        )}
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Мои плейлисты</div>
      {playlists.length === 0 ? (
        <div style={{ textAlign: "center", color: "var(--tg-theme-hint-color, #aaa)", padding: 32 }}>Нет плейлистов</div>
      ) : (
        playlists.map((p) => (
          <div
            key={p.id}
            onClick={() => setSelectedId(p.id)}
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              marginBottom: 4,
              cursor: "pointer",
              background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontWeight: 500 }}>{p.name}</span>
            <span style={{ color: "var(--tg-theme-hint-color, #aaa)", fontSize: 13 }}>{p.track_count} треков</span>
          </div>
        ))
      )}
    </div>
  );
}
