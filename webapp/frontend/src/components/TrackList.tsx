import type { Track } from "../api";

interface Props {
  tracks: Track[];
  currentIndex: number;
  onPlay: (track: Track) => void;
}

export function TrackList({ tracks, currentIndex, onPlay }: Props) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
        Очередь ({tracks.length})
      </div>
      {tracks.map((t, i) => (
        <div
          key={t.video_id}
          onClick={() => onPlay(t)}
          style={{
            display: "flex",
            alignItems: "center",
            padding: "8px 12px",
            borderRadius: 8,
            marginBottom: 4,
            cursor: "pointer",
            background: i === currentIndex
              ? "var(--tg-theme-button-color, #7c4dff)"
              : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: i === currentIndex ? 600 : 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {t.title}
            </div>
            <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)" }}>
              {t.artist}
            </div>
          </div>
          <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)", marginLeft: 8 }}>
            {t.duration_fmt}
          </div>
        </div>
      ))}
    </div>
  );
}
