import { useRef, useState, useEffect } from "preact/hooks";
import type { PlayerState } from "../api";
import { toggleFavorite, checkFavorite } from "../api";
import { IconMusic } from "./Icons";

interface Props {
  state: PlayerState;
  accentColor: string;
  themeId?: string;
  elapsed?: number;
  audioDuration?: number;
  onAction: (action: string) => void;
  onExpand: () => void;
}

const haptic = (type: "light" | "medium" | "heavy" = "light") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type); } catch {}
};

export function MiniPlayer({ state, accentColor, themeId = "blackroom", elapsed = 0, audioDuration = 0, onAction, onExpand }: Props) {
  const track = state.current_track;
  if (!track) return null;
  const isTequila = themeId === "tequila";
  const duration = audioDuration || track.duration || 0;
  const progress = duration > 0 ? Math.min(1, elapsed / duration) : 0;

  // Like state
  const [isLiked, setIsLiked] = useState(false);
  useEffect(() => {
    if (track?.video_id) {
      checkFavorite(track.video_id).then(setIsLiked).catch(() => setIsLiked(false));
    }
  }, [track?.video_id]);

  const handleLike = async (e: Event) => {
    e.stopPropagation();
    if (!track) return;
    haptic("medium");
    try {
      const newState = await toggleFavorite(track.video_id);
      setIsLiked(newState);
    } catch {}
  };

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
        background: isTequila ? "rgba(40, 25, 15, 0.88)" : "rgba(20, 20, 30, 0.92)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderTop: `2px solid ${accentColor}`,
        boxShadow: isTequila ? "0 -10px 30px rgba(255, 109, 0, 0.18)" : "none",
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        cursor: "pointer",
        touchAction: "pan-y",
        userSelect: "none",
      }}
    >
      {/* Progress bar at top */}
      <div style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: 2,
        background: "rgba(255,255,255,0.08)",
      }}>
        <div style={{
          height: "100%",
          width: `${progress * 100}%`,
          background: isTequila ? "linear-gradient(90deg, #ff6d00, #ffd54f)" : accentColor,
          transition: "width 0.5s linear",
          borderRadius: 1,
        }} />
      </div>

      {/* Mini cover */}
      <div style={{
        width: 44,
        height: 44,
        borderRadius: 8,
        overflow: "hidden",
        flexShrink: 0,
        background: isTequila ? "rgba(255, 213, 79, 0.08)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
        border: isTequila ? "1px solid rgba(255, 213, 79, 0.18)" : "none",
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
          color: isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)",
        }}>
          {track.title}
        </div>
        <div style={{
          fontSize: 11,
          color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}>
          {track.artist}
        </div>
      </div>

      {/* Like button */}
      <button
        onClick={handleLike}
        style={{
          background: "none",
          border: "none",
          color: isLiked ? "#ff4081" : (isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #888)"),
          cursor: "pointer",
          padding: 4,
          display: "flex",
          alignItems: "center",
          flexShrink: 0,
          transition: "color 0.2s, transform 0.2s",
          transform: isLiked ? "scale(1.1)" : "scale(1)",
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill={isLiked ? "#ff4081" : "none"} stroke={isLiked ? "#ff4081" : "currentColor"} strokeWidth="2">
          <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
        </svg>
      </button>

      {/* Play/Pause button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          haptic("medium");
          onAction(state.is_playing ? "pause" : "play");
        }}
        style={{
          background: isTequila ? "linear-gradient(135deg, #ff6d00, #ffa726)" : accentColor,
          border: "none",
          borderRadius: "50%",
          width: 36,
          height: 36,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          color: isTequila ? "#1a120b" : "#fff",
          flexShrink: 0,
          boxShadow: isTequila ? "0 4px 14px rgba(255, 109, 0, 0.35)" : "none",
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
          color: isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)",
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
