import { useState, useRef } from "preact/hooks";
import type { Track } from "../api";

interface Props {
  tracks: Track[];
  currentIndex: number;
  onPlay: (track: Track) => void;
  onReorder?: (newOrder: Track[]) => void;
  accentColor?: string;
}

// Haptic helper
const haptic = (type: "light" | "medium" | "heavy" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

export function TrackList({ tracks, currentIndex, onPlay, onReorder, accentColor = "var(--tg-theme-button-color, #7c4dff)" }: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const dragStartY = useRef(0);
  const longPressTimer = useRef<number | null>(null);

  const handleTouchStart = (e: TouchEvent, idx: number) => {
    dragStartY.current = e.touches[0].clientY;
    longPressTimer.current = window.setTimeout(() => {
      haptic("heavy");
      setDragIndex(idx);
    }, 400);
  };

  const handleTouchMove = (e: TouchEvent) => {
    if (longPressTimer.current) {
      const moved = Math.abs(e.touches[0].clientY - dragStartY.current);
      if (moved > 10) {
        clearTimeout(longPressTimer.current);
        longPressTimer.current = null;
      }
    }
    if (dragIndex !== null) {
      const touch = e.touches[0];
      const elements = document.elementsFromPoint(touch.clientX, touch.clientY);
      for (const el of elements) {
        const idx = (el as HTMLElement).dataset?.trackIdx;
        if (idx !== undefined) {
          setOverIndex(parseInt(idx));
          break;
        }
      }
    }
  };

  const handleTouchEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    if (dragIndex !== null && overIndex !== null && dragIndex !== overIndex && onReorder) {
      const newTracks = [...tracks];
      const [removed] = newTracks.splice(dragIndex, 1);
      newTracks.splice(overIndex, 0, removed);
      haptic("medium");
      onReorder(newTracks);
    }
    setDragIndex(null);
    setOverIndex(null);
  };

  return (
    <div
      style={{ marginTop: 16 }}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <span>Очередь ({tracks.length})</span>
        {onReorder && <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>зажми для перетаскивания</span>}
      </div>
      {tracks.map((t, i) => (
        <div
          key={t.video_id}
          data-track-idx={i}
          onTouchStart={(e) => handleTouchStart(e as unknown as TouchEvent, i)}
          onClick={() => dragIndex === null && onPlay(t)}
          style={{
            display: "flex",
            alignItems: "center",
            padding: "10px 12px",
            borderRadius: 10,
            marginBottom: 6,
            cursor: "pointer",
            background: i === currentIndex
              ? accentColor
              : dragIndex === i
              ? "rgba(124, 77, 255, 0.3)"
              : overIndex === i && dragIndex !== null
              ? "rgba(124, 77, 255, 0.15)"
              : "rgba(255,255,255,0.08)",
            transform: dragIndex === i ? "scale(1.02)" : "scale(1)",
            transition: "transform 0.15s, background 0.15s",
            boxShadow: dragIndex === i ? "0 4px 12px rgba(0,0,0,0.3)" : "none",
            touchAction: "none",
            userSelect: "none",
          }}
        >
          {/* Drag handle */}
          {onReorder && (
            <div style={{ marginRight: 10, color: "var(--tg-theme-hint-color, #666)", fontSize: 16 }}>
              ☰
            </div>
          )}
          {/* Playing indicator */}
          {i === currentIndex && (
            <div style={{ marginRight: 8, display: "flex", alignItems: "flex-end", gap: 2, height: 16 }}>
              <span style={{ width: 3, height: 12, background: "#fff", borderRadius: 1, animation: "eq 0.4s ease infinite alternate" }} />
              <span style={{ width: 3, height: 8, background: "#fff", borderRadius: 1, animation: "eq 0.4s ease 0.1s infinite alternate" }} />
              <span style={{ width: 3, height: 14, background: "#fff", borderRadius: 1, animation: "eq 0.4s ease 0.2s infinite alternate" }} />
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: i === currentIndex ? 600 : 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {t.title}
            </div>
            <div style={{ fontSize: 12, color: i === currentIndex ? "rgba(255,255,255,0.8)" : "var(--tg-theme-hint-color, #aaa)" }}>
              {t.artist}
            </div>
          </div>
          <div style={{ fontSize: 12, color: i === currentIndex ? "rgba(255,255,255,0.8)" : "var(--tg-theme-hint-color, #aaa)", marginLeft: 8 }}>
            {t.duration_fmt}
          </div>
        </div>
      ))}
      <style>{`
        @keyframes eq {
          from { height: 4px; }
          to { height: 14px; }
        }
      `}</style>
    </div>
  );
}
