import { useState, useRef, useCallback, useEffect } from "preact/hooks";
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
  const [dragY, setDragY] = useState(0);
  const dragStartY = useRef(0);
  const dragStartX = useRef(0);
  const longPressTimer = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // Calculate drop target based on Y position
  const findDropTarget = useCallback((touchY: number) => {
    let newOverIndex = dragIndex;
    itemRefs.current.forEach((el, idx) => {
      if (idx === dragIndex) return;
      const rect = el.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      if (touchY > midY - 20 && touchY < midY + rect.height) {
        newOverIndex = idx;
      }
    });
    return newOverIndex;
  }, [dragIndex]);

  const handleTouchStart = (e: TouchEvent, idx: number) => {
    dragStartY.current = e.touches[0].clientY;
    dragStartX.current = e.touches[0].clientX;
    // Long press for drag mode
    longPressTimer.current = window.setTimeout(() => {
      haptic("heavy");
      setDragIndex(idx);
      setDragY(e.touches[0].clientY);
      setSwipedIndex(null);
    }, 400);
  };

  const handleTouchMove = useCallback((e: TouchEvent, idx: number) => {
    const touchY = e.touches[0].clientY;
    const touchX = e.touches[0].clientX;
    const movedY = Math.abs(touchY - dragStartY.current);
    const movedX = touchX - dragStartX.current;

    // Cancel long press if moved too much before timer fires
    if (longPressTimer.current && (movedY > 15 || Math.abs(movedX) > 15)) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }

    // Swipe left to reveal delete (only if not dragging)
    if (dragIndex === null && movedX < -50 && movedY < 30) {
      setSwipedIndex(idx);
    } else if (movedX > 20 && swipedIndex === idx) {
      setSwipedIndex(null);
    }
  }, [dragIndex, swipedIndex]);

  // Global touch move listener for drag mode
  useEffect(() => {
    if (dragIndex === null) return;

    const onMove = (e: TouchEvent) => {
      e.preventDefault();
      const touchY = e.touches[0].clientY;
      setDragY(touchY);
      
      const newOver = findDropTarget(touchY);
      if (newOver !== null && newOver !== overIndex) {
        setOverIndex(newOver);
        haptic("light");
      }
    };

    const onEnd = () => {
      if (dragIndex !== null && overIndex !== null && dragIndex !== overIndex && onReorder) {
        const newTracks = [...tracks];
        const [removed] = newTracks.splice(dragIndex, 1);
        newTracks.splice(overIndex, 0, removed);
        haptic("medium");
        onReorder(newTracks);
      }
      setDragIndex(null);
      setOverIndex(null);
      setDragY(0);
    };

    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onEnd);
    document.addEventListener("touchcancel", onEnd);

    return () => {
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.removeEventListener("touchcancel", onEnd);
    };
  }, [dragIndex, overIndex, tracks, onReorder, findDropTarget]);

  const handleTouchEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    // Actual reorder is handled by global listener when dragIndex is set
    if (dragIndex === null) {
      // Not in drag mode, do nothing special
    }
  };

  const handleRemove = async (e: Event, track: Track, idx: number) => {
    e.preventDefault();
    e.stopPropagation();
    haptic("medium");
    
    // Close swipe immediately for visual feedback
    setSwipedIndex(null);
    
    if (onRemove) {
      onRemove(track);
    } else {
      // Fallback: remove via API directly
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
      style={{ 
        marginTop: 16, 
        overflowY: dragIndex !== null ? "hidden" : "auto", 
        maxHeight: "40vh", 
        WebkitOverflowScrolling: "touch",
        position: "relative",
      }}
      onTouchEnd={handleTouchEnd}
    >
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span>Очередь ({tracks.length})</span>
        <span style={{ fontSize: 10, color: "var(--tg-theme-hint-color, #888)" }}>
          {dragIndex !== null ? "🎯 отпусти для перемещения" : "☰ зажми · ← свайп удалить"}
        </span>
      </div>
      {tracks.map((t, i) => (
        <div
          key={t.video_id}
          ref={(el) => { if (el) itemRefs.current.set(i, el); else itemRefs.current.delete(i); }}
          data-track-idx={i}
          style={{ position: "relative", overflow: "hidden", marginBottom: 6 }}
        >
          {/* Drop indicator line */}
          {dragIndex !== null && overIndex === i && dragIndex !== i && (
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: dragIndex < i ? "auto" : 0,
                bottom: dragIndex < i ? 0 : "auto",
                height: 3,
                background: accentColor,
                borderRadius: 2,
                zIndex: 10,
              }}
            />
          )}
          {/* Delete button (revealed on swipe) */}
          <div
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleRemove(e as unknown as Event, t, i); }}
            onTouchEnd={(e) => { e.preventDefault(); e.stopPropagation(); handleRemove(e as unknown as Event, t, i); }}
            style={{
              position: "absolute",
              right: 0,
              top: 0,
              bottom: 0,
              width: 70,
              background: "#ff4444",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "0 10px 10px 0",
              cursor: "pointer",
              opacity: swipedIndex === i ? 1 : 0,
              pointerEvents: swipedIndex === i ? "auto" : "none",
              transition: "opacity 0.2s",
              zIndex: 50,
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
                ? "rgba(124, 77, 255, 0.5)"
                : overIndex === i && dragIndex !== null
                ? "rgba(124, 77, 255, 0.2)"
                : "rgba(255,255,255,0.08)",
              transform: `translateX(${swipedIndex === i ? -60 : 0}px) scale(${dragIndex === i ? 1.05 : 1})`,
              transition: dragIndex === i ? "none" : "transform 0.2s, background 0.15s",
              boxShadow: dragIndex === i ? "0 8px 24px rgba(0,0,0,0.4)" : "none",
              touchAction: dragIndex !== null ? "none" : "pan-y",
              userSelect: "none",
              opacity: dragIndex === i ? 0.9 : 1,
              zIndex: dragIndex === i ? 100 : 1,
            }}
          >
          {/* Drag handle */}
          {onReorder && (
            <div style={{ 
              marginRight: 10, 
              color: dragIndex === i ? accentColor : "var(--tg-theme-hint-color, #666)", 
              fontSize: 18,
              padding: "4px",
            }}>
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
