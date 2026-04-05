import { useState, useEffect, useRef } from "preact/hooks";
import type { EqPreset } from "../api";

// --- Haptic Feedback Helper ---
export const haptic = (type: "light" | "medium" | "heavy" | "rigid" | "soft" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

// --- SVG Icons ---
export const IconPlay = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>;
export const IconPause = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>;
export const IconSkipForward = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19" strokeWidth="2"/></svg>;
export const IconSkipBack = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5" strokeWidth="2"/></svg>;
export const IconShuffle = ({ active, color = "#7c4dff" }: { active: boolean; color?: string }) => <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? color : "var(--tg-theme-hint-color, #888)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>;
export const IconRepeat = ({ mode, activeColor = "#7c4dff" }: { mode: string; activeColor?: string }) => {
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
export const IconLyrics = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>;
export const IconHeart = ({ filled }: { filled: boolean }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill={filled ? "#ff4081" : "none"} stroke={filled ? "#ff4081" : "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

// --- Audio Visualizer (animated equalizer bars) ---
export function AudioVisualizer({ isPlaying, accentColor = "#7c4dff" }: { isPlaying: boolean; accentColor?: string }) {
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
            background: `linear-gradient(to top, ${accentColor}, #e040fb)`,
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

// --- Marquee Component for long text (GPU-accelerated, buttery smooth) ---
export function Marquee({ text, style }: { text: string; style?: Record<string, string | number> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);
  const [animDuration, setAnimDuration] = useState(10);

  useEffect(() => {
    if (containerRef.current && textRef.current) {
      const overflow = textRef.current.scrollWidth > containerRef.current.clientWidth;
      setNeedsScroll(overflow);
      if (overflow) {
        const dur = Math.max(6, textRef.current.scrollWidth / 45);
        setAnimDuration(dur);
      }
    }
  }, [text]);

  return (
    <div
      ref={containerRef}
      style={{
        overflow: "hidden",
        whiteSpace: "nowrap",
        position: "relative",
        maskImage: needsScroll ? "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)" : undefined,
        WebkitMaskImage: needsScroll ? "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)" : undefined,
        ...style,
      }}
    >
      <span
        ref={textRef}
        style={{
          display: "inline-block",
          paddingRight: needsScroll ? 60 : 0,
          animation: needsScroll ? `marqueeSmooth ${animDuration}s linear infinite` : "none",
          willChange: needsScroll ? "transform" : undefined,
        }}
      >
        {text}
      </span>
      {needsScroll && (
        <span style={{
          display: "inline-block",
          paddingRight: 60,
          animation: `marqueeSmooth ${animDuration}s linear infinite`,
          willChange: "transform",
        }}>
          {text}
        </span>
      )}
      <style>{`
        @keyframes marqueeSmooth {
          0% { transform: translate3d(0, 0, 0); }
          100% { transform: translate3d(-50%, 0, 0); }
        }
      `}</style>
    </div>
  );
}

export function AudioBadge({ label, active, warm = false }: { label: string; active?: boolean; warm?: boolean }) {
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: warm ? "5px 10px" : "4px 9px",
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: 0.5,
      color: warm ? (active ? "#1a120b" : "#ffd54f") : (active ? "#fff" : "#d1c4e9"),
      background: warm
        ? (active ? "linear-gradient(135deg, #ffb300, #ffd54f)" : "rgba(255, 213, 79, 0.08)")
        : (active ? "linear-gradient(135deg, var(--theme-accent, #7c4dff), #e040fb)" : "rgba(124, 77, 255, 0.12)"),
      border: warm ? "1px solid rgba(255, 213, 79, 0.22)" : "1px solid rgba(179, 136, 255, 0.22)",
      textTransform: "uppercase",
    }}>{label}</span>
  );
}

export const btnStyle: Record<string, string | number> = {
  background: "none",
  border: "none",
  color: "var(--tg-theme-text-color, #eee)",
  cursor: "pointer",
  padding: "8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

export const QUALITY_OPTIONS = ["auto", "128", "192", "320"] as const;

export const EQ_OPTIONS: Array<{ value: EqPreset; label: string; note: string }> = [
  { value: "flat", label: "Flat", note: "neutral studio" },
  { value: "bass", label: "Bass", note: "deep low-end" },
  { value: "vocal", label: "Vocal", note: "clean mids" },
  { value: "club", label: "Club", note: "wide party curve" },
  { value: "bright", label: "Bright", note: "sparkling highs" },
  { value: "night", label: "Night", note: "soft dark top" },
  { value: "soft", label: "Soft", note: "smooth comfort" },
  { value: "techno", label: "Techno", note: "punch + air" },
  { value: "vocal_boost", label: "Vocal Boost", note: "forward voice" },
];

export function formatEqPresetLabel(preset: EqPreset): string {
  return EQ_OPTIONS.find((option) => option.value === preset)?.label ?? preset.replace(/_/g, " ");
}

// --- Waveform Seek Bar ---
export function WaveformSeek({ elapsed, duration, accentColor, onSeek }: {
  elapsed: number;
  duration: number;
  accentColor: string;
  onSeek: (pos: number) => void;
}) {
  const bars = 48;
  const containerRef = useRef<HTMLDivElement>(null);
  // Generate stable pseudo-random bar heights from duration
  const [heights] = useState(() => {
    const h: number[] = [];
    let seed = 42;
    for (let i = 0; i < bars; i++) {
      seed = (seed * 16807 + 13) % 2147483647;
      h.push(0.2 + 0.8 * ((seed % 1000) / 1000));
    }
    return h;
  });

  const progress = duration > 0 ? elapsed / duration : 0;

  const handleClick = (e: MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || duration <= 0) return;
    const x = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(duration, Math.round(x * duration))));
  };

  return (
    <div
      ref={containerRef}
      onClick={handleClick}
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 1.5,
        height: 32,
        cursor: duration > 0 ? "pointer" : "default",
        opacity: duration > 0 ? 1 : 0.4,
        padding: "0 2px",
      }}
    >
      {heights.map((h, i) => {
        const filled = i / bars < progress;
        return (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${h * 100}%`,
              borderRadius: 2,
              background: filled ? accentColor : "rgba(255,255,255,0.15)",
              transition: "background 0.15s ease",
            }}
          />
        );
      })}
    </div>
  );
}

// --- Music Particles ---
const PARTICLE_SYMBOLS = ["♪", "♫", "♬", "✦", "•"];

export function MusicParticles({ isPlaying, accentColor }: { isPlaying: boolean; accentColor: string }) {
  const count = 8;
  if (!isPlaying) return null;
  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden", zIndex: 0 }}>
      <style>{`
        @keyframes particleFloat {
          0% { opacity: 0; transform: translateY(0) scale(0.5); }
          15% { opacity: 0.7; }
          100% { opacity: 0; transform: translateY(-120px) scale(1.2) rotate(30deg); }
        }
      `}</style>
      {Array.from({ length: count }).map((_, i) => (
        <span
          key={i}
          style={{
            position: "absolute",
            left: `${10 + (i * 80 / count) + (i % 3) * 5}%`,
            bottom: `${5 + (i % 4) * 8}%`,
            fontSize: 12 + (i % 3) * 4,
            color: accentColor,
            opacity: 0,
            animation: `particleFloat ${2.5 + (i % 3) * 0.8}s ease-out ${i * 0.4}s infinite`,
            willChange: "transform, opacity",
          }}
        >
          {PARTICLE_SYMBOLS[i % PARTICLE_SYMBOLS.length]}
        </span>
      ))}
    </div>
  );
}
