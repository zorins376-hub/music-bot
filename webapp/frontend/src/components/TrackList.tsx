import { useState, useRef, useCallback, useEffect } from "preact/hooks";
import type { Track } from "../api";
import { sendAction } from "../api";
import { IconDragHandle, IconMusic, IconTarget, IconSwipeLeft, IconTrash } from "./Icons";

interface Props {
  tracks: Track[];
  currentIndex: number;
  onPlay: (track: Track) => void;
  onReorder?: (fromIndex: number, toIndex: number) => void;
  onRemove?: (track: Track) => void;
  accentColor?: string;
  accentColorAlpha?: string;
  themeId?: string;
}

// Haptic helper
const haptic = (type: "light" | "medium" | "heavy" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

export function TrackList({ tracks, currentIndex, onPlay, onReorder, onRemove, accentColor = "var(--tg-theme-button-color, #7c4dff)", accentColorAlpha = "rgba(124, 77, 255, 0.4)", themeId = "blackroom" }: Props) {
  const isTequila = themeId === "tequila";
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [swipedIndex, setSwipedIndex] = useState<number | null>(null);
  const [dragY, setDragY] = useState(0);
  const dragStartY = useRef(0);
  const dragStartX = useRef(0);
  const longPressTimer = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const lastAutoScrollAt = useRef(0);

  // Calculate drop target based on Y position
  const findDropTarget = useCallback((touchY: number) => {
    let newOverIndex = dragIndex;
    const items = [...itemRefs.current.entries()].sort((a, b) => a[0] - b[0]);
    if (!items.length) return newOverIndex;

    const firstRect = items[0][1].getBoundingClientRect();
    const lastRect = items[items.length - 1][1].getBoundingClientRect();

    if (touchY <= firstRect.top + firstRect.height / 2) {
      return 0;
    }
    if (touchY >= lastRect.top + lastRect.height / 2) {
      return items[items.length - 1][0];
    }

    items.forEach(([idx, el]) => {
      if (idx === dragIndex) return;
      const rect = el.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      if (touchY >= rect.top && touchY <= rect.bottom) {
        newOverIndex = touchY < midY ? idx : Math.min(idx + 1, items[items.length - 1][0]);
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
      setOverIndex(idx);
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

      const container = containerRef.current;
      if (container) {
        const rect = container.getBoundingClientRect();
        const edgeThreshold = 56;
        const now = Date.now();
        if (now - lastAutoScrollAt.current > 16) {
          if (touchY < rect.top + edgeThreshold) {
            container.scrollTop -= 18;
            lastAutoScrollAt.current = now;
          } else if (touchY > rect.bottom - edgeThreshold) {
            container.scrollTop += 18;
            lastAutoScrollAt.current = now;
          }
        }
      }
      
      const newOver = findDropTarget(touchY);
      if (newOver !== null && newOver !== overIndex) {
        setOverIndex(newOver);
        haptic("light");
      }
    };

    const onEnd = () => {
      if (dragIndex !== null && overIndex !== null && dragIndex !== overIndex && onReorder) {
        haptic("medium");
        onReorder(dragIndex, overIndex);
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
  }, [dragIndex, overIndex, onReorder, findDropTarget]);

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
      } catch (err) {
        console.error("Remove track error:", err);
      }
    }
  };

  return (
    <div style={{ marginTop: 16 }}>
      {/* Sticky header outside scroll container */}
      <div style={{ 
        fontSize: 14, 
        fontWeight: 600, 
        marginBottom: 8, 
        display: "flex", 
        alignItems: "center", 
        justifyContent: "space-between",
        padding: isTequila ? "10px 12px" : "4px 0",
        background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-bg-color, #1a1a2e)",
        border: isTequila ? "1px solid rgba(255, 213, 79, 0.12)" : "none",
        borderRadius: isTequila ? 16 : 0,
        backdropFilter: isTequila ? "blur(14px)" : undefined,
        color: isTequila ? "#fef0e0" : undefined,
      }}>
        <span>Очередь ({tracks.length})</span>
        <span style={{ fontSize: 10, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #888)" }}>
          {dragIndex !== null ? (
            <><IconTarget size={12} /> отпусти для перемещения</>
          ) : (
            <><IconDragHandle size={12} /> зажми · <IconSwipeLeft size={12} /> удалить</>
          )}
        </span>
      </div>
      {/* Scrollable track list */}
      <div
        ref={containerRef}
        style={{ 
          overflowY: "auto", 
          maxHeight: "calc(100vh - 140px)", 
          WebkitOverflowScrolling: "touch",
          position: "relative",
        }}
        onTouchEnd={handleTouchEnd}
      >
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
              background: isTequila ? "linear-gradient(135deg, #b23a1e, #ff6d00)" : "#ff4444",
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
            <IconTrash size={24} color="#fff" />
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
                ? (isTequila ? `linear-gradient(135deg, ${accentColor}, #ffcc66)` : accentColor)
                : dragIndex === i
                ? accentColorAlpha
                : overIndex === i && dragIndex !== null
                ? (isTequila ? "rgba(255, 213, 79, 0.14)" : "rgba(124, 77, 255, 0.2)")
                : (isTequila ? "rgba(40, 25, 15, 0.45)" : "rgba(255,255,255,0.08)"),
              transform: `translateX(${swipedIndex === i ? -60 : 0}px) translateY(${dragIndex === i ? dragY - dragStartY.current : 0}px) scale(${dragIndex === i ? 1.05 : 1})`,
              transition: dragIndex === i ? "none" : "transform 0.2s, background 0.15s",
              boxShadow: dragIndex === i ? "0 8px 24px rgba(0,0,0,0.4)" : (isTequila ? "0 4px 14px rgba(0,0,0,0.18)" : "none"),
              border: isTequila ? `1px solid ${i === currentIndex ? "rgba(255, 245, 210, 0.18)" : "rgba(255, 213, 79, 0.08)"}` : "none",
              backdropFilter: isTequila ? "blur(10px)" : undefined,
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
              padding: "4px",
              display: "flex",
              alignItems: "center",
            }}>
              <IconDragHandle size={18} color={dragIndex === i ? accentColor : "var(--tg-theme-hint-color, #666)"} />
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
          <div style={{
            width: 42,
            height: 42,
            borderRadius: 10,
            overflow: "hidden",
            flexShrink: 0,
            marginRight: 10,
            background: isTequila ? "rgba(255, 213, 79, 0.08)" : "rgba(255,255,255,0.08)",
            border: isTequila ? "1px solid rgba(255, 213, 79, 0.14)" : "1px solid rgba(255,255,255,0.06)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            {t.cover_url ? (
              <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <IconMusic size={20} color={isTequila ? "#c8a882" : "rgba(255,255,255,0.55)"} />
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: i === currentIndex ? 600 : 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: isTequila && i !== currentIndex ? "#fef0e0" : undefined }}>
              {t.title}
            </div>
            <div style={{ fontSize: 12, color: i === currentIndex ? "rgba(255,255,255,0.8)" : (isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)") }}>
              {t.artist}
            </div>
          </div>
          <div style={{ fontSize: 12, color: i === currentIndex ? "rgba(255,255,255,0.8)" : (isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)"), marginLeft: 8 }}>
            {t.duration_fmt}
          </div>
          </div>
        </div>
      ))}
      </div>
      <style>{`
        @keyframes eq {
          from { height: 4px; }
          to { height: 14px; }
        }
      `}</style>
    </div>
  );
}
