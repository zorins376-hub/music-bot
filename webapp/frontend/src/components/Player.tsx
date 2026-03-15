import { useState, useEffect, useRef } from "preact/hooks";
import type { EqPreset, PlayerState } from "../api";
import { toggleFavorite, checkFavorite, sendFeedback, ingestEvent, fetchSimilar, generateAiPlaylist, fetchTrending, searchTracks, type Track } from "../api";
import { ShareCard } from "./ShareCard";
import { IconEqualizer, IconMusic, IconMusicNote, IconSpectrum, IconSpatial, IconSpeed, IconBassBoost, IconParty, IconMood, IconMic, IconHiRes, IconMoodChill, IconMoodEnergy, IconMoodFocus, IconMoodRomance, IconMoodMelancholy, IconMoodParty, IconPlus, IconShare, IconImage, IconWave, IconSimilar, IconTrending, IconMoon, IconSpinner, IconFire } from "./Icons";

interface Props {
  state: PlayerState;
  onAction: (action: string, trackId?: string, seekPos?: number) => void;
  onShowLyrics: (trackId: string) => void;
  accentColor?: string;
  accentColorAlpha?: string;
  onSleepTimer?: (minutes: number | null) => void;
  sleepTimerRemaining?: number | null;
  audioDuration?: number;
  onWave?: () => void;
  isWaveLoading?: boolean;
  elapsed?: number;
  buffering?: boolean;
  themeId?: string;
  isPremium?: boolean;
  isAdmin?: boolean;
  canUseAudioControls?: boolean;
  quality?: string;
  eqPreset?: EqPreset;
  onQualityChange?: (quality: string) => void;
  onEqPresetChange?: (preset: EqPreset) => void;
  bassBoost?: boolean;
  onBassBoost?: (on: boolean) => void;
  partyMode?: boolean;
  onPartyMode?: (on: boolean) => void;
  playbackSpeed?: number;
  onSpeedChange?: (speed: number) => void;
  panValue?: number;
  onPanChange?: (value: number) => void;
  showSpectrum?: boolean;
  onToggleSpectrum?: () => void;
  spectrumStyle?: "bars" | "wave" | "circle";
  onSpectrumStyleChange?: (style: "bars" | "wave" | "circle") => void;
  moodFilter?: string | null;
  onMoodChange?: (mood: string | null) => void;
  bypassProcessing?: boolean;
  onBypassToggle?: (on: boolean) => void;
  tapeWarmth?: boolean;
  onTapeWarmth?: (on: boolean) => void;
  airBand?: boolean;
  onAirBand?: (on: boolean) => void;
  stereoWiden?: boolean;
  onStereoWiden?: (on: boolean) => void;
  softClip?: boolean;
  onSoftClip?: (on: boolean) => void;
  crossfadeDuration?: number;
  onCrossfadeDuration?: (sec: number) => void;
  vinylSpin?: boolean;
  onVinylSpin?: (on: boolean) => void;
  onAddToPlaylist?: () => void;
  onPlayTrack?: (track: Track) => void;
  onPlayAll?: (tracks: Track[]) => void;
}

const QUALITY_OPTIONS = ["auto", "128", "192", "320"] as const;
const EQ_OPTIONS: Array<{ value: EqPreset; label: string; note: string }> = [
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

function formatEqPresetLabel(preset: EqPreset): string {
  return EQ_OPTIONS.find((option) => option.value === preset)?.label ?? preset.replace(/_/g, " ");
}

function AudioBadge({ label, active, warm = false }: { label: string; active?: boolean; warm?: boolean }) {
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
        : (active ? "linear-gradient(135deg, #7c4dff, #e040fb)" : "rgba(124, 77, 255, 0.12)"),
      border: warm ? "1px solid rgba(255, 213, 79, 0.22)" : "1px solid rgba(179, 136, 255, 0.22)",
      textTransform: "uppercase",
    }}>{label}</span>
  );
}

// --- Haptic Feedback Helper ---
const haptic = (type: "light" | "medium" | "heavy" | "rigid" | "soft" = "light") => {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(type);
  } catch {}
};

