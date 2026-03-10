import { useState, useEffect, useRef } from "preact/hooks";
import { fetchLyrics } from "../api";
import { SkeletonLyrics } from "./Skeleton";
import { IconArrowLeft, IconSad, IconMic } from "./Icons";

interface LyricLine {
  time: number;   // seconds
  text: string;
}

interface Props {
  trackId: string;
  elapsed: number;  // current playback position in seconds
  onBack: () => void;
  accentColor?: string;
  themeId?: string;
}

/**
 * Parse lyrics text. Supports [mm:ss.xx] LRC format and plain text.
 * Returns array of {time, text}. Plain lines get time = -1.
 */
function parseLines(raw: string): LyricLine[] {
  const lines = raw.split("\n");
  const result: LyricLine[] = [];
  const lrcRe = /^\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)/;
  let hasTimestamps = false;

  for (const line of lines) {
    const m = lrcRe.exec(line);
    if (m) {
      hasTimestamps = true;
      const mins = parseInt(m[1], 10);
      const secs = parseInt(m[2], 10);
      const ms = m[3] ? parseInt(m[3].padEnd(3, "0"), 10) : 0;
      result.push({ time: mins * 60 + secs + ms / 1000, text: m[4] });
    } else {
      result.push({ time: -1, text: line });
    }
  }

  // If no timestamps found, assign sequential index-based times so all lines show
  if (!hasTimestamps) {
    return result.map((l, i) => ({ time: -1, text: l.text }));
  }
  return result;
}

