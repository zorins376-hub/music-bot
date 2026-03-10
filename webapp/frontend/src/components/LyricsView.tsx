import { useState, useEffect, useRef } from "preact/hooks";
import { fetchLyrics } from "../api";
import { SkeletonLyrics } from "./Skeleton";

interface LyricLine {
  time: number;   // seconds
  text: string;
}

interface Props {
  trackId: string;
  elapsed: number;  // current playback position in seconds
  onBack: () => void;
  accentColor?: string;
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

export function LyricsView({ trackId, elapsed, onBack, accentColor = "var(--tg-theme-button-color, #7c4dff)" }: Props) {
  const [lyrics, setLyrics] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lines, setLines] = useState<LyricLine[]>([]);
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

  return (
    <div>
      <button
        onClick={onBack}
        style={{ background: "none", border: "none", color: "var(--tg-theme-link-color, #7c4dff)", cursor: "pointer", marginBottom: 12, fontSize: 14 }}
      >
        ← Назад к плееру
      </button>

      {loading ? (
        <SkeletonLyrics />
      ) : lyrics ? (
        <div style={{
          padding: 12,
          borderRadius: 12,
          background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
          maxHeight: "60vh",
          overflowY: "auto",
        }}>
          {lines.map((line, i) => (
            <div
              key={i}
              ref={i === activeIdx ? activeRef : undefined}
              style={{
                fontSize: i === activeIdx ? 18 : 14,
                fontWeight: i === activeIdx ? 700 : 400,
                color: i === activeIdx
                  ? "#fff"
                  : "var(--tg-theme-text-color, #eee)",
                opacity: hasTimestamps && activeIdx >= 0 && i !== activeIdx ? 0.4 : 1,
                padding: i === activeIdx ? "8px 12px" : "4px 0",
                margin: i === activeIdx ? "4px 0" : 0,
                borderRadius: i === activeIdx ? 8 : 0,
                background: i === activeIdx
                  ? `linear-gradient(90deg, ${accentColor || 'var(--tg-theme-button-color, #7c4dff)'}, #e040fb)`
                  : "transparent",
                transform: i === activeIdx ? "scale(1.02)" : "scale(1)",
                boxShadow: i === activeIdx ? "0 2px 12px rgba(124, 77, 255, 0.4)" : "none",
                transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
                lineHeight: 1.6,
              }}
            >
              {line.text || "\u00A0"}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: 32, color: "var(--tg-theme-hint-color, #aaa)" }}>
          Текст не найден 😔
        </div>
      )}
    </div>
  );
}
