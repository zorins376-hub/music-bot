import { useState, useRef, useCallback } from "preact/hooks";
import type { Track } from "../api";
import { sendAction } from "../api";

interface Props {
  tracks: Track[];
  currentIndex: number;
  onPlay: (track: Track) => void;
  onReorder?: (newOrder: Track[]) => void;
  onRemove?: (track: Track) => void;
  accentColor?: string;
}

// Haptic helper
const haptic = (type: "light" | "medium" | "heavy" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

export function TrackList({ tracks, currentIndex, onPlay, onReorder, onRemove, accentColor = "var(--tg-theme-button-color, #7c4dff)" }: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [swipedIndex, setSwipedIndex] = useState<number | null>(null);
  const dragStartY = useRef(0);
  const dragStartX = useRef(0);
  const longPressTimer = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleTouchStart = (e: TouchEvent, idx: number) => {
    dragStartY.current = e.touches[0].clientY;
    dragStartX.current = e.touches[0].clientX;
    // Long press for drag mode
    longPressTimer.current = window.setTimeout(() => {
      haptic("heavy");
      setDragIndex(idx);
      setSwipedIndex(null);
    }, 500);
  };

  const handleTouchMove = useCallback((e: TouchEvent, idx: number) => {
    const touchY = e.touches[0].clientY;
    const touchX = e.touches[0].clientX;
    const movedY = Math.abs(touchY - dragStartY.current);
    const movedX = touchX - dragStartX.current;

    // Cancel long press if moved
    if (longPressTimer.current && movedY > 10) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }

    // Swipe left to reveal delete (only if not dragging)
    if (dragIndex === null && movedX < -50 && movedY < 30) {
      setSwipedIndex(idx);
    } else if (movedX > 20 && swipedIndex === idx) {
      setSwipedIndex(null);
    }

    // Drag mode - find target position
    if (dragIndex !== null) {
      e.preventDefault();
      const elements = document.elementsFromPoint(touchX, touchY);
      for (const el of elements) {
        const dataIdx = (el as HTMLElement).dataset?.trackIdx;
        if (dataIdx !== undefined) {
          const newOver = parseInt(dataIdx);
          if (newOver !== overIndex) {
            setOverIndex(newOver);
            haptic("light");
          }
          break;
        }
      }
    }
  }, [dragIndex, overIndex, swipedIndex]);

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

  const handleRemove = async (e: Event, track: Track, idx: number) => {
    e.stopPropagation();
    haptic("medium");
    setSwipedIndex(null);
    
    if (onRemove) {
      onRemove(track);
    } else {
      // Default: remove via API
      try {
        await sendAction("remove", track.video_id);
        // Trigger reorder without the removed track
        if (onReorder) {
          const newTracks = tracks.filter((_, i) => i !== idx);
          onReorder(newTracks);
        }
      } catch (err) {
        console.error("Remove track error:", err);
      }
    }
  };

  return (
    <div
      ref={containerRef}
      style={{ marginTop: 16, overflowY: "auto", maxHeight: "40vh", WebkitOverflowScrolling: "touch" }}
      onTouchEnd={handleTouchEnd}
    >
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <span>Очередь ({tracks.length})</span>
        <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>← свайп для удаления</span>
      </div>
      {tracks.map((t, i) => (
        <div
          key={t.video_id}
          data-track-idx={i}
          style={{ position: "relative", overflow: "hidden", marginBottom: 6 }}
        >
          {/* Delete button (revealed on swipe) */}
          <div
            onClick={(e) => handleRemove(e as unknown as Event, t, i)}
            style={{
              position: "absolute",
              right: 0,
              top: 0,
              bottom: 0,
              width: 60,
              background: "#ff4444",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "0 10px 10px 0",
              cursor: "pointer",
              opacity: swipedIndex === i ? 1 : 0,
              transition: "opacity 0.2s",
            }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </div>
          {/* Track item */}
          <div
            onTouchStart={(e) => handleTouchStart(e as unknown as TouchEvent, i)}
            onTouchMove={(e) => handleTouchMove(e as unknown as TouchEvent, i)}
            onClick={() => dragIndex === null && swipedIndex !== i && onPlay(t)}
            style={{
              display: "flex",
              alignItems: "center",
              padding: "10px 12px",
              borderRadius: 10,
              cursor: "pointer",
              background: i === currentIndex
                ? accentColor
                : dragIndex === i
                ? "rgba(124, 77, 255, 0.3)"
                : overIndex === i && dragIndex !== null
                ? "rgba(124, 77, 255, 0.15)"
                : "rgba(255,255,255,0.08)",
              transform: `translateX(${swipedIndex === i ? -60 : 0}px) scale(${dragIndex === i ? 1.02 : 1})`,
              transition: "transform 0.2s, background 0.15s",
              boxShadow: dragIndex === i ? "0 4px 12px rgba(0,0,0,0.3)" : "none",
              touchAction: dragIndex !== null ? "none" : "pan-y",
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