export function LyricsView({ trackId, elapsed, onBack, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const isTequila = themeId === "tequila";
  const [lyrics, setLyrics] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lines, setLines] = useState<LyricLine[]>([]);
  const [karaokeMode, setKaraokeMode] = useState(false);
  const activeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchLyrics(trackId)
      .then((text) => {
        setLyrics(text);
        if (text) setLines(parseLines(text));
      })
      .catch(() => setLyrics(null))
      .finally(() => setLoading(false));
  }, [trackId]);

  // Auto-scroll to active line
  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [elapsed]);

  // Find current active line index
  const hasTimestamps = lines.some((l) => l.time >= 0);
  let activeIdx = -1;
  if (hasTimestamps) {
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].time >= 0 && lines[i].time <= elapsed) {
        activeIdx = i;
        break;
      }
    }
  }

  // Calculate progress within active line for karaoke fill effect
  let lineProgress = 0;
  if (hasTimestamps && activeIdx >= 0) {
    const activeTime = lines[activeIdx].time;
    let nextTime = 0;
    for (let i = activeIdx + 1; i < lines.length; i++) {
      if (lines[i].time >= 0) { nextTime = lines[i].time; break; }
    }
    if (nextTime > activeTime) {
      lineProgress = Math.min(1, Math.max(0, (elapsed - activeTime) / (nextTime - activeTime)));
    } else {
      lineProgress = 1;
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <button
          onClick={onBack}
          style={{ background: "none", border: "none", color: isTequila ? "#ffd54f" : "var(--tg-theme-link-color, #7c4dff)", cursor: "pointer", fontSize: 14, display: "flex", alignItems: "center", gap: 4 }}
        >
          <IconArrowLeft size={16} /> Назад к плееру
        </button>
        {hasTimestamps && (
          <button
            onClick={() => setKaraokeMode(k => !k)}
            style={{
              padding: "6px 12px", borderRadius: 16,
              border: karaokeMode
                ? `1px solid ${isTequila ? "#ffd54f" : accentColor}`
                : `1px solid ${isTequila ? "rgba(255,213,79,0.2)" : "rgba(124,77,255,0.2)"}`,
              background: karaokeMode
                ? (isTequila ? "linear-gradient(135deg, rgba(255,109,0,0.3), rgba(255,213,79,0.2))" : `linear-gradient(135deg, ${accentColor}, #e040fb)`)
                : "transparent",
              color: karaokeMode ? "#fff" : (isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #888)"),
              fontSize: 11, fontWeight: 600, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4,
              textTransform: "uppercase", letterSpacing: 0.5,
            }}
          >
            <IconMic size={13} /> Караоке
          </button>
        )}
      </div>

      {loading ? (
        <SkeletonLyrics />
      ) : lyrics ? (
        <div style={{
          padding: karaokeMode ? "24px 16px" : 12,
          borderRadius: 16,
          background: karaokeMode
            ? (isTequila ? "rgba(26, 18, 11, 0.9)" : "rgba(10, 10, 20, 0.95)")
            : (isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)"),
          border: isTequila ? "1px solid rgba(255, 213, 79, 0.12)" : "none",
          backdropFilter: isTequila ? "blur(16px)" : undefined,
          maxHeight: karaokeMode ? "70vh" : "60vh",
          overflowY: "auto",
          transition: "all 0.4s ease",
        }}>
          {lines.map((line, i) => {
            const isActive = i === activeIdx;
            const isPast = hasTimestamps && activeIdx >= 0 && i < activeIdx;

            if (karaokeMode) {
              // Karaoke mode: large text, word-by-word fill
              return (
                <div
                  key={i}
                  ref={isActive ? activeRef : undefined}
                  style={{
                    fontSize: isActive ? 28 : isPast ? 16 : 20,
                    fontWeight: isActive ? 800 : 500,
                    lineHeight: 1.5,
                    padding: isActive ? "12px 0" : "6px 0",
                    opacity: isActive ? 1 : isPast ? 0.25 : 0.5,
                    transform: isActive ? "scale(1.05)" : "scale(1)",
                    transition: "all 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
                    position: "relative",
                    overflow: "hidden",
                    textAlign: "center",
                    color: "transparent",
                    WebkitBackgroundClip: "text",
                    backgroundClip: "text",
                    backgroundImage: isActive
                      ? `linear-gradient(90deg, ${isTequila ? "#ffd54f" : "#fff"} ${lineProgress * 100}%, ${isTequila ? "rgba(200,168,130,0.4)" : "rgba(255,255,255,0.3)"} ${lineProgress * 100}%)`
                      : isPast
                        ? `linear-gradient(90deg, ${isTequila ? "rgba(200,168,130,0.5)" : "rgba(200,200,200,0.5)"} 100%, transparent 100%)`
                        : `linear-gradient(90deg, ${isTequila ? "#fef0e0" : "#eee"} 100%, transparent 100%)`,
                    textShadow: isActive ? (isTequila ? "0 0 30px rgba(255,167,38,0.4)" : `0 0 30px ${accentColor}66`) : "none",
                  }}
                >
                  {line.text || "\u00A0"}
                </div>
              );
            }

            // Normal mode
            return (
              <div
                key={i}
                ref={isActive ? activeRef : undefined}
                style={{
                  fontSize: isActive ? 18 : 14,
                  fontWeight: isActive ? 700 : 400,
                  color: isActive
                    ? "#fff"
                    : (isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
                  opacity: hasTimestamps && activeIdx >= 0 && !isActive ? 0.4 : 1,
                  padding: isActive ? "8px 12px" : "4px 0",
                  margin: isActive ? "4px 0" : 0,
                  borderRadius: isActive ? 8 : 0,
                  background: isActive
                    ? (isTequila ? `linear-gradient(90deg, ${accentColor}, #ffcc66)` : `linear-gradient(90deg, ${accentColor || 'var(--tg-theme-button-color, #7c4dff)'}, #e040fb)`)
                    : "transparent",
                  transform: isActive ? "scale(1.02)" : "scale(1)",
                  boxShadow: isActive ? (isTequila ? "0 2px 16px rgba(255, 109, 0, 0.35)" : "0 2px 12px rgba(124, 77, 255, 0.4)") : "none",
                  transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
                  lineHeight: 1.6,
                }}
              >
                {line.text || "\u00A0"}
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: 32, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>
          Текст не найден <IconSad size={16} />
        </div>
      )}
    </div>
  );
}
