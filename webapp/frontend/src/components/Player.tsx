import { useState, useEffect, useRef } from "preact/hooks";
import type { PlayerState } from "../api";
import { toggleFavorite, checkFavorite } from "../api";

interface Props {
  state: PlayerState;
  onAction: (action: string, trackId?: string, seekPos?: number) => void;
  onShowLyrics: (trackId: string) => void;
  accentColor?: string;
  accentColorAlpha?: string;
}

// --- Haptic Feedback Helper ---
const haptic = (type: "light" | "medium" | "heavy" | "rigid" | "soft" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

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
const IconShuffle = ({ active, color = "#7c4dff" }: { active: boolean; color?: string }) => <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? color : "var(--tg-theme-hint-color, #888)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>;
const IconRepeat = ({ mode, activeColor = "#7c4dff" }: { mode: string; activeColor?: string }) => {
  const active = mode !== "off";
  const isOne = mode === "one";
  const color = active ? activeColor : "var(--tg-theme-hint-color, #888)";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>
      <polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>
      {isOne && <text x="10" y="16" fontSize="10" fill={color} stroke="none" fontWeight="bold">1</text>}
    </svg>
  );
};
const IconLyrics = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>;
const IconHeart = ({ filled }: { filled: boolean }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill={filled ? "#ff4081" : "none"} stroke={filled ? "#ff4081" : "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

// --- Audio Visualizer (animated equalizer bars) ---
function AudioVisualizer({ isPlaying }: { isPlaying: boolean }) {
  const bars = [
    { delay: "0s", minH: 20, maxH: 60 },
    { delay: "0.1s", minH: 15, maxH: 80 },
    { delay: "0.2s", minH: 25, maxH: 70 },
    { delay: "0.15s", minH: 10, maxH: 90 },
    { delay: "0.25s", minH: 20, maxH: 65 },
  ];

  return (
    <div
      style={{
        position: "absolute",
        bottom: 12,
        left: "50%",
        transform: "translateX(-50%)",
        display: "flex",
        alignItems: "flex-end",
        gap: 4,
        height: 32,
        padding: "4px 12px",
        background: "rgba(0,0,0,0.5)",
        borderRadius: 16,
        backdropFilter: "blur(8px)",
      }}
    >
      {bars.map((bar, i) => (
        <div
          key={i}
          style={{
            width: 4,
            borderRadius: 2,
            background: `linear-gradient(to top, ${accentColor || '#7c4dff'}, #e040fb)`,
            animation: isPlaying ? `visualizer 0.5s ease-in-out ${bar.delay} infinite alternate` : "none",
            height: isPlaying ? undefined : 8,
          }}
        />
      ))}
      <style>{`
        @keyframes visualizer {
          0% { height: 8px; }
          100% { height: 28px; }
        }
      `}</style>
    </div>
  );
}

// --- Marquee Component for long text ---
function Marquee({ text, style }: { text: string; style?: Record<string, string | number> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);

  useEffect(() => {
    if (containerRef.current && textRef.current) {
      setNeedsScroll(textRef.current.scrollWidth > containerRef.current.clientWidth);
    }
  }, [text]);

  return (
    <div
      ref={containerRef}
      style={{
        overflow: "hidden",
        whiteSpace: "nowrap",
        position: "relative",
        ...style,
      }}
    >
      <span
        ref={textRef}
        style={{
          display: "inline-block",
          paddingRight: needsScroll ? 50 : 0,
          animation: needsScroll ? "marquee 8s linear infinite" : "none",
        }}
      >
        {text}
      </span>
      {needsScroll && (
        <span style={{ display: "inline-block", paddingRight: 50, animation: "marquee 8s linear infinite" }}>
          {text}
        </span>
      )}
      <style>{`
        @keyframes marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}

export function Player({ state, onAction, onShowLyrics, accentColor = "rgb(124, 77, 255)", accentColorAlpha = "rgba(124, 77, 255, 0.4)" }: Props) {
  const track = state.current_track;
  const duration = track?.duration ?? 0;
  const [elapsed, setElapsed] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const [isLiked, setIsLiked] = useState(false);
  const intervalRef = useRef<number | null>(null);

  // Swipe tracking
  const touchStartX = useRef<number>(0);
  const touchEndX = useRef<number>(0);
  const [swipeOffset, setSwipeOffset] = useState(0);

  // Check if current track is liked
  useEffect(() => {
    if (track?.video_id) {
      checkFavorite(track.video_id).then(setIsLiked).catch(() => setIsLiked(false));
    } else {
      setIsLiked(false);
    }
  }, [track?.video_id]);

  const handleLikeToggle = async () => {
    if (!track) return;
    haptic(isLiked ? "light" : "medium");
    try {
      const newState = await toggleFavorite(track.video_id);
      setIsLiked(newState);
    } catch {}
  };

  const handleTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchEndX.current = e.touches[0].clientX;
  };

  const handleTouchMove = (e: TouchEvent) => {
    touchEndX.current = e.touches[0].clientX;
    const diff = touchEndX.current - touchStartX.current;
    setSwipeOffset(Math.max(-80, Math.min(80, diff)));
  };

  const handleTouchEnd = () => {
    const diff = touchEndX.current - touchStartX.current;
    if (diff > 60) {
      haptic("medium");
      onAction("prev");
    } else if (diff < -60) {
      haptic("medium");
      onAction("next");
    }
    setSwipeOffset(0);
  };

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
      {/* Cover container with swipe */}
      <div
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        style={{
          position: "relative",
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
          transition: swipeOffset === 0 ? "transform 0.3s ease-out" : "none",
          transform: `translateX(${swipeOffset}px) scale(${state.is_playing ? 1.02 : 1})`,
          touchAction: "pan-y",
          userSelect: "none",
        }}
      >
        {track?.cover_url ? (
          <img 
            src={track.cover_url} 
            alt="Cover" 
            style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none" }} 
            draggable={false}
          />
        ) : (
          track ? "♫" : "♪"
        )}
        {/* Audio Visualizer overlay */}
        {track && <AudioVisualizer isPlaying={state.is_playing} />}
      </div>

      {/* Track info with Marquee */}
      <div style={{ padding: "0 24px", marginBottom: 4 }}>
        <Marquee
          text={track?.title ?? "Ничего не играет"}
          style={{ fontSize: 18, fontWeight: 600 }}
        />
      </div>
      <div style={{ padding: "0 24px", fontSize: 14, color: "var(--tg-theme-hint-color, #aaa)", marginBottom: 16 }}>
        <Marquee
          text={track ? `${track.artist} • ${track.duration_fmt}` : "—"}
          style={{}}
        />
      </div>

      {/* Seek slider - improved touch area */}
      {track && duration > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36, textAlign: "right" }}>
            {fmtTime(elapsed)}
          </span>
          <div style={{ flex: 1, padding: "12px 0", touchAction: "none" }}>
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
                haptic("light");
                onAction("seek", track.video_id, pos);
              }}
              style={{
                width: "100%",
                height: 6,
                accentColor: "var(--tg-theme-button-color, #7c4dff)",
                cursor: "pointer",
              }}
            />
          </div>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36 }}>
            {fmtTime(duration)}
          </span>
        </div>
      )}

      {/* Controls with haptic feedback */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 16 }}>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("shuffle"); }}>
          <IconShuffle active={state.shuffle} color={accentColor} />
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("prev"); }}>
          <IconSkipBack />
        </button>
        <button
          style={{ ...btnStyle, background: accentColor, color: "#fff", borderRadius: "50%", padding: 12, width: 64, height: 64, boxShadow: `0 4px 12px ${accentColorAlpha}`, transition: "background 0.5s ease, box-shadow 0.5s ease" }}
          onClick={() => { haptic("heavy"); onAction(state.is_playing ? "pause" : "play"); }}
        >
          {state.is_playing ? <IconPause /> : <IconPlay />}
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("next"); }}>
          <IconSkipForward />
        </button>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("repeat"); }}>
          <IconRepeat mode={state.repeat_mode} activeColor={accentColor} />
        </button>
      </div>

      {/* Lyrics & Like buttons */}
      {track && (
        <div style={{ display: "flex", justifyContent: "center", gap: 12, marginTop: 24 }}>
          <button
            onClick={() => { haptic("light"); onShowLyrics(track.video_id); }}
            style={{
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
          <button
            onClick={handleLikeToggle}
            style={{
              padding: "8px 16px",
              borderRadius: 20,
              border: `1px solid ${isLiked ? "#ff4081" : "var(--tg-theme-hint-color, #555)"}`,
              background: isLiked ? "rgba(255, 64, 129, 0.1)" : "transparent",
              color: isLiked ? "#ff4081" : "var(--tg-theme-text-color, #eee)",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              transition: "all 0.2s ease",
            }}
          >
            <IconHeart filled={isLiked} />
          </button>
        </div>
      )}
    </div>
  );
}
