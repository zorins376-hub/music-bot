import { useState, useEffect, useRef } from "preact/hooks";
import type { PlayerState } from "../api";

interface Props {
  state: PlayerState;
  onAction: (action: string, trackId?: string, seekPos?: number) => void;
  onShowLyrics: (trackId: string) => void;
}

const btnStyle: Record<string, string | number> = {
  background: "none",
  border: "none",
  color: "var(--tg-theme-text-color, #eee)",
  fontSize: 24,
  cursor: "pointer",
  padding: "8px",
};

export function Player({ state, onAction, onShowLyrics }: Props) {
  const track = state.current_track;
  const duration = track?.duration ?? 0;
  const [elapsed, setElapsed] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const intervalRef = useRef<number | null>(null);

  // Tick elapsed time while playing
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (state.is_playing && duration > 0) {
      intervalRef.current = window.setInterval(() => {
        setElapsed((e) => (e < duration ? e + 1 : 0));
      }, 1000);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [state.is_playing, track?.video_id]);

  // Reset elapsed on track change
  useEffect(() => { setElapsed(0); }, [track?.video_id]);

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? "0" : ""}${sec}`;
  };

  return (
    <div style={{ textAlign: "center", padding: "16px 0" }}>
      {/* Cover placeholder */}
      <div
        style={{
          width: 200,
          height: 200,
          margin: "0 auto 16px",
          borderRadius: 16,
          background: "linear-gradient(135deg, #7c4dff 0%, #e040fb 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 64,
        }}
      >
        {track ? "♫" : "♪"}
      </div>

      {/* Track info */}
      <div style={{ marginBottom: 4, fontSize: 18, fontWeight: 600 }}>
        {track?.title ?? "Ничего не играет"}
      </div>
      <div style={{ fontSize: 14, color: "var(--tg-theme-hint-color, #aaa)", marginBottom: 16 }}>
        {track?.artist ?? "—"}
        {track && (
          <span style={{ marginLeft: 8, fontSize: 12 }}>({track.duration_fmt})</span>
        )}
      </div>

      {/* Seek slider */}
      {track && duration > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36, textAlign: "right" }}>
            {fmtTime(elapsed)}
          </span>
          <input
            type="range"
            min={0}
            max={duration}
            value={seeking ? undefined : elapsed}
            onInput={(e) => {
              setSeeking(true);
              setElapsed(Number((e.target as HTMLInputElement).value));
            }}
            onChange={(e) => {
              const pos = Number((e.target as HTMLInputElement).value);
              setElapsed(pos);
              setSeeking(false);
              onAction("seek", track.video_id, pos);
            }}
            style={{ flex: 1, accentColor: "var(--tg-theme-button-color, #7c4dff)" }}
          />
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36 }}>
            {fmtTime(duration)}
          </span>
        </div>
      )}

      {/* Controls */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 4 }}>
        <button style={btnStyle} onClick={() => onAction("shuffle")}>
          {state.shuffle ? "🔀" : "➡️"}
        </button>
        <button style={btnStyle} onClick={() => onAction("prev")}>⏮</button>
        <button
          style={{ ...btnStyle, fontSize: 40 }}
          onClick={() => onAction(state.is_playing ? "pause" : "play")}
        >
          {state.is_playing ? "⏸" : "▶️"}
        </button>
        <button style={btnStyle} onClick={() => onAction("next")}>⏭</button>
        <button style={btnStyle} onClick={() => onAction("repeat")}>
          {state.repeat_mode === "one" ? "🔂" : state.repeat_mode === "all" ? "🔁" : "➡️"}
        </button>
      </div>

      {/* Lyrics button */}
      {track && (
        <button
          onClick={() => onShowLyrics(track.video_id)}
          style={{
            marginTop: 12,
            padding: "6px 16px",
            borderRadius: 16,
            border: "1px solid var(--tg-theme-hint-color, #555)",
            background: "transparent",
            color: "var(--tg-theme-text-color, #eee)",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          📝 Текст песни
        </button>
      )}
    </div>
  );
}
