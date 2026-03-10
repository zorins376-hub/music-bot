import { useRef } from "preact/hooks";
import type { PlayerState } from "../api";
import { IconMusic } from "./Icons";

interface Props {
  state: PlayerState;
  accentColor: string;
  onAction: (action: string) => void;
  onExpand: () => void;
}

const haptic = (type: "light" | "medium" | "heavy" = "light") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type); } catch {}
};

export function MiniPlayer({ state, accentColor, onAction, onExpand }: Props) {
  const track = state.current_track;
  if (!track) return null;

  // Swipe tracking
  const touchStartX = useRef(0);

  const handleTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  };
  const handleTouchEnd = (e: TouchEvent) => {
    const diff = e.changedTouches[0].clientX - touchStartX.current;
    if (diff > 60) { haptic("medium"); onAction("prev"); }
    else if (diff < -60) { haptic("medium"); onAction("next"); }
  };

  return (
    <div
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onClick={onExpand}
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        background: "rgba(20, 20, 30, 0.92)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderTop: `2px solid ${accentColor}`,
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        cursor: "pointer",
        touchAction: "pan-y",
        userSelect: "none",
      }}
    >
      {/* Mini cover */}
      <div style={{
        width: 44,
        height: 44,
        borderRadius: 8,
        overflow: "hidden",
        flexShrink: 0,
        background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
      }}>
        {track.cover_url ? (
          <img src={track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <IconMusic size={24} color="rgba(255,255,255,0.6)" />
          </div>
        )}
      </div>

      {/* Track info */}
      <div style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
        <div style={{
          fontSize: 13,
          fontWeight: 600,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          color: "var(--tg-theme-text-color, #eee)",
        }}>
          {track.title}
        </div>
        <div style={{
          fontSize: 11,
          color: "var(--tg-theme-hint-color, #aaa)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}>
          {track.artist}
        </div>
      </div>

      {/* Play/Pause button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          haptic("medium");
          onAction(state.is_playing ? "pause" : "play");
        }}
        style={{
          background: accentColor,
          border: "none",
          borderRadius: "50%",
          width: 36,
          height: 36,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          color: "#fff",
          flexShrink: 0,
        }}
      >
        {state.is_playing ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg>
        )}
      </button>

      {/* Next button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          haptic("light");
          onAction("next");
        }}
        style={{
          background: "none",
          border: "none",
          color: "var(--tg-theme-text-color, #eee)",
          cursor: "pointer",
          padding: 4,
          display: "flex",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19" stroke="currentColor" strokeWidth="2"/></svg>
      </button>
    </div>
  );
}