const btnStyle: Record<string, string | number> = {
  background: "none",
  border: "none",
  color: "var(--tg-theme-text-color, #eee)",
  cursor: "pointer",
  padding: "8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

// --- SVG Icons ---
const IconPlay = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>;
const IconPause = () => <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>;
const IconSkipForward = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19" strokeWidth="2"/></svg>;
const IconSkipBack = () => <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5" strokeWidth="2"/></svg>;
const IconShuffle = ({ active, color = "#7c4dff" }: { active: boolean; color?: string }) => <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={active ? color : "var(--tg-theme-hint-color, #888)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>;
const IconRepeat = ({ mode, activeColor = "#7c4dff" }: { mode: string; activeColor?: string }) => {
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
const IconLyrics = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>;
const IconHeart = ({ filled }: { filled: boolean }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill={filled ? "#ff4081" : "none"} stroke={filled ? "#ff4081" : "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

// --- Audio Visualizer (animated equalizer bars) ---
function AudioVisualizer({ isPlaying, accentColor = "#7c4dff" }: { isPlaying: boolean; accentColor?: string }) {
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
function Marquee({ text, style }: { text: string; style?: Record<string, string | number> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);
  const [animDuration, setAnimDuration] = useState(10);

  useEffect(() => {
    if (containerRef.current && textRef.current) {
      const overflow = textRef.current.scrollWidth > containerRef.current.clientWidth;
      setNeedsScroll(overflow);
      if (overflow) {
        // Speed: ~45px/s — consistent regardless of text length
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

export function Player({ state, onAction, onShowLyrics, accentColor = "rgb(124, 77, 255)", accentColorAlpha = "rgba(124, 77, 255, 0.4)", onSleepTimer, sleepTimerRemaining, audioDuration = 0, onWave, isWaveLoading = false, elapsed: externalElapsed = 0, buffering = false, themeId = "blackroom", isPremium = false, isAdmin = false, canUseAudioControls = false, quality = "192", eqPreset = "flat", onQualityChange, onEqPresetChange, bassBoost = false, onBassBoost, partyMode = false, onPartyMode, playbackSpeed = 1, onSpeedChange, panValue = 0, onPanChange, showSpectrum = false, onToggleSpectrum, spectrumStyle = "bars", onSpectrumStyleChange, moodFilter = null, onMoodChange, bypassProcessing = false, onBypassToggle, tapeWarmth = false, onTapeWarmth, airBand = false, onAirBand, stereoWiden = false, onStereoWiden, softClip = false, onSoftClip, crossfadeDuration = 0, onCrossfadeDuration, vinylSpin = true, onVinylSpin, onAddToPlaylist, onPlayTrack, onPlayAll }: Props) {
  const isTequila = themeId === "tequila";
  const track = state.current_track;
  const duration = audioDuration || track?.duration || 0;
  const [seekValue, setSeekValue] = useState<number | null>(null);
  const elapsed = seekValue !== null ? seekValue : externalElapsed;
  const [seeking, setSeeking] = useState(false);
  const [isLiked, setIsLiked] = useState(false);
  const [showSleepMenu, setShowSleepMenu] = useState(false);
  const [showShareCard, setShowShareCard] = useState(false);
  const [similarTracks, setSimilarTracks] = useState<Track[]>([]);
  const [showSimilar, setShowSimilar] = useState(false);
  const [isSimilarLoading, setIsSimilarLoading] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiPlaylistTracks, setAiPlaylistTracks] = useState<Track[]>([]);
  const [showAiPlaylist, setShowAiPlaylist] = useState(false);
  const [isAiPlaylistLoading, setIsAiPlaylistLoading] = useState(false);
  const [trendingTracks, setTrendingTracks] = useState<Track[]>([]);
  const [showTrending, setShowTrending] = useState(false);
  const [isTrendingLoading, setIsTrendingLoading] = useState(false);

  const handleSimilar = async () => {
    if (!track || isSimilarLoading) return;
    if (showSimilar) { setShowSimilar(false); return; }
    setIsSimilarLoading(true);
    haptic("medium");
    try {
      const results = await fetchSimilar(track.video_id, 10);
      setSimilarTracks(results);
      setShowSimilar(true);
    } catch { setSimilarTracks([]); }
    setIsSimilarLoading(false);
  };

  const handleAiPlaylist = async () => {
    if (!aiPrompt.trim() || isAiPlaylistLoading) return;
    setIsAiPlaylistLoading(true);
    haptic("medium");
    try {
      const prompt = aiPrompt.trim();
      const results = await generateAiPlaylist(prompt, 10);
      const safeResults = results.length > 0 ? results : await searchTracks(prompt, 10);
      setAiPlaylistTracks(safeResults);
      setShowAiPlaylist(true);
    } catch { setAiPlaylistTracks([]); }
    setIsAiPlaylistLoading(false);
  };

  const handleTrending = async () => {
    if (isTrendingLoading) return;
    if (showTrending) { setShowTrending(false); return; }
    setIsTrendingLoading(true);
    haptic("medium");
    try {
      const results = await fetchTrending(24, 20);
      setTrendingTracks(results);
      setShowTrending(true);
    } catch { setTrendingTracks([]); }
    setIsTrendingLoading(false);
  };

  const handlePlayAll = (tracks: Track[]) => {
    if (!tracks.length) return;
    haptic("medium");
    onPlayAll?.(tracks);
  };

  // Reset similar/ai-playlist on track change
  useEffect(() => { setShowSimilar(false); setSimilarTracks([]); }, [track?.video_id]);

  // Quick suggestions when queue is empty
  const [quickSuggestions, setQuickSuggestions] = useState<Track[]>([]);

  useEffect(() => {
    if (state.current_track && state.queue.length <= 1) {
      fetchSimilar(state.current_track.video_id, 4)
        .then(setQuickSuggestions)
        .catch(() => setQuickSuggestions([]));
    } else {
      setQuickSuggestions([]);
    }
  }, [state.current_track?.video_id, state.queue.length]);

  // Swipe tracking
  const touchStartX = useRef<number>(0);
  const touchEndX = useRef<number>(0);
  const [swipeOffset, setSwipeOffset] = useState(0);

  // Check if current track is liked
  useEffect(() => {
    if (track?.video_id) {
      checkFavorite(track.video_id).then(setIsLiked).catch(() => setIsLiked(false));
    } else {
      setIsLiked(false);
    }
  }, [track?.video_id]);

  const handleLikeToggle = async () => {
    if (!track) return;
    haptic(isLiked ? "light" : "medium");
    try {
      const newState = await toggleFavorite(track.video_id);
      setIsLiked(newState);
      // Send feedback to Supabase AI
      sendFeedback(newState ? "like" : "dislike", track.video_id, "player");
      if (newState) {
        ingestEvent("like", track, undefined, "player");
      }
    } catch {}
  };

  const handleShare = () => {
    if (!track) return;
    haptic("medium");
    const text = `${track.title} — ${track.artist}`;
    const url = `https://t.me/TSmymusicbot_bot/app?startapp=play_${track.video_id}`;
    try {
      window.Telegram?.WebApp?.openTelegramLink?.(
        `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`
      );
    } catch {
      // Fallback
      window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`, "_blank");
    }
  };

  const handleTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchEndX.current = e.touches[0].clientX;
  };

  const handleTouchMove = (e: TouchEvent) => {
    touchEndX.current = e.touches[0].clientX;
    const raw = touchEndX.current - touchStartX.current;
    // Rubber-band damping: resistance increases as you drag further
    const damped = Math.sign(raw) * Math.pow(Math.abs(raw), 0.75);
    setSwipeOffset(Math.max(-100, Math.min(100, damped)));
  };

  const handleTouchEnd = () => {
    const diff = touchEndX.current - touchStartX.current;
    if (diff > 60) {
      haptic("medium");
      onAction("prev");
    } else if (diff < -60) {
      haptic("medium");
      onAction("next");
    }
    setSwipeOffset(0);
  };

  // Reset seek value on track change
  useEffect(() => { setSeekValue(null); }, [track?.video_id]);

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? "0" : ""}${sec}`;
  };

  const qualityLabel = quality === "auto" ? "Auto" : `${quality} kbps`;
  const eqPresetLabel = formatEqPresetLabel(eqPreset);
  const audioControlsPanel = (warm = false) => canUseAudioControls ? (
    <div style={{
      marginTop: 18,
      padding: warm ? "16px 16px 14px" : "16px",
      borderRadius: 22,
      display: "flex",
      flexDirection: "column",
      gap: 14,
      background: warm ? "linear-gradient(180deg, rgba(40, 25, 15, 0.78), rgba(28, 18, 12, 0.72))" : "linear-gradient(180deg, rgba(124, 77, 255, 0.12), rgba(32, 24, 50, 0.32))",
      border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : "1px solid rgba(179, 136, 255, 0.16)",
      boxShadow: warm ? "0 16px 40px rgba(0,0,0,0.2)" : `0 16px 40px ${accentColorAlpha}`,
      backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, textAlign: warm ? "left" : "left" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: warm ? "#ffd54f" : accentColor, fontSize: 15, fontWeight: 700, letterSpacing: 0.6 }}>
            <IconEqualizer size={18} color={warm ? "#ffd54f" : accentColor} animated={false} />
            <span>Audio Pro</span>
          </div>
          <div style={{ fontSize: 12, color: warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>
            {isAdmin ? "Advanced sound for admin access" : "Premium sound scene with curated EQ presets"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <AudioBadge label={qualityLabel} active warm={warm} />
          <AudioBadge label={bypassProcessing ? "RAW" : eqPresetLabel} active warm={warm} />
        </div>
      </div>

      {/* Bypass / RAW mode toggle */}
      <button
        onClick={() => { haptic("medium"); onBypassToggle?.(!bypassProcessing); }}
        style={{
          padding: "10px 16px",
          borderRadius: 16,
          border: bypassProcessing
            ? (warm ? "1px solid #ffd54f" : `1px solid ${accentColor}`)
            : (warm ? "1px solid rgba(255, 213, 79, 0.18)" : "1px solid rgba(179, 136, 255, 0.16)"),
          background: bypassProcessing
            ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))" : `linear-gradient(135deg, ${accentColor}, #e040fb)`)
            : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
          color: bypassProcessing ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          transition: "all 0.3s ease",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          {bypassProcessing ? (
            <>
              <line x1="1" y1="1" x2="23" y2="23"/>
              <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/>
              <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2c0 .76-.13 1.49-.35 2.17"/>
              <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
            </>
          ) : (
            <>
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
            </>
          )}
        </svg>
        {bypassProcessing ? "RAW · Без обработки" : "Включить RAW (без обработки)"}
      </button>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: warm ? "#c8a882" : "#bca8ff" }}>
          Stream quality
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
          {QUALITY_OPTIONS.map((value) => {
            const active = quality === value;
            return (
              <button
                key={value}
                onClick={() => onQualityChange?.(value)}
                style={{
                  padding: warm ? "10px 8px" : "9px 8px",
                  borderRadius: 16,
                  border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : `1px solid ${active ? accentColor : accentColorAlpha}`,
                  background: active
                    ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))" : `linear-gradient(135deg, ${accentColor}, #e040fb)`)
                    : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
                  color: active ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: active ? 700 : 600,
                }}
              >
                {value === "auto" ? "Auto" : `${value}`}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: warm ? "#c8a882" : "#bca8ff" }}>
          EQ presets
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
          {EQ_OPTIONS.map((option) => {
            const active = eqPreset === option.value;
            return (
              <button
                key={option.value}
                onClick={() => onEqPresetChange?.(option.value)}
                style={{
                  padding: warm ? "11px 10px" : "10px",
                  minHeight: 64,
                  borderRadius: 18,
                  border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : `1px solid ${active ? accentColor : accentColorAlpha}`,
                  background: active
                    ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.34), rgba(255,213,79,0.22))" : `linear-gradient(135deg, ${accentColor}, rgba(224,64,251,0.92))`)
                    : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
                  color: active ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  justifyContent: "center",
                  gap: 4,
                  textAlign: "left",
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.1 }}>{option.label}</span>
                <span style={{ fontSize: 10, opacity: active ? 0.95 : 0.72, textTransform: "uppercase", letterSpacing: 0.6 }}>{option.note}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  ) : null;

  const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;
  const MOOD_OPTIONS = [
    { id: "chill", label: "Chill", icon: (c: string) => <IconMoodChill size={18} color={c} /> },
    { id: "energy", label: "Energy", icon: (c: string) => <IconMoodEnergy size={18} color={c} /> },
    { id: "focus", label: "Focus", icon: (c: string) => <IconMoodFocus size={18} color={c} /> },
    { id: "romance", label: "Romance", icon: (c: string) => <IconMoodRomance size={18} color={c} /> },
    { id: "melancholy", label: "Melancholy", icon: (c: string) => <IconMoodMelancholy size={18} color={c} /> },
    { id: "party", label: "Party", icon: (c: string) => <IconMoodParty size={18} color={c} /> },
  ];

  // ─── LUXURY FEATURES PANEL ─────────────────────────────
  const luxuryPanel = (warm: boolean) => {
    const panelBg = warm
      ? "linear-gradient(180deg, rgba(40, 25, 15, 0.78), rgba(28, 18, 12, 0.72))"
      : "linear-gradient(180deg, rgba(124, 77, 255, 0.08), rgba(32, 24, 50, 0.28))";
    const panelBorder = warm
      ? "1px solid rgba(255, 213, 79, 0.18)"
      : "1px solid rgba(179, 136, 255, 0.12)";
    const labelColor = warm ? "#c8a882" : "#bca8ff";
    const activeGrad = warm
      ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))"
      : `linear-gradient(135deg, ${accentColor}, #e040fb)`;
    const inactiveBg = warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)";
    const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
    const hlColor = warm ? "#ffd54f" : accentColor;

    return (
      <div style={{
        marginTop: 14,
        padding: warm ? "14px 14px 12px" : "14px",
        borderRadius: 22,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        background: panelBg,
        border: panelBorder,
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
      }}>
        {/* Quick Toggles Row */}
        <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
          {/* Spectrum Visualizer toggle */}
          <button onClick={onToggleSpectrum} style={{
            padding: "8px 14px", borderRadius: 16,
            border: showSpectrum ? `1px solid ${hlColor}` : panelBorder,
            background: showSpectrum ? activeGrad : inactiveBg,
            color: showSpectrum ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconSpectrum size={14} color={showSpectrum ? "#fff" : hlColor} /> Спектр
          </button>

          {/* Bass Boost toggle */}
          <button onClick={() => onBassBoost?.(!bassBoost)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: bassBoost ? `1px solid ${hlColor}` : panelBorder,
            background: bassBoost ? activeGrad : inactiveBg,
            color: bassBoost ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconBassBoost size={14} color={bassBoost ? "#fff" : hlColor} /> Bass+
          </button>

          {/* Party Mode */}
          <button onClick={() => onPartyMode?.(!partyMode)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: partyMode ? `1px solid ${hlColor}` : panelBorder,
            background: partyMode
              ? "linear-gradient(135deg, #ff6d00, #e040fb)"
              : inactiveBg,
            color: partyMode ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
            animation: partyMode ? "partyPulse 1.5s ease-in-out infinite" : "none",
          }}>
            <IconParty size={14} color={partyMode ? "#fff" : hlColor} /> Party
          </button>
        </div>

        {/* Luxury Audio Toggles */}
        <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
          <button onClick={() => onTapeWarmth?.(!tapeWarmth)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: tapeWarmth ? `1px solid ${hlColor}` : panelBorder,
            background: tapeWarmth ? (warm ? "linear-gradient(135deg, #ff8f00, #ffb300)" : activeGrad) : inactiveBg,
            color: tapeWarmth ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconFire size={14} color={tapeWarmth ? "#fff" : hlColor} /> Warmth
          </button>
          <button onClick={() => onAirBand?.(!airBand)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: airBand ? `1px solid ${hlColor}` : panelBorder,
            background: airBand ? activeGrad : inactiveBg,
            color: airBand ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconHiRes size={14} color={airBand ? "#fff" : hlColor} /> Air
          </button>
          <button onClick={() => onStereoWiden?.(!stereoWiden)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: stereoWiden ? `1px solid ${hlColor}` : panelBorder,
            background: stereoWiden ? activeGrad : inactiveBg,
            color: stereoWiden ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconSpatial size={14} color={stereoWiden ? "#fff" : hlColor} /> Wide
          </button>
          <button onClick={() => onSoftClip?.(!softClip)} style={{
            padding: "8px 14px", borderRadius: 16,
            border: softClip ? `1px solid ${hlColor}` : panelBorder,
            background: softClip ? activeGrad : inactiveBg,
            color: softClip ? "#fff" : textColor,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <IconMood size={14} color={softClip ? "#fff" : hlColor} /> Limiter
          </button>
        </div>

        {/* Crossfade Duration */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
              <IconWave size={14} color={labelColor} /> Crossfade
            </div>
            <span style={{ fontSize: 10, color: labelColor, fontVariantNumeric: "tabular-nums" }}>
              {crossfadeDuration === 0 ? "OFF" : `${crossfadeDuration}s`}
            </span>
          </div>
          <input
            type="range" min={0} max={12} step={1}
            value={crossfadeDuration}
            onInput={(e) => { haptic("light"); onCrossfadeDuration?.(Number((e.target as HTMLInputElement).value)); }}
            style={{ width: "100%", height: 4, accentColor: hlColor, cursor: "pointer" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: labelColor, opacity: 0.7 }}>
            <span>OFF</span><span>12 сек</span>
          </div>
        </div>

        {/* Vinyl Spin Toggle */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
            💿 Vinyl Spin
          </div>
          <button onClick={() => { haptic("light"); onVinylSpin?.(!vinylSpin); }} style={{
            padding: "5px 14px", borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: "pointer",
            border: vinylSpin ? `1px solid ${hlColor}` : panelBorder,
            background: vinylSpin ? activeGrad : inactiveBg,
            color: vinylSpin ? "#fff" : textColor,
          }}>
            {vinylSpin ? "ON" : "OFF"}
          </button>
        </div>

        {/* 3D Spatial Panner */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
              <IconSpatial size={14} color={labelColor} /> 3D Spatial
            </div>
            <span style={{ fontSize: 10, color: labelColor, fontVariantNumeric: "tabular-nums" }}>
              {panValue === 0 ? "Center" : panValue < 0 ? `L ${Math.abs(Math.round(panValue * 100))}%` : `R ${Math.round(panValue * 100)}%`}
            </span>
          </div>
          <input
            type="range" min={-1} max={1} step={0.01}
            value={panValue}
            onInput={(e) => onPanChange?.(Number((e.target as HTMLInputElement).value))}
            style={{ width: "100%", height: 4, accentColor: hlColor, cursor: "pointer" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: labelColor, opacity: 0.7 }}>
            <span>◀ Left</span><span>Right ▶</span>
          </div>
        </div>

        {/* Playback Speed */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
            <IconSpeed size={14} color={labelColor} /> Скорость
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 6 }}>
            {SPEED_OPTIONS.map((s) => {
              const active = playbackSpeed === s;
              return (
                <button
                  key={s}
                  onClick={() => { haptic("light"); onSpeedChange?.(s); }}
                  style={{
                    padding: "7px 4px", borderRadius: 12,
                    border: active ? `1px solid ${hlColor}` : panelBorder,
                    background: active ? activeGrad : inactiveBg,
                    color: active ? "#fff" : textColor,
                    fontSize: 11, fontWeight: active ? 700 : 500,
                    cursor: "pointer",
                  }}
                >
                  {s}x
                </button>
              );
            })}
          </div>
        </div>

        {/* Mood Filter for AI Wave */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
            <IconMood size={14} color={labelColor} /> Настроение
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
            {MOOD_OPTIONS.map((m) => {
              const active = moodFilter === m.id;
              return (
                <button
                  key={m.id}
                  onClick={() => { haptic("light"); onMoodChange?.(active ? null : m.id); }}
                  style={{
                    padding: "8px 6px", borderRadius: 14,
                    border: active ? `1px solid ${hlColor}` : panelBorder,
                    background: active ? activeGrad : inactiveBg,
                    color: active ? "#fff" : textColor,
                    fontSize: 12, fontWeight: active ? 700 : 500,
                    cursor: "pointer",
                    display: "flex", flexDirection: "column",
                    alignItems: "center", gap: 2,
                  }}
                >
                  {m.icon(active ? "#fff" : textColor)}
                  <span style={{ fontSize: 10 }}>{m.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Hi-Res Badge */}
        {(quality === "320" || quality === "auto") && (
          <div style={{
            display: "flex", justifyContent: "center", gap: 8, marginTop: 2,
          }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "5px 12px", borderRadius: 999,
              fontSize: 10, fontWeight: 700, letterSpacing: 1,
              color: warm ? "#ffd54f" : "#b388ff",
              background: warm ? "rgba(255, 213, 79, 0.08)" : "rgba(124, 77, 255, 0.08)",
              border: warm ? "1px solid rgba(255, 213, 79, 0.15)" : "1px solid rgba(179, 136, 255, 0.15)",
              textTransform: "uppercase",
            }}>
              <IconHiRes size={14} color={warm ? "#ffd54f" : "#b388ff"} />
              HI-RES AUDIO · {quality === "320" ? "320kbps" : "ADAPTIVE"}
            </span>
          </div>
        )}
      </div>
    );
  };

  // ─── TEQUILA LUXURY THEME ───────────────────────────────
  if (isTequila) {
    const gold = "#ffd54f";
    const warmAccent = accentColor;
    const warmAlpha = accentColorAlpha;
    const glassCard = "rgba(40, 25, 15, 0.55)";
    const borderGold = "rgba(255, 213, 79, 0.25)";
    const tqBtn: Record<string, string | number> = {
      background: "none",
      border: "none",
      color: "#fef0e0",
      cursor: "pointer",
      padding: "10px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    };

    return (
      <div style={{ textAlign: "center", padding: "8px 0" }}>
        <style>{`
          @keyframes vinylSpin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          @keyframes tequilaGlow {
            0% { box-shadow: 0 12px 40px rgba(255, 109, 0, 0.22), 0 0 0 1px rgba(255, 213, 79, 0.22), inset 0 0 0 1px rgba(255,213,79,0.1); }
            50% { box-shadow: 0 16px 54px rgba(255, 109, 0, 0.34), 0 0 0 1px rgba(255, 213, 79, 0.30), inset 0 0 0 1px rgba(255,213,79,0.16); }
            100% { box-shadow: 0 12px 40px rgba(255, 109, 0, 0.22), 0 0 0 1px rgba(255, 213, 79, 0.22), inset 0 0 0 1px rgba(255,213,79,0.1); }
          }
          @keyframes tequilaPulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.04); }
            100% { transform: scale(1); }
          }
          @keyframes tequilaShimmer {
            0% { opacity: .35; transform: translateX(-140%) rotate(18deg); }
            50% { opacity: .55; }
            100% { opacity: 0; transform: translateX(160%) rotate(18deg); }
          }
        `}</style>
        {/* Cover — luxury framed */}
        <div
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          style={{
            position: "relative",
            width: 260,
            height: 260,
            margin: "0 auto 20px",
            borderRadius: vinylSpin ? "50%" : 24,
            background: track
              ? `linear-gradient(135deg, rgba(255,167,38,0.15), rgba(255,213,79,0.08))`
              : "linear-gradient(135deg, #ff6d00 0%, #ffd54f 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: track
              ? `0 12px 40px rgba(255, 109, 0, 0.25), 0 0 0 1px ${borderGold}, inset 0 0 0 1px rgba(255,213,79,0.1)`
              : "0 8px 24px rgba(255,109,0,0.3)",
            animation: vinylSpin && state.is_playing && track ? "vinylSpin 4s linear infinite" : (state.is_playing ? "tequilaGlow 3.6s ease-in-out infinite" : "none"),
            overflow: "hidden",
            transition: swipeOffset === 0 ? "transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)" : "none",
            transform: `translate3d(${swipeOffset}px, 0, 0) scale(${state.is_playing && !vinylSpin ? 1.03 : 1})`,
            willChange: "transform",
            touchAction: "pan-y",
            userSelect: "none",
          }}
        >
          {track?.cover_url ? (
            <img
              src={track.cover_url}
              alt="Cover"
              style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none", borderRadius: vinylSpin ? "50%" : 0 }}
              draggable={false}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          ) : (
            track ? <IconMusic size={64} color="rgba(255,245,220,0.8)" /> : <IconMusicNote size={48} color="rgba(255,245,220,0.5)" />
          )}
          {/* Vinyl center hole */}
          {vinylSpin && track && (
            <div style={{
              position: "absolute",
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: "radial-gradient(circle, #1a120b 40%, rgba(26,18,11,0.9) 60%, transparent 100%)",
              border: `2px solid ${borderGold}`,
              boxShadow: "0 0 12px rgba(0,0,0,0.6)",
              zIndex: 2,
            }} />
          )}
          {/* Warm visualizer */}
          {track && <AudioVisualizer isPlaying={state.is_playing} accentColor="#ff6d00" />}
          {/* Golden shimmer border overlay */}
          <div style={{
            position: "absolute",
            inset: 0,
            borderRadius: 24,
            border: `1.5px solid ${borderGold}`,
            pointerEvents: "none",
          }} />
          {state.is_playing && (
            <div style={{
              position: "absolute",
              top: -20,
              left: -60,
              width: 120,
              height: 320,
              background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,244,200,0.26), rgba(255,255,255,0))",
              transform: "rotate(18deg)",
              animation: "tequilaShimmer 2.8s ease-in-out infinite",
              pointerEvents: "none",
            }} />
          )}
        </div>

        {/* Glass info card */}
        <div style={{
          margin: "0 16px 16px",
          padding: "14px 20px",
          borderRadius: 20,
          background: glassCard,
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: `1px solid ${borderGold}`,
        }}>
          <Marquee
            text={track?.title ?? "Ничего не играет"}
            style={{ fontSize: 17, fontWeight: 600, color: "#fef0e0", letterSpacing: 0.5 }}
          />
          <Marquee
            text={track ? `${track.artist}  ·  ${track.duration_fmt}  ·  ${qualityLabel}` : "—"}
            style={{ fontSize: 13, color: "#c8a882", marginTop: 4 }}
          />
        </div>

        {/* Seek slider — warm */}
        {track && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: "#c8a882", minWidth: 36, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
              {fmtTime(elapsed)}
            </span>
            <div style={{ flex: 1, padding: "12px 0", touchAction: "none" }}>
              <input
                type="range"
                min={0}
                max={duration || 1}
                value={elapsed}
                disabled={duration === 0}
                onInput={(e) => {
                  if (duration > 0) {
                    setSeeking(true);
                    setSeekValue(Number((e.target as HTMLInputElement).value));
                  }
                }}
                onChange={(e) => {
                  if (duration > 0) {
                    const pos = Number((e.target as HTMLInputElement).value);
                    setSeekValue(null);
                    setSeeking(false);
                    haptic("light");
                    onAction("seek", track.video_id, pos);
                  }
                }}
                style={{
                  width: "100%",
                  height: 5,
                  accentColor: "#ffa726",
                  cursor: duration > 0 ? "pointer" : "default",
                  opacity: duration > 0 ? 1 : 0.5,
                }}
              />
            </div>
            <span style={{ fontSize: 11, color: "#c8a882", minWidth: 36, fontVariantNumeric: "tabular-nums" }}>
              {duration > 0 ? fmtTime(duration) : "-:--"}
            </span>
          </div>
        )}

        {/* Main controls — luxury circular */}
        <div style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 8,
          marginTop: 12,
          padding: "0 16px",
        }}>
          <button style={tqBtn} onClick={() => { haptic("light"); onAction("shuffle"); }}>
            <IconShuffle active={state.shuffle} color={state.shuffle ? gold : "#c8a882"} />
          </button>
          <button
            style={{
              ...tqBtn,
              background: "rgba(255,213,79,0.08)",
              borderRadius: "50%",
              width: 48,
              height: 48,
              border: `1px solid ${borderGold}`,
            }}
            onClick={() => { haptic("medium"); onAction("prev"); }}
          >
            <IconSkipBack />
          </button>
          {/* Play/Pause — golden glow */}
          <button
            style={{
              ...tqBtn,
              background: `linear-gradient(135deg, #ff6d00, #ffa726)`,
              color: "#1a120b",
              borderRadius: "50%",
              padding: 14,
              width: 72,
              height: 72,
              boxShadow: `0 6px 24px rgba(255, 109, 0, 0.45), 0 0 0 3px rgba(255, 213, 79, 0.15)`,
              transition: "all 0.4s ease",
              position: "relative",
              border: "none",
              animation: state.is_playing && !buffering ? "tequilaPulse 2.6s ease-in-out infinite" : "none",
            }}
            onClick={() => { haptic("heavy"); onAction(state.is_playing ? "pause" : "play"); }}
          >
            {buffering ? (
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ animation: "spin 1s linear infinite" }}>
                <path d="M12 2a10 10 0 0 1 10 10" />
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              </svg>
            ) : state.is_playing ? <IconPause /> : <IconPlay />}
          </button>
          <button
            style={{
              ...tqBtn,
              background: "rgba(255,213,79,0.08)",
              borderRadius: "50%",
              width: 48,
              height: 48,
              border: `1px solid ${borderGold}`,
            }}
            onClick={() => { haptic("medium"); onAction("next"); }}
          >
            <IconSkipForward />
          </button>
          <button style={tqBtn} onClick={() => { haptic("light"); onAction("repeat"); }}>
            <IconRepeat mode={state.repeat_mode} activeColor={gold} />
          </button>
        </div>

        {/* Smart Suggestions — when queue is empty */}
        {quickSuggestions.length > 0 && (
          <div style={{
            marginTop: 14,
            padding: "10px 14px",
            borderRadius: 16,
            background: glassCard,
            backdropFilter: "blur(12px)",
            border: `1px solid ${borderGold}`,
          }}>
            <div style={{ fontSize: 11, color: "#c8a882", marginBottom: 8, fontWeight: 600 }}>Далее:</div>
            <div style={{ display: "flex", gap: 8, overflowX: "auto", scrollbarWidth: "none", msOverflowStyle: "none" }}>
              {quickSuggestions.map((t) => (
                <div
                  key={t.video_id}
                  onClick={() => { haptic("medium"); onPlayTrack?.(t); }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "5px 10px 5px 5px",
                    borderRadius: 20,
                    background: "rgba(255, 213, 79, 0.08)",
                    border: `1px solid ${borderGold}`,
                    cursor: "pointer",
                    flexShrink: 0,
                    maxWidth: 180,
                    transition: "background 0.2s ease",
                  }}
                >
                  <img
                    src={t.thumbnail}
                    alt=""
                    style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover", flexShrink: 0 }}
                  />
                  <span style={{
                    fontSize: 12,
                    color: "#fef0e0",
                    fontWeight: 500,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}>{t.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Action Buttons Carousel — warm tones */}
        {track && (
          <div style={{
            marginTop: 24,
            position: "relative",
            overflow: "hidden",
          }}>
            <div style={{
              display: "flex",
              gap: 8,
              overflowX: "auto",
              scrollSnapType: "x mandatory",
              WebkitOverflowScrolling: "touch",
              paddingBottom: 8,
              paddingLeft: 16,
              paddingRight: 16,
              msOverflowStyle: "none",
              scrollbarWidth: "none",
            }}>
              {/* Текст */}
              <button
                onClick={() => { haptic("light"); onShowLyrics(track.video_id); }}
                style={{
                  padding: "10px 18px",
                  borderRadius: 24,
                  border: `1px solid ${borderGold}`,
                  background: glassCard,
                  backdropFilter: "blur(12px)",
                  color: "#fef0e0",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  letterSpacing: 0.5,
                }}
              >
                <IconLyrics /> Текст
              </button>
              {/* Like */}
              <button
                onClick={handleLikeToggle}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${isLiked ? "#ff6d00" : borderGold}`,
                  background: isLiked ? "rgba(255, 109, 0, 0.18)" : glassCard,
                  backdropFilter: "blur(12px)",
                  color: isLiked ? "#ffa726" : "#fef0e0",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  transition: "all 0.3s ease",
                }}
              >
                <IconHeart filled={isLiked} />
              </button>
              {/* В плейлист */}
              <button
                onClick={() => { haptic("light"); onAddToPlaylist?.(); }}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${borderGold}`,
                  background: glassCard,
                  backdropFilter: "blur(12px)",
                  color: "#fef0e0",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                }}
              >
                <IconPlus size={16} /> В плейлист
              </button>
              {/* Share */}
              <button
                onClick={handleShare}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${borderGold}`,
                  background: glassCard,
                  backdropFilter: "blur(12px)",
                  color: "#fef0e0",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                }}
              >
                <IconShare size={18} />
              </button>
              {/* Story */}
              <button
                onClick={() => { haptic("medium"); setShowShareCard(true); }}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${borderGold}`,
                  background: "linear-gradient(135deg, rgba(255,109,0,0.15), rgba(255,213,79,0.1))",
                  backdropFilter: "blur(12px)",
                  color: "#fef0e0",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                }}
              >
                <IconImage size={18} /> Story
              </button>
              {/* Волна */}
              <button
                onClick={() => { haptic("medium"); onWave?.(); }}
                disabled={isWaveLoading}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${gold}55`,
                  background: "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))",
                  backdropFilter: "blur(12px)",
                  color: gold,
                  cursor: isWaveLoading ? "wait" : "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  transition: "all 0.3s ease",
                  opacity: isWaveLoading ? 0.6 : 1,
                }}
              >
                {isWaveLoading ? <IconSpinner size={18} color={gold} /> : <IconWave size={18} />}
                Волна
              </button>
              {/* Похожие */}
              <button
                onClick={handleSimilar}
                disabled={!track || isSimilarLoading}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${showSimilar ? gold + "88" : borderGold}`,
                  background: showSimilar ? "rgba(255,167,38,0.18)" : glassCard,
                  backdropFilter: "blur(12px)",
                  color: showSimilar ? gold : "#fef0e0",
                  cursor: !track || isSimilarLoading ? "wait" : "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  transition: "all 0.3s ease",
                  opacity: !track ? 0.4 : 1,
                }}
              >
                {isSimilarLoading ? <IconSpinner size={18} color={showSimilar ? gold : "#fef0e0"} /> : <IconSimilar size={18} />}
                Похожие
              </button>
              {/* Тренды */}
              <button
                onClick={handleTrending}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${showTrending ? gold + "88" : borderGold}`,
                  background: showTrending ? "rgba(255,167,38,0.18)" : glassCard,
                  backdropFilter: "blur(12px)",
                  color: showTrending ? gold : "#fef0e0",
                  cursor: isTrendingLoading ? "wait" : "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  transition: "all 0.3s ease",
                }}
              >
                {isTrendingLoading ? <IconSpinner size={18} color={showTrending ? gold : "#fef0e0"} /> : <IconTrending size={18} />}
                Тренды
              </button>
              {/* Сон */}
              <button
                onClick={() => { haptic("light"); setShowSleepMenu(!showSleepMenu); }}
                style={{
                  padding: "10px 16px",
                  borderRadius: 24,
                  border: `1px solid ${sleepTimerRemaining ? gold + "88" : borderGold}`,
                  background: sleepTimerRemaining ? "rgba(255,167,38,0.18)" : glassCard,
                  backdropFilter: "blur(12px)",
                  color: sleepTimerRemaining ? gold : "#fef0e0",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  scrollSnapAlign: "start",
                  transition: "all 0.3s ease",
                }}
              >
                <IconMoon size={18} />
                {sleepTimerRemaining ? `${Math.ceil(sleepTimerRemaining / 60)}м` : "Сон"}
              </button>
            </div>
            {/* Carousel fade edges — warm */}
            <div style={{ position: "absolute", top: 0, left: 0, width: 20, height: "100%", background: "linear-gradient(90deg, rgba(28, 18, 12, 1), transparent)", pointerEvents: "none" }} />
            <div style={{ position: "absolute", top: 0, right: 0, width: 20, height: "100%", background: "linear-gradient(270deg, rgba(28, 18, 12, 1), transparent)", pointerEvents: "none" }} />
          </div>
        )}

        {/* Similar Tracks — warm */}
        {showSimilar && similarTracks.length > 0 && (
          <div style={{
            marginTop: 14,
            padding: 14,
            borderRadius: 20,
            background: "rgba(40, 25, 15, 0.75)",
            backdropFilter: "blur(16px)",
            border: `1px solid ${borderGold}`,
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: gold, marginBottom: 10 }}>Похожие треки</div>
            <button onClick={() => handlePlayAll(similarTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${gold}55`, background: "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))", color: gold, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
            {similarTracks.map((t) => (
              <button
                key={t.video_id}
                onClick={() => { haptic("light"); onPlayTrack?.(t); }}
                style={{
                  display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                  background: "none", border: "none", borderBottom: `1px solid ${borderGold}`,
                  color: "#fef0e0", cursor: "pointer", textAlign: "left", fontSize: 13,
                }}
              >
                {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
                <div style={{ flex: 1, overflow: "hidden" }}>
                  <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: "#c8a882" }}>{t.artist}</div>
                </div>
                <div style={{ fontSize: 11, color: "#c8a882" }}>{t.duration_fmt}</div>
              </button>
            ))}
          </div>
        )}

        {/* AI Playlist — warm */}
        <div style={{
          marginTop: 14,
          padding: 14,
          borderRadius: 20,
          background: "rgba(40, 25, 15, 0.65)",
          backdropFilter: "blur(16px)",
          border: `1px solid ${borderGold}`,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: gold, marginBottom: 10 }}>AI Плейлист</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              placeholder="грустный рок на вечер..."
              value={aiPrompt}
              onInput={(e: any) => { const v = e.target.value; setAiPrompt(v); if (!v.trim()) { setShowAiPlaylist(false); setAiPlaylistTracks([]); } }}
              onKeyDown={(e: any) => { if (e.key === "Enter") handleAiPlaylist(); }}
              style={{
                flex: 1, padding: "10px 14px", borderRadius: 14, border: `1px solid ${borderGold}`,
                background: "rgba(255,213,79,0.06)", color: "#fef0e0", fontSize: 13, outline: "none",
              }}
            />
            <button
              onClick={handleAiPlaylist}
              disabled={isAiPlaylistLoading || !aiPrompt.trim()}
              style={{
                padding: "10px 18px", borderRadius: 14, border: `1px solid ${gold}55`,
                background: "linear-gradient(135deg, rgba(255,109,0,0.25), rgba(255,213,79,0.15))",
                color: gold, cursor: isAiPlaylistLoading ? "wait" : "pointer",
                fontSize: 13, fontWeight: 700, opacity: isAiPlaylistLoading || !aiPrompt.trim() ? 0.5 : 1,
              }}
            >
              {isAiPlaylistLoading ? "..." : "Go"}
            </button>
          </div>
          {showAiPlaylist && aiPlaylistTracks.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <button onClick={() => handlePlayAll(aiPlaylistTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${gold}55`, background: "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))", color: gold, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
              {aiPlaylistTracks.map((t) => (
                <button
                  key={t.video_id}
                  onClick={() => { haptic("light"); onPlayTrack?.(t); }}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                    background: "none", border: "none", borderBottom: `1px solid ${borderGold}`,
                    color: "#fef0e0", cursor: "pointer", textAlign: "left", fontSize: 13,
                  }}
                >
                  {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
                  <div style={{ flex: 1, overflow: "hidden" }}>
                    <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                    <div style={{ fontSize: 11, color: "#c8a882" }}>{t.artist}</div>
                  </div>
                  <div style={{ fontSize: 11, color: "#c8a882" }}>{t.duration_fmt}</div>
                </button>
              ))}
            </div>
          )}
          {showAiPlaylist && aiPlaylistTracks.length === 0 && !isAiPlaylistLoading && (
            <div style={{ marginTop: 10, textAlign: "center", color: "#c8a882", fontSize: 12 }}>Ничего не найдено</div>
          )}
        </div>

        {/* Trending — warm */}
        {showTrending && trendingTracks.length > 0 && (
          <div style={{
            marginTop: 14,
            padding: 14,
            borderRadius: 20,
            background: "rgba(40, 25, 15, 0.75)",
            backdropFilter: "blur(16px)",
            border: `1px solid ${borderGold}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: gold, display: "flex", alignItems: "center", gap: 4 }}><IconFire size={14} /> Тренды</div>
              <button
                onClick={() => setShowTrending(false)}
                style={{
                  padding: "5px 10px",
                  borderRadius: 12,
                  border: `1px solid ${gold}55`,
                  background: "rgba(255,213,79,0.08)",
                  color: gold,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: 700,
                }}
              >
                Скрыть
              </button>
            </div>
            <button onClick={() => handlePlayAll(trendingTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${gold}55`, background: "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))", color: gold, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
            {trendingTracks.map((t, i) => (
              <button
                key={t.video_id}
                onClick={() => { haptic("light"); onPlayTrack?.(t); }}
                style={{
                  display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                  background: "none", border: "none", borderBottom: `1px solid ${borderGold}`,
                  color: "#fef0e0", cursor: "pointer", textAlign: "left", fontSize: 13,
                }}
              >
                <span style={{ fontSize: 14, fontWeight: 700, color: gold, minWidth: 20 }}>{i + 1}</span>
                {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
                <div style={{ flex: 1, overflow: "hidden" }}>
                  <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: "#c8a882" }}>{t.artist}</div>
                </div>
                <div style={{ fontSize: 11, color: "#c8a882" }}>{t.duration_fmt}</div>
              </button>
            ))}
          </div>
        )}

        {audioControlsPanel(true)}
        {luxuryPanel(true)}

        <style>{`
          @keyframes partyPulse {
            0% { box-shadow: 0 0 8px rgba(255, 109, 0, 0.3); }
            50% { box-shadow: 0 0 20px rgba(224, 64, 251, 0.5); }
            100% { box-shadow: 0 0 8px rgba(255, 109, 0, 0.3); }
          }
        `}</style>

        {/* Sleep menu — warm glass */}
        {showSleepMenu && (
          <div style={{
            marginTop: 12,
            padding: 14,
            borderRadius: 20,
            background: "rgba(40, 25, 15, 0.85)",
            backdropFilter: "blur(20px)",
            border: `1px solid ${borderGold}`,
            display: "flex",
            gap: 8,
            justifyContent: "center",
            flexWrap: "wrap",
          }}>
            {[5, 15, 30, 45, 60].map((m) => (
              <button
                key={m}
                onClick={() => {
                  haptic("medium");
                  onSleepTimer?.(m);
                  setShowSleepMenu(false);
                }}
                style={{
                  padding: "7px 16px",
                  borderRadius: 14,
                  border: `1px solid ${borderGold}`,
                  background: "rgba(255,213,79,0.08)",
                  color: "#fef0e0",
                  fontSize: 13,
                  cursor: "pointer",
                  transition: "background 0.2s ease",
                }}
              >
                {m} мин
              </button>
            ))}
            {sleepTimerRemaining && (
              <button
                onClick={() => {
                  haptic("light");
                  onSleepTimer?.(null);
                  setShowSleepMenu(false);
                }}
                style={{
                  padding: "7px 16px",
                  borderRadius: 14,
                  border: "1px solid rgba(255, 109, 0, 0.4)",
                  background: "rgba(255, 109, 0, 0.15)",
                  color: "#ff6d00",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Отмена
              </button>
            )}
          </div>
        )}

        {/* Share Card Modal */}
        {showShareCard && track && (
          <ShareCard
            track={track}
            onClose={() => setShowShareCard(false)}
            accentColor={accentColor}
            themeId={themeId}
          />
        )}
      </div>
    );
  }

  // ─── DEFAULT BLACK ROOM THEME ──────────────────────────
  return (
    <div style={{ textAlign: "center", padding: "16px 0" }}>
      <style>{`
        @keyframes vinylSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      {/* Cover container with swipe */}
      <div
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        style={{
          position: "relative",
          width: 240,
          height: 240,
          margin: "0 auto 24px",
          borderRadius: vinylSpin ? "50%" : 20,
          background: track ? "var(--tg-theme-secondary-bg-color, #2a2a3e)" : "linear-gradient(135deg, #7c4dff 0%, #e040fb 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 64,
          boxShadow: track ? (vinylSpin ? `0 8px 24px rgba(0,0,0,0.4), 0 0 0 3px rgba(60,60,80,0.5)` : "0 8px 24px rgba(0,0,0,0.3)") : "none",
          overflow: "hidden",
          transition: swipeOffset === 0 ? "transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)" : "none",
          transform: `translate3d(${swipeOffset}px, 0, 0) scale(${state.is_playing && !vinylSpin ? 1.02 : 1})`,
          animation: vinylSpin && state.is_playing && track ? "vinylSpin 4s linear infinite" : "none",
          willChange: "transform",
          touchAction: "pan-y",
          userSelect: "none",
        }}
      >
        {track?.cover_url ? (
          <img
            src={track.cover_url}
            alt="Cover"
            style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none", borderRadius: vinylSpin ? "50%" : 0 }}
            draggable={false}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        ) : (
          track ? <IconMusic size={64} color="rgba(255,255,255,0.8)" /> : <IconMusicNote size={48} color="rgba(255,255,255,0.5)" />
        )}
        {/* Vinyl center hole */}
        {vinylSpin && track && (
          <div style={{
            position: "absolute",
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "radial-gradient(circle, #1a1a2e 40%, rgba(26,26,46,0.9) 60%, transparent 100%)",
            border: `2px solid ${accentColor}`,
            boxShadow: "0 0 12px rgba(0,0,0,0.6)",
            zIndex: 2,
          }} />
        )}
        {/* Audio Visualizer overlay */}
        {track && <AudioVisualizer isPlaying={state.is_playing} accentColor={accentColor} />}
      </div>

      {/* Track info with Marquee */}
      <div style={{ padding: "0 24px", marginBottom: 4 }}>
        <Marquee
          text={track?.title ?? "Ничего не играет"}
          style={{ fontSize: 18, fontWeight: 600 }}
        />
      </div>
      <div style={{ padding: "0 24px", fontSize: 14, color: "var(--tg-theme-hint-color, #aaa)", marginBottom: 16 }}>
        <Marquee
          text={track ? `${track.artist} • ${track.duration_fmt} • ${qualityLabel}` : "—"}
          style={{}}
        />
      </div>

      {/* Seek slider - improved touch area */}
      {track && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36, textAlign: "right" }}>
            {fmtTime(elapsed)}
          </span>
          <div style={{ flex: 1, padding: "12px 0", touchAction: "none" }}>
            <input
              type="range"
              min={0}
              max={duration || 1}
              value={elapsed}
              disabled={duration === 0}
              onInput={(e) => {
                if (duration > 0) {
                  setSeeking(true);
                  setSeekValue(Number((e.target as HTMLInputElement).value));
                }
              }}
              onChange={(e) => {
                if (duration > 0) {
                  const pos = Number((e.target as HTMLInputElement).value);
                  setSeekValue(null);
                  setSeeking(false);
                  haptic("light");
                  onAction("seek", track.video_id, pos);
                }
              }}
              style={{
                width: "100%",
                height: 6,
                accentColor: "var(--tg-theme-button-color, #7c4dff)",
                cursor: duration > 0 ? "pointer" : "default",
                opacity: duration > 0 ? 1 : 0.5,
              }}
            />
          </div>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36 }}>
            {duration > 0 ? fmtTime(duration) : "-:--"}
          </span>
        </div>
      )}

      {/* Controls with haptic feedback */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 16 }}>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("shuffle"); }}>
          <IconShuffle active={state.shuffle} color={accentColor} />
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("prev"); }}>
          <IconSkipBack />
        </button>
        <button
          style={{ ...btnStyle, background: accentColor, color: "#fff", borderRadius: "50%", padding: 12, width: 64, height: 64, boxShadow: `0 4px 12px ${accentColorAlpha}`, transition: "background 0.5s ease, box-shadow 0.5s ease", position: "relative" }}
          onClick={() => { haptic("heavy"); onAction(state.is_playing ? "pause" : "play"); }}
        >
          {buffering ? (
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ animation: "spin 1s linear infinite" }}>
              <path d="M12 2a10 10 0 0 1 10 10" />
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </svg>
          ) : state.is_playing ? <IconPause /> : <IconPlay />}
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("next"); }}>
          <IconSkipForward />
        </button>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("repeat"); }}>
          <IconRepeat mode={state.repeat_mode} activeColor={accentColor} />
        </button>
      </div>

      {/* Smart Suggestions — when queue is empty */}
      {quickSuggestions.length > 0 && (
        <div style={{
          marginTop: 14,
          padding: "10px 14px",
          borderRadius: 16,
          background: "rgba(255,255,255,0.06)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(179, 136, 255, 0.16)",
        }}>
          <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", marginBottom: 8, fontWeight: 600 }}>Далее:</div>
          <div style={{ display: "flex", gap: 8, overflowX: "auto", scrollbarWidth: "none", msOverflowStyle: "none" }}>
            {quickSuggestions.map((t) => (
              <div
                key={t.video_id}
                onClick={() => { haptic("medium"); onPlayTrack?.(t); }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "5px 10px 5px 5px",
                  borderRadius: 20,
                  background: "rgba(124, 77, 255, 0.08)",
                  border: "1px solid rgba(179, 136, 255, 0.16)",
                  cursor: "pointer",
                  flexShrink: 0,
                  maxWidth: 180,
                  transition: "background 0.2s ease",
                }}
              >
                <img
                  src={t.thumbnail}
                  alt=""
                  style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover", flexShrink: 0 }}
                />
                <span style={{
                  fontSize: 12,
                  color: "var(--tg-theme-text-color, #eee)",
                  fontWeight: 500,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>{t.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Buttons Carousel */}
      {track && (
        <div style={{
          marginTop: 24,
          position: "relative",
          overflow: "hidden",
        }}>
          <div style={{
            display: "flex",
            gap: 10,
            overflowX: "auto",
            scrollSnapType: "x mandatory",
            WebkitOverflowScrolling: "touch",
            paddingBottom: 8,
            paddingLeft: 16,
            paddingRight: 16,
            msOverflowStyle: "none",
            scrollbarWidth: "none",
          }}>
            {/* Текст */}
            <button
              onClick={() => { haptic("light"); onShowLyrics(track.video_id); }}
              style={{
                padding: "10px 18px",
                borderRadius: 20,
                border: "1px solid var(--tg-theme-hint-color, #555)",
                background: "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: "var(--tg-theme-text-color, #eee)",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                flexShrink: 0,
                scrollSnapAlign: "start",
              }}
            >
              <IconLyrics /> Текст
            </button>
            {/* Like */}
            <button
              onClick={handleLikeToggle}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: `1px solid ${isLiked ? "#ff4081" : "var(--tg-theme-hint-color, #555)"}`,
                background: isLiked ? "rgba(255, 64, 129, 0.15)" : "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: isLiked ? "#ff4081" : "var(--tg-theme-text-color, #eee)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
                transition: "all 0.2s ease",
              }}
            >
              <IconHeart filled={isLiked} />
            </button>
            {/* В плейлист */}
            <button
              onClick={() => { haptic("light"); onAddToPlaylist?.(); }}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: "var(--tg-theme-text-color, #eee)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
              }}
            >
              <IconPlus size={16} /> В плейлист
            </button>
            {/* Share */}
            <button
              onClick={handleShare}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: "1px solid var(--tg-theme-hint-color, #555)",
                background: "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: "var(--tg-theme-text-color, #eee)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
              }}
            >
              <IconShare size={18} />
            </button>
            {/* Story */}
            <button
              onClick={() => { haptic("medium"); setShowShareCard(true); }}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: "1px solid var(--tg-theme-hint-color, #555)",
                background: "linear-gradient(135deg, rgba(255,64,129,0.12), rgba(124,77,255,0.12))",
                backdropFilter: "blur(12px)",
                color: "var(--tg-theme-text-color, #eee)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
              }}
            >
              <IconImage size={18} /> Story
            </button>
            {/* Волна */}
            <button
              onClick={() => { haptic("medium"); onWave?.(); }}
              disabled={isWaveLoading}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "linear-gradient(135deg, rgba(124,77,255,0.15), rgba(224,64,251,0.12))",
                backdropFilter: "blur(12px)",
                color: "var(--tg-theme-text-color, #eee)",
                cursor: isWaveLoading ? "wait" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
                transition: "all 0.3s ease",
                opacity: isWaveLoading ? 0.6 : 1,
              }}
            >
              {isWaveLoading ? <IconSpinner size={18} /> : <IconWave size={18} />}
              Волна
            </button>
            {/* Похожие */}
            <button
              onClick={handleSimilar}
              disabled={!track || isSimilarLoading}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: `1px solid ${showSimilar ? accentColor : "var(--tg-theme-hint-color, #555)"}`,
                background: showSimilar ? `${accentColorAlpha}` : "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: showSimilar ? accentColor : "var(--tg-theme-text-color, #eee)",
                cursor: !track || isSimilarLoading ? "wait" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
                transition: "all 0.3s ease",
                opacity: !track ? 0.4 : 1,
              }}
            >
              {isSimilarLoading ? <IconSpinner size={18} /> : <IconSimilar size={18} />}
              Похожие
            </button>
            {/* Тренды */}
            <button
              onClick={handleTrending}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: `1px solid ${showTrending ? accentColor : "var(--tg-theme-hint-color, #555)"}`,
                background: showTrending ? `${accentColorAlpha}` : "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: showTrending ? accentColor : "var(--tg-theme-text-color, #eee)",
                cursor: isTrendingLoading ? "wait" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
                transition: "all 0.3s ease",
              }}
            >
              {isTrendingLoading ? <IconSpinner size={18} /> : <IconTrending size={18} />}
              Тренды
            </button>
            {/* Sleep */}
            <button
              onClick={() => { haptic("light"); setShowSleepMenu(!showSleepMenu); }}
              style={{
                padding: "10px 16px",
                borderRadius: 20,
                border: `1px solid ${sleepTimerRemaining ? accentColor : "var(--tg-theme-hint-color, #555)"}`,
                background: sleepTimerRemaining ? `${accentColorAlpha}` : "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: sleepTimerRemaining ? accentColor : "var(--tg-theme-text-color, #eee)",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                fontWeight: 600,
                flexShrink: 0,
                scrollSnapAlign: "start",
                transition: "all 0.3s ease",
              }}
            >
              <IconMoon size={18} />
              {sleepTimerRemaining ? `${Math.ceil(sleepTimerRemaining / 60)}м` : "Сон"}
            </button>
          </div>
          {/* Carousel fade edges */}
          <div style={{ position: "absolute", top: 0, left: 0, width: 20, height: "100%", background: "linear-gradient(90deg, var(--tg-theme-bg-color, #1a1a2e), transparent)", pointerEvents: "none" }} />
          <div style={{ position: "absolute", top: 0, right: 0, width: 20, height: "100%", background: "linear-gradient(270deg, var(--tg-theme-bg-color, #1a1a2e), transparent)", pointerEvents: "none" }} />
        </div>
      )}

      {/* Sleep Timer Menu */}
      {showSleepMenu && (
        <div style={{
          marginTop: 12,
          padding: 12,
          borderRadius: 16,
          background: "rgba(30, 30, 50, 0.9)",
          backdropFilter: "blur(16px)",
          display: "flex",
          gap: 8,
          justifyContent: "center",
          flexWrap: "wrap",
        }}>
          {[5, 15, 30, 45, 60].map((m) => (
            <button
              key={m}
              onClick={() => {
                haptic("medium");
                onSleepTimer?.(m);
                setShowSleepMenu(false);
              }}
              style={{
                padding: "6px 14px",
                borderRadius: 12,
                border: "none",
                background: "rgba(255,255,255,0.1)",
                color: "var(--tg-theme-text-color, #eee)",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              {m} мин
            </button>
          ))}
          {sleepTimerRemaining && (
            <button
              onClick={() => {
                haptic("light");
                onSleepTimer?.(null);
                setShowSleepMenu(false);
              }}
              style={{
                padding: "6px 14px",
                borderRadius: 12,
                border: "none",
                background: "rgba(255, 64, 129, 0.2)",
                color: "#ff4081",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              Отмена
            </button>
          )}
        </div>
      )}

      {/* Similar Tracks */}
      {showSimilar && similarTracks.length > 0 && (
        <div style={{
          marginTop: 14,
          padding: 14,
          borderRadius: 18,
          background: "rgba(30, 30, 50, 0.85)",
          backdropFilter: "blur(16px)",
          border: `1px solid ${accentColorAlpha}`,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accentColor, marginBottom: 10 }}>Похожие треки</div>
          <button onClick={() => handlePlayAll(similarTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${accentColor}44`, background: `linear-gradient(135deg, ${accentColorAlpha}, rgba(124,77,255,0.08))`, color: accentColor, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
          {similarTracks.map((t) => (
            <button
              key={t.video_id}
              onClick={() => { haptic("light"); onPlayTrack?.(t); }}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                background: "none", border: "none", borderBottom: "1px solid rgba(255,255,255,0.06)",
                color: "var(--tg-theme-text-color, #eee)", cursor: "pointer", textAlign: "left", fontSize: 13,
              }}
            >
              {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
              <div style={{ flex: 1, overflow: "hidden" }}>
                <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.artist}</div>
              </div>
              <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.duration_fmt}</div>
            </button>
          ))}
        </div>
      )}

      {/* AI Playlist */}
      <div style={{
        marginTop: 14,
        padding: 14,
        borderRadius: 18,
        background: "rgba(30, 30, 50, 0.7)",
        backdropFilter: "blur(16px)",
        border: `1px solid ${accentColorAlpha}`,
      }}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accentColor, marginBottom: 10 }}>AI Плейлист</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            placeholder="грустный рок на вечер..."
            value={aiPrompt}
            onInput={(e: any) => { const v = e.target.value; setAiPrompt(v); if (!v.trim()) { setShowAiPlaylist(false); setAiPlaylistTracks([]); } }}
            onKeyDown={(e: any) => { if (e.key === "Enter") handleAiPlaylist(); }}
            style={{
              flex: 1, padding: "10px 14px", borderRadius: 14,
              border: `1px solid ${accentColorAlpha}`,
              background: "rgba(124, 77, 255, 0.06)", color: "var(--tg-theme-text-color, #eee)",
              fontSize: 13, outline: "none",
            }}
          />
          <button
            onClick={handleAiPlaylist}
            disabled={isAiPlaylistLoading || !aiPrompt.trim()}
            style={{
              padding: "10px 18px", borderRadius: 14,
              border: `1px solid ${accentColor}`,
              background: `linear-gradient(135deg, ${accentColorAlpha}, transparent)`,
              color: accentColor, cursor: isAiPlaylistLoading ? "wait" : "pointer",
              fontSize: 13, fontWeight: 700, opacity: isAiPlaylistLoading || !aiPrompt.trim() ? 0.5 : 1,
            }}
          >
            {isAiPlaylistLoading ? "..." : "Go"}
          </button>
        </div>
        {showAiPlaylist && aiPlaylistTracks.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <button onClick={() => handlePlayAll(aiPlaylistTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${accentColor}44`, background: `linear-gradient(135deg, ${accentColorAlpha}, rgba(124,77,255,0.08))`, color: accentColor, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
            {aiPlaylistTracks.map((t) => (
              <button
                key={t.video_id}
                onClick={() => { haptic("light"); onPlayTrack?.(t); }}
                style={{
                  display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                  background: "none", border: "none", borderBottom: "1px solid rgba(255,255,255,0.06)",
                  color: "var(--tg-theme-text-color, #eee)", cursor: "pointer", textAlign: "left", fontSize: 13,
                }}
              >
                {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
                <div style={{ flex: 1, overflow: "hidden" }}>
                  <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.artist}</div>
                </div>
                <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.duration_fmt}</div>
              </button>
            ))}
          </div>
        )}
        {showAiPlaylist && aiPlaylistTracks.length === 0 && !isAiPlaylistLoading && (
          <div style={{ marginTop: 10, textAlign: "center", color: "var(--tg-theme-hint-color, #888)", fontSize: 12 }}>Ничего не найдено</div>
        )}
      </div>

      {/* Trending */}
      {showTrending && trendingTracks.length > 0 && (
        <div style={{
          marginTop: 14,
          padding: 14,
          borderRadius: 18,
          background: "rgba(30, 30, 50, 0.85)",
          backdropFilter: "blur(16px)",
          border: `1px solid ${accentColorAlpha}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accentColor, display: "flex", alignItems: "center", gap: 4 }}><IconFire size={14} /> Тренды</div>
            <button
              onClick={() => setShowTrending(false)}
              style={{
                padding: "5px 10px",
                borderRadius: 12,
                border: `1px solid ${accentColor}66`,
                background: `linear-gradient(135deg, ${accentColorAlpha}, rgba(124,77,255,0.08))`,
                color: accentColor,
                cursor: "pointer",
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              Скрыть
            </button>
          </div>
          <button onClick={() => handlePlayAll(trendingTracks)} style={{ marginBottom: 8, padding: "6px 14px", borderRadius: 14, border: `1px solid ${accentColor}44`, background: `linear-gradient(135deg, ${accentColorAlpha}, rgba(124,77,255,0.08))`, color: accentColor, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>▶ Играть все</button>
          {trendingTracks.map((t, i) => (
            <button
              key={t.video_id}
              onClick={() => { haptic("light"); onPlayTrack?.(t); }}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 6px",
                background: "none", border: "none", borderBottom: "1px solid rgba(255,255,255,0.06)",
                color: "var(--tg-theme-text-color, #eee)", cursor: "pointer", textAlign: "left", fontSize: 13,
              }}
            >
              <span style={{ fontSize: 14, fontWeight: 700, color: accentColor, minWidth: 20 }}>{i + 1}</span>
              {t.cover_url && <img src={t.cover_url} style={{ width: 36, height: 36, borderRadius: 8, objectFit: "cover" }} />}
              <div style={{ flex: 1, overflow: "hidden" }}>
                <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.artist}</div>
              </div>
              <div style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #888)" }}>{t.duration_fmt}</div>
            </button>
          ))}
        </div>
      )}

      {audioControlsPanel(false)}
      {luxuryPanel(false)}

      {/* Share Card Modal */}
      {showShareCard && track && (
        <ShareCard
          track={track}
          onClose={() => setShowShareCard(false)}
          accentColor={accentColor}
          themeId={themeId}
        />
      )}
    </div>
  );
}
