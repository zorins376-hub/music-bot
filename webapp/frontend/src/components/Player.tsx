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
  cursor: "pointer",
  padding: "8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

// --- SVG Icons ---
const IconPlay = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>;
const IconPause = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>;
const IconSkipForward = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19" strokeWidth="2"/></svg>;
const IconSkipBack = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5" strokeWidth="2"/></svg>;
const IconShuffle = ({ active }: { active: boolean }) => <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? "#7c4dff" : "var(--tg-theme-hint-color, #888)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>;
const IconRepeat = ({ mode }: { mode: string }) => {
  const active = mode !== "off";
  const isOne = mode === "one";
  const color = active ? "#7c4dff" : "var(--tg-theme-hint-color, #888)";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>
      <polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>
      {isOne && <text x="10" y="16" fontSize="10" fill={color} stroke="none" fontWeight="bold">1</text>}
    </svg>
  );
};
const IconLyrics = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>;

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
      {/* Cover container */}
      <div
        style={{
          width: 240,
          height: 240,
          margin: "0 auto 24px",
          borderRadius: 20,
          background: track ? "var(--tg-theme-secondary-bg-color, #2a2a3e)" : "linear-gradient(135deg, #7c4dff 0%, #e040fb 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 64,
          boxShadow: track ? "0 8px 24px rgba(0,0,0,0.3)" : "none",
          overflow: "hidden",
          transition: "transform 0.2s ease-out",
          transform: state.is_playing ? "scale(1.02)" : "scale(1)",
        }}
      >
        {track?.cover_url ? (
          <img 
            src={track.cover_url} 
            alt="Cover" 
            style={{ width: "100%", height: "100%", objectFit: "cover" }} 
          />
        ) : (
          track ? "♫" : "♪"
        )}
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
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 16 }}>
        <button style={btnStyle} onClick={() => onAction("shuffle")}>
          <IconShuffle active={state.shuffle} />
        </button>
        <button style={btnStyle} onClick={() => onAction("prev")}>
          <IconSkipBack />
        </button>
        <button
          style={{ ...btnStyle, background: "var(--tg-theme-button-color, #7c4dff)", color: "#fff", borderRadius: "50%", padding: 12, width: 64, height: 64, boxShadow: "0 4px 12px rgba(124, 77, 255, 0.4)" }}
          onClick={() => onAction(state.is_playing ? "pause" : "play")}
        >
          {state.is_playing ? <IconPause /> : <IconPlay />}
        </button>
        <button style={btnStyle} onClick={() => onAction("next")}>
          <IconSkipForward />
        </button>
        <button style={btnStyle} onClick={() => onAction("repeat")}>
          <IconRepeat mode={state.repeat_mode} />
        </button>
      </div>

      {/* Lyrics button */}
      {track && (
        <button
          onClick={() => onShowLyrics(track.video_id)}
          style={{
            marginTop: 24,
            padding: "8px 20px",
            borderRadius: 20,
            border: "1px solid var(--tg-theme-hint-color, #555)",
            background: "transparent",
            color: "var(--tg-theme-text-color, #eee)",
            fontSize: 14,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
          }}
        >
          <IconLyrics /> Текст песни
        </button>
      )}
    </div>
  );
}
