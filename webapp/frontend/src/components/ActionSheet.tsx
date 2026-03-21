import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import type { JSX } from "preact";
import type { Track } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconPlaySmall, IconPlus, IconMusic, IconMusicNote, IconHeart,
  IconRocket, IconSimilar, IconShare, IconClose,
} from "./Icons";

export interface ActionSheetAction {
  id: string;
  label: string;
  icon: JSX.Element;
  color?: string;
  danger?: boolean;
}

interface Props {
  track: Track | null;
  visible: boolean;
  onClose: () => void;
  onAction: (actionId: string, track: Track) => void;
  actions?: ActionSheetAction[];
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function ActionSheet({
  track,
  visible,
  onClose,
  onAction,
  actions,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);
  const [animState, setAnimState] = useState<"enter" | "exit" | "idle">("idle");
  const sheetRef = useRef<HTMLDivElement>(null);

  // Inject animation styles
  useEffect(() => {
    if (document.getElementById("action-sheet-anims")) return;
    const s = document.createElement("style");
    s.id = "action-sheet-anims";
    s.textContent = `
      @keyframes as-slideUp { 0% { transform:translateY(100%); } 100% { transform:translateY(0); } }
      @keyframes as-slideDown { 0% { transform:translateY(0); } 100% { transform:translateY(100%); } }
      @keyframes as-fadeIn { 0% { opacity:0; } 100% { opacity:1; } }
      @keyframes as-fadeOut { 0% { opacity:1; } 100% { opacity:0; } }
    `;
    document.head.appendChild(s);
  }, []);

  useEffect(() => {
    if (visible) {
      setAnimState("enter");
      return;
    }

    // When parent forces visible=false, always transition out so the full-screen
    // backdrop cannot remain mounted and block taps.
    setAnimState((prev) => (prev === "idle" ? "idle" : "exit"));
  }, [visible]);

  useEffect(() => {
    if (animState !== "exit") return;
    const t = setTimeout(() => setAnimState("idle"), 200);
    return () => clearTimeout(t);
  }, [animState]);

  const handleClose = useCallback(() => {
    haptic("light");
    setAnimState("exit");
    setTimeout(() => {
      setAnimState("idle");
      onClose();
    }, 200);
  }, [onClose]);

  const handleAction = useCallback((actionId: string) => {
    if (!track) return;
    haptic("medium");
    setAnimState("exit");
    setTimeout(() => {
      setAnimState("idle");
      onAction(actionId, track);
      onClose();
    }, 150);
  }, [track, onAction, onClose]);

  if (!visible && animState === "idle") return null;
  if (!track) return null;

  const defaultActions: ActionSheetAction[] = actions || [
    { id: "play", label: "Play", icon: <IconPlaySmall size={18} color={tc.highlight} /> },
    { id: "queue", label: "Add to Queue", icon: <IconPlus size={18} color={tc.highlight} /> },
    { id: "playlist", label: "Add to Playlist", icon: <IconMusic size={18} color={tc.highlight} /> },
    { id: "similar", label: "Similar Tracks", icon: <IconSimilar size={18} color={tc.highlight} /> },
    { id: "radio", label: "Start Radio", icon: <IconRocket size={18} color={tc.highlight} /> },
    { id: "share", label: "Share", icon: <IconShare size={18} color={tc.highlight} /> },
  ];

  return (
    <div
      style={{
        position: "fixed",
        top: 0, left: 0, right: 0, bottom: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.5)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        animation: animState === "enter" ? "as-fadeIn 0.2s ease-out" : animState === "exit" ? "as-fadeOut 0.2s ease-out forwards" : undefined,
      }}
      onClick={handleClose}
    >
      <div
        ref={sheetRef}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "absolute",
          bottom: 0, left: 0, right: 0,
          background: theme.bgColor,
          borderRadius: "24px 24px 0 0",
          padding: "12px 16px 32px",
          boxShadow: "0 -10px 40px rgba(0,0,0,0.3)",
          animation: animState === "enter" ? "as-slideUp 0.25s ease-out" : animState === "exit" ? "as-slideDown 0.2s ease-out forwards" : undefined,
        }}
      >
        {/* Drag handle */}
        <div style={{
          width: 36, height: 4, borderRadius: 2,
          background: "rgba(255,255,255,0.15)",
          margin: "0 auto 16px",
        }} />

        {/* Track info header */}
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "8px 4px 16px",
          borderBottom: `1px solid rgba(255,255,255,0.06)`,
          marginBottom: 8,
        }}>
          <div style={{
            width: 52, height: 52, borderRadius: 12, overflow: "hidden", flexShrink: 0,
            background: tc.coverPlaceholderBg,
          }}>
            {track.cover_url ? (
              <img src={track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <IconMusicNote size={22} color={tc.hintColor} />
              </div>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: 15, fontWeight: 700, color: tc.textColor,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {track.title}
            </div>
            <div style={{ fontSize: 13, color: tc.hintColor, marginTop: 2 }}>
              {track.artist}
            </div>
          </div>
          <button
            onClick={handleClose}
            style={{
              background: "rgba(255,255,255,0.06)", border: "none",
              borderRadius: 10, width: 32, height: 32,
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", flexShrink: 0,
            }}
          >
            <IconClose size={16} color={tc.hintColor} />
          </button>
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {defaultActions.map((action) => (
            <button
              key={action.id}
              onClick={() => handleAction(action.id)}
              style={{
                display: "flex", alignItems: "center", gap: 14,
                padding: "14px 12px",
                borderRadius: 14,
                border: "none",
                background: "transparent",
                color: action.danger ? "#f44336" : tc.textColor,
                fontSize: 15, fontWeight: 500,
                cursor: "pointer",
                transition: "background 0.15s ease",
                textAlign: "left",
                width: "100%",
              }}
            >
              <div style={{
                width: 36, height: 36, borderRadius: 10,
                background: action.danger ? "rgba(244,67,54,0.1)" : tc.coverPlaceholderBg,
                display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                {action.icon}
              </div>
              {action.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Hook to add long-press detection for action sheet.
 * Returns: { onTouchStart, onTouchEnd, onContextMenu }
 */
export function useLongPress(callback: () => void, delay = 500) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggeredRef = useRef(false);

  const start = useCallback((e: TouchEvent | MouseEvent) => {
    triggeredRef.current = false;
    timerRef.current = setTimeout(() => {
      triggeredRef.current = true;
      haptic("heavy");
      callback();
    }, delay);
  }, [callback, delay]);

  const end = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const prevent = useCallback((e: Event) => {
    e.preventDefault();
  }, []);

  return {
    onTouchStart: start,
    onTouchEnd: end,
    onTouchMove: end,
    onContextMenu: prevent,
    wasLongPress: () => triggeredRef.current,
  };
}
