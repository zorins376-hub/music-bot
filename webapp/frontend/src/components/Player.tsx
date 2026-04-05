import { useState, useEffect, useRef } from "preact/hooks";
import { memo } from "preact/compat";
import type { EqPreset, PlayerState } from "../api";
import { toggleFavorite, checkFavorite, sendFeedback, ingestEvent, fetchSimilar, generateAiPlaylist, fetchTrending, searchTracks, type Track } from "../api";
import { ShareCard } from "./ShareCard";
import { IconEqualizer, IconMusic, IconMusicNote, IconSpectrum, IconSpatial, IconSpeed, IconBassBoost, IconParty, IconMood, IconMic, IconHiRes, IconMoodChill, IconMoodEnergy, IconMoodFocus, IconMoodRomance, IconMoodMelancholy, IconMoodParty, IconPlus, IconShare, IconImage, IconWave, IconSimilar, IconTrending, IconMoon, IconSpinner, IconFire } from "./Icons";
import { haptic, IconPlay, IconPause, IconSkipForward, IconSkipBack, IconShuffle, IconRepeat, IconLyrics, IconHeart, AudioVisualizer, Marquee, AudioBadge, btnStyle, QUALITY_OPTIONS, EQ_OPTIONS, formatEqPresetLabel, WaveformSeek, MusicParticles } from "./PlayerHelpers";
import { EQPanel } from "./EQPanel";
import { LuxuryPanel } from "./LuxuryPanel";

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
  nightMode?: boolean;
  onNightMode?: (on: boolean) => void;
  reverbEnabled?: boolean;
  onReverb?: (on: boolean) => void;
  reverbPreset?: "studio" | "concert" | "club" | "cathedral";
  onReverbPreset?: (preset: "studio" | "concert" | "club" | "cathedral") => void;
  reverbMix?: number;
  onReverbMix?: (mix: number) => void;
  karaokeMode?: boolean;
  onKaraokeMode?: (on: boolean) => void;
  crossfadeDuration?: number;
  onCrossfadeDuration?: (sec: number) => void;
  coverMode?: "default" | "vinyl" | "cd" | "case";
  onCoverMode?: (mode: "default" | "vinyl" | "cd" | "case") => void;
  onAddToPlaylist?: () => void;
  onAddToQueue?: (track: Track) => void;
  onPlayTrack?: (track: Track) => void;
  onPlayAll?: (tracks: Track[]) => void;
  onBgColorsChange?: (colors: [string, string, string]) => void;
}

export const Player = memo(function Player({ state, onAction, onShowLyrics, accentColor = "rgb(124, 77, 255)", accentColorAlpha = "rgba(124, 77, 255, 0.4)", onSleepTimer, sleepTimerRemaining, audioDuration = 0, onWave, isWaveLoading = false, elapsed: externalElapsed = 0, buffering = false, themeId = "blackroom", isPremium = false, isAdmin = false, canUseAudioControls = false, quality = "192", eqPreset = "flat", onQualityChange, onEqPresetChange, bassBoost = false, onBassBoost, partyMode = false, onPartyMode, playbackSpeed = 1, onSpeedChange, panValue = 0, onPanChange, showSpectrum = false, onToggleSpectrum, spectrumStyle = "bars", onSpectrumStyleChange, moodFilter = null, onMoodChange, bypassProcessing = false, onBypassToggle, tapeWarmth = false, onTapeWarmth, airBand = false, onAirBand, stereoWiden = false, onStereoWiden, softClip = false, onSoftClip, nightMode = false, onNightMode, reverbEnabled = false, onReverb, reverbPreset = "studio", onReverbPreset, reverbMix = 0.3, onReverbMix, karaokeMode = false, onKaraokeMode, crossfadeDuration = 0, onCrossfadeDuration, coverMode = "vinyl", onCoverMode, onAddToPlaylist, onAddToQueue, onPlayTrack, onPlayAll, onBgColorsChange }: Props) {
  const qualityLabel = quality === "auto" ? "Auto" : `${quality} kbps`;
  const isTequila = themeId === "tequila";
  const vinylSpin = coverMode === "vinyl";
  const cdMode = coverMode === "cd";
  const caseMode = coverMode === "case";
  const isDiscSpin = vinylSpin || cdMode; // modes where disc rotates
  const isRound = vinylSpin || cdMode; // modes where cover is circular
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
  const [showSettings, setShowSettings] = useState(false);

  // ── Animated gradient background from cover art colors ──
  const [bgColors, setBgColors] = useState<[string, string, string]>(["#1a1a2e", "#0a0a1e", "#1a1a2e"]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!track?.cover_url) {
      setBgColors(isTequila ? ["#2d1a0a", "#1a0f04", "#2d1a0a"] : ["#1a1a2e", "#0a0a1e", "#1a1a2e"]);
      return;
    }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const c = canvasRef.current || document.createElement("canvas");
        canvasRef.current = c;
        c.width = 16;
        c.height = 16;
        const ctx = c.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, 16, 16);
        const d = ctx.getImageData(0, 0, 16, 16).data;
        const px = (x: number, y: number) => {
          const i = (y * 16 + x) * 4;
          return [d[i], d[i + 1], d[i + 2]] as [number, number, number];
        };
        // Sample corners + center, darken for background
        const samples = [px(2, 2), px(13, 2), px(2, 13), px(13, 13), px(8, 8)];
        const darken = (rgb: [number, number, number], f: number) =>
          `rgb(${Math.round(rgb[0] * f)}, ${Math.round(rgb[1] * f)}, ${Math.round(rgb[2] * f)})`;
        setBgColors([darken(samples[0], 0.25), darken(samples[4], 0.15), darken(samples[3], 0.25)]);
      } catch {
        // CORS or canvas error — keep defaults
      }
    };
    img.src = track.cover_url;
  }, [track?.cover_url, isTequila]);

  // Notify parent about background colors
  useEffect(() => { onBgColorsChange?.(bgColors); }, [bgColors, onBgColorsChange]);

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

  // ── Double-tap ±15s seek ──
  const lastTapTime = useRef<number>(0);
  const lastTapX = useRef<number>(0);
  const [doubleTapIndicator, setDoubleTapIndicator] = useState<"left" | "right" | null>(null);

  const handleCoverDoubleTap = (e: MouseEvent | TouchEvent) => {
    if (!track || !duration) return;
    const now = Date.now();
    const clientX = "touches" in e ? e.changedTouches[0].clientX : e.clientX;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const isLeft = clientX < rect.left + rect.width / 2;

    if (now - lastTapTime.current < 300 && Math.abs(clientX - lastTapX.current) < 60) {
      // Double tap detected
      const seekDelta = isLeft ? -15 : 15;
      const newPos = Math.max(0, Math.min(duration, elapsed + seekDelta));
      haptic("medium");
      onAction("seek", track.video_id, newPos);
      setDoubleTapIndicator(isLeft ? "left" : "right");
      setTimeout(() => setDoubleTapIndicator(null), 600);
      lastTapTime.current = 0;
    } else {
      lastTapTime.current = now;
      lastTapX.current = clientX;
    }
  };

  // Reset seek value on track change
  useEffect(() => { setSeekValue(null); }, [track?.video_id]);

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? "0" : ""}${sec}`;
  };

  const audioControlsPanel = (warm = false) => canUseAudioControls ? (
    <EQPanel
      quality={quality} eqPreset={eqPreset} bypassProcessing={bypassProcessing}
      accentColor={accentColor} accentColorAlpha={accentColorAlpha}
      warm={warm} isAdmin={isAdmin}
      onQualityChange={onQualityChange} onEqPresetChange={onEqPresetChange}
      onBypassToggle={onBypassToggle}
    />
  ) : null;

  const luxuryPanel = (warm: boolean) => (
    <LuxuryPanel
      warm={warm} accentColor={accentColor}
      showSpectrum={showSpectrum} onToggleSpectrum={onToggleSpectrum}
      bassBoost={bassBoost} onBassBoost={onBassBoost}
      partyMode={partyMode} onPartyMode={onPartyMode}
      tapeWarmth={tapeWarmth} onTapeWarmth={onTapeWarmth}
      airBand={airBand} onAirBand={onAirBand}
      stereoWiden={stereoWiden} onStereoWiden={onStereoWiden}
      softClip={softClip} onSoftClip={onSoftClip}
      nightMode={nightMode} onNightMode={onNightMode}
      reverbEnabled={reverbEnabled} onReverb={onReverb}
      reverbPreset={reverbPreset} onReverbPreset={onReverbPreset}
      reverbMix={reverbMix} onReverbMix={onReverbMix}
      karaokeMode={karaokeMode} onKaraokeMode={onKaraokeMode}
      crossfadeDuration={crossfadeDuration} onCrossfadeDuration={onCrossfadeDuration}
      coverMode={coverMode} onCoverMode={onCoverMode}
      panValue={panValue} onPanChange={onPanChange}
      playbackSpeed={playbackSpeed} onSpeedChange={onSpeedChange}
      moodFilter={moodFilter} onMoodChange={onMoodChange}
      quality={quality}
    />
  );

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
      <div style={{ textAlign: "center", padding: "8px 0", position: "relative" }}>
        <style>{`
          @keyframes bgShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          @keyframes dtFade {
            0% { opacity: 1; transform: translateY(-50%) scale(1); }
            100% { opacity: 0; transform: translateY(-50%) scale(1.3); }
          }
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
        {/* ── Cover Area ── */}
        <div onClick={handleCoverDoubleTap} style={{ position: "relative", width: 340, margin: "0 auto 20px", cursor: "pointer", perspective: 800 }}>
          {/* Double-tap indicator */}
          {doubleTapIndicator && (
            <div style={{
              position: "absolute", top: "50%", [doubleTapIndicator === "left" ? "left" : "right"]: 20,
              transform: "translateY(-50%)", zIndex: 20, pointerEvents: "none",
              animation: "dtFade 0.6s ease forwards",
            }}>
              <div style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)", borderRadius: 16, padding: "8px 14px", color: "#fff", fontSize: 16, fontWeight: 700 }}>
                {doubleTapIndicator === "left" ? "−15s" : "+15s"}
              </div>
            </div>
          )}
          {/* Tonearm — vinyl mode only */}
          {vinylSpin && (
            <svg viewBox="0 0 60 130" style={{
              position: "absolute", top: -16, right: 2, width: 52, height: 112, zIndex: 12, pointerEvents: "none",
              transformOrigin: "48px 10px",
              transform: state.is_playing && track ? "rotate(24deg)" : "rotate(0deg)",
              transition: "transform 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)",
              filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.5))",
            }}>
              <circle cx="54" cy="3" r="5" fill="#555" stroke="#777" strokeWidth="0.5" />
              <circle cx="48" cy="10" r="6.5" fill="#4a3a2a" stroke={borderGold} strokeWidth="0.8" />
              <circle cx="48" cy="10" r="2.5" fill="#2a1a0a" />
              <line x1="48" y1="16" x2="12" y2="108" stroke="url(#tq-arm-grad)" strokeWidth="2.8" strokeLinecap="round" />
              <line x1="12" y1="108" x2="6" y2="122" stroke="#bba070" strokeWidth="3.5" strokeLinecap="round" />
              <rect x="1" y="120" width="12" height="5" rx="1.5" fill="#998060" stroke={borderGold} strokeWidth="0.5" />
              <line x1="7" y1="125" x2="7" y2="129" stroke="#d4b878" strokeWidth="1.2" />
              <defs><linearGradient id="tq-arm-grad" x1="48" y1="16" x2="12" y2="108" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="#aa9070" /><stop offset="100%" stopColor="#887050" />
              </linearGradient></defs>
            </svg>
          )}

          {/* Case mode — jewel case wrapper */}
          {caseMode && track && (
            <div style={{
              position: "absolute", inset: -6, borderRadius: 20,
              background: "linear-gradient(145deg, rgba(255,213,79,0.06), rgba(255,167,38,0.03))",
              border: `1.5px solid ${borderGold}`,
              boxShadow: `0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,213,79,0.1)`,
              zIndex: 0, pointerEvents: "none",
            }} />
          )}

          {/* Disc */}
          <div
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
            style={{
              position: "relative",
              width: 320, height: 320, margin: "0 auto",
              borderRadius: isRound ? "50%" : 24,
              background: track
                ? `linear-gradient(135deg, rgba(255,167,38,0.15), rgba(255,213,79,0.08))`
                : "linear-gradient(135deg, #ff6d00 0%, #ffd54f 100%)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: track
                ? (isRound
                  ? `0 12px 40px rgba(255,109,0,0.25), 0 0 0 2px ${borderGold}, 0 0 0 4px rgba(26,18,11,0.8), 0 0 0 5px ${borderGold}`
                  : `0 12px 40px rgba(255,109,0,0.25), 0 0 0 1px ${borderGold}, inset 0 0 0 1px rgba(255,213,79,0.1)`)
                : "0 8px 24px rgba(255,109,0,0.3)",
              animation: isDiscSpin && state.is_playing && track ? `vinylSpin ${cdMode ? "6s" : "4s"} linear infinite` : (state.is_playing && coverMode === "default" ? "tequilaGlow 3.6s ease-in-out infinite" : "none"),
              overflow: "hidden",
              transition: swipeOffset === 0 ? "transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)" : "none",
              transform: `translate3d(${swipeOffset}px, 0, 0) scale(${state.is_playing && !isRound ? 1.03 : 1}) rotateX(${state.is_playing ? 4 : 0}deg)`,
              transformStyle: "preserve-3d",
              willChange: "transform", touchAction: "pan-y", userSelect: "none",
            }}
          >
            {/* Cover image */}
            {track?.cover_url ? (
              <img src={track.cover_url} alt="Cover"
                style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none", borderRadius: isRound ? "50%" : 0 }}
                draggable={false} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            ) : (
              track ? <IconMusic size={64} color="rgba(255,245,220,0.8)" /> : <IconMusicNote size={48} color="rgba(255,245,220,0.5)" />
            )}

            {/* Vinyl grooves */}
            {vinylSpin && track && (
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "repeating-radial-gradient(circle, transparent 0px, transparent 3px, rgba(0,0,0,0.06) 3.5px, transparent 4px)", pointerEvents: "none", zIndex: 1 }} />
            )}

            {/* CD rainbow reflection */}
            {cdMode && track && (
              <div style={{
                position: "absolute", inset: 0, borderRadius: "50%", pointerEvents: "none", zIndex: 1,
                background: `conic-gradient(from 0deg, transparent 0deg, rgba(255,50,50,0.06) 30deg, rgba(255,255,50,0.08) 60deg, rgba(50,255,50,0.06) 90deg, rgba(50,255,255,0.08) 120deg, rgba(50,50,255,0.06) 150deg, rgba(255,50,255,0.08) 180deg, transparent 210deg, rgba(255,50,50,0.06) 240deg, rgba(255,255,50,0.08) 270deg, rgba(50,255,50,0.06) 300deg, rgba(50,50,255,0.08) 330deg, transparent 360deg)`,
              }} />
            )}

            {/* Case mode — static disc overlay */}
            {caseMode && track && (
              <div style={{
                position: "absolute", width: 240, height: 240, borderRadius: "50%",
                border: `2px solid ${borderGold}`,
                boxShadow: "0 4px 20px rgba(0,0,0,0.4), inset 0 0 30px rgba(0,0,0,0.3)",
                overflow: "hidden", zIndex: 2,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {track.cover_url && (
                  <img src={track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%", opacity: 0.85 }} draggable={false} />
                )}
                {/* CD hole */}
                <div style={{
                  position: "absolute", width: 32, height: 32, borderRadius: "50%",
                  background: "radial-gradient(circle, rgba(26,18,11,0.95) 40%, transparent 100%)",
                  border: `1.5px solid ${borderGold}`, boxShadow: "0 0 8px rgba(0,0,0,0.6)",
                }} />
                {/* Rainbow sheen */}
                <div style={{
                  position: "absolute", inset: 0, borderRadius: "50%", pointerEvents: "none",
                  background: `conic-gradient(from 45deg, transparent 0deg, rgba(255,200,50,0.06) 90deg, rgba(200,50,255,0.04) 180deg, rgba(50,200,255,0.06) 270deg, transparent 360deg)`,
                }} />
              </div>
            )}

            {/* Vinyl center label */}
            {vinylSpin && track && (
              <div style={{
                position: "absolute", width: 100, height: 100, borderRadius: "50%",
                background: "radial-gradient(circle at 35% 35%, #2a1f10, #1a120b 70%)",
                border: `1.5px solid ${borderGold}`,
                boxShadow: "0 0 16px rgba(0,0,0,0.7), inset 0 1px 3px rgba(255,213,79,0.15)",
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                zIndex: 3, padding: "6px 8px", overflow: "hidden",
              }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#0a0806", border: `1px solid ${borderGold}`, marginBottom: 3, flexShrink: 0 }} />
                <div style={{ fontSize: 7, color: "#c8a882", textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.2, letterSpacing: "0.04em", textTransform: "uppercase" }}>{track.artist}</div>
                <div style={{ fontSize: "clamp(6.5px, 2vw, 8.5px)", color: "#fef0e0", fontWeight: 700, textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.2, marginTop: 1 }}>{track.title}</div>
                <div style={{ fontSize: 6, color: "rgba(200,168,130,0.5)", marginTop: 2, letterSpacing: "0.08em" }}>{track.duration_fmt}</div>
              </div>
            )}

            {/* CD center hole */}
            {cdMode && track && (
              <div style={{
                position: "absolute", width: 34, height: 34, borderRadius: "50%",
                background: "radial-gradient(circle, #1a120b 35%, rgba(26,18,11,0.9) 60%, transparent 100%)",
                border: `2px solid ${borderGold}`, boxShadow: "0 0 12px rgba(0,0,0,0.6)", zIndex: 2,
              }} />
            )}

            {/* Warm visualizer */}
            {track && <AudioVisualizer isPlaying={state.is_playing} accentColor="#ff6d00" />}
            {/* Border overlay */}
            <div style={{ position: "absolute", inset: 0, borderRadius: isRound ? "50%" : 24, border: `1.5px solid ${borderGold}`, pointerEvents: "none" }} />
            {/* Shimmer — default/case only */}
            {state.is_playing && !isDiscSpin && (
              <div style={{ position: "absolute", top: -20, left: -60, width: 120, height: 320, background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,244,200,0.26), rgba(255,255,255,0))", transform: "rotate(18deg)", animation: "tequilaShimmer 2.8s ease-in-out infinite", pointerEvents: "none" }} />
            )}
          </div>

          {/* Progress ring */}
          {track && duration > 0 && (
            <svg style={{
              position: "absolute", top: "50%", left: "50%",
              width: 338, height: 338,
              transform: "translate(-50%, -50%)",
              pointerEvents: "none", zIndex: 10,
            }} viewBox="0 0 338 338">
              <circle cx="169" cy="169" r="166" fill="none" stroke="rgba(255,167,38,0.12)" strokeWidth="2.5" />
              <circle cx="169" cy="169" r="166" fill="none" stroke="#ffa726" strokeWidth="2.5"
                strokeDasharray={2 * Math.PI * 166}
                strokeDashoffset={2 * Math.PI * 166 * (1 - elapsed / duration)}
                strokeLinecap="round"
                transform="rotate(-90 169 169)"
                style={{ transition: "stroke-dashoffset 0.5s linear" }}
              />
            </svg>
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

        {/* Seek slider — warm waveform */}
        {track && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: "#c8a882", minWidth: 36, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
              {fmtTime(elapsed)}
            </span>
            <div style={{ flex: 1, touchAction: "none" }}>
              <WaveformSeek elapsed={elapsed} duration={duration} accentColor="#ffa726" onSeek={(pos) => { haptic("light"); onAction("seek", track.video_id, pos); }} />
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
          <button style={tqBtn} onClick={() => { haptic("light"); onAction("shuffle"); }} aria-label={state.shuffle ? "Disable shuffle" : "Enable shuffle"}>
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
            aria-label="Previous track"
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
              width: 80,
              height: 80,
              boxShadow: `0 6px 24px rgba(255, 109, 0, 0.45), 0 0 0 3px rgba(255, 213, 79, 0.15)`,
              transition: "all 0.4s ease",
              position: "relative",
              border: "none",
              animation: state.is_playing && !buffering ? "tequilaPulse 2.6s ease-in-out infinite" : "none",
            }}
            onClick={() => { haptic("heavy"); onAction(state.is_playing ? "pause" : "play"); }}
            aria-label={state.is_playing ? "Pause" : "Play"}
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
            aria-label="Next track"
          >
            <IconSkipForward />
          </button>
          <button style={tqBtn} onClick={() => { haptic("light"); onAction("repeat"); }} aria-label={`Repeat: ${state.repeat_mode || "off"}`}>
            <IconRepeat mode={state.repeat_mode} activeColor={gold} />
          </button>
        </div>

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
              {/* Настройки */}
              <button
                onClick={() => { haptic("light"); setShowSettings(!showSettings); }}
                style={{
                  padding: "10px 18px",
                  borderRadius: 24,
                  border: showSettings ? `1px solid ${gold}88` : `1px solid ${borderGold}`,
                  background: showSettings ? "rgba(255,167,38,0.18)" : glassCard,
                  backdropFilter: "blur(12px)",
                  color: showSettings ? gold : "#fef0e0",
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
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                Настройки
              </button>
            </div>
            {/* Carousel fade edges — warm */}
            <div style={{ position: "absolute", top: 0, left: 0, width: 20, height: "100%", background: "linear-gradient(90deg, rgba(28, 18, 12, 1), transparent)", pointerEvents: "none" }} />
            <div style={{ position: "absolute", top: 0, right: 0, width: 20, height: "100%", background: "linear-gradient(270deg, rgba(28, 18, 12, 1), transparent)", pointerEvents: "none" }} />
          </div>
        )}

        {/* ── Settings Panel (tequila) ── */}
        {showSettings && (
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 0, animation: "fadeSlideIn 0.25s ease" }}>

        {/* Quick Actions Row */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginBottom: 12 }}>
          <button onClick={() => { haptic("medium"); onWave?.(); }} disabled={isWaveLoading} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${borderGold}`, background: "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))", color: gold, cursor: isWaveLoading ? "wait" : "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6, opacity: isWaveLoading ? 0.6 : 1 }}>
            {isWaveLoading ? <IconSpinner size={14} color={gold} /> : <IconWave size={14} />} Волна
          </button>
          <button onClick={handleSimilar} disabled={!track || isSimilarLoading} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${showSimilar ? gold + "88" : borderGold}`, background: showSimilar ? "rgba(255,167,38,0.18)" : glassCard, color: showSimilar ? gold : "#fef0e0", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
            {isSimilarLoading ? <IconSpinner size={14} /> : <IconSimilar size={14} />} Похожие
          </button>
          <button onClick={handleTrending} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${showTrending ? gold + "88" : borderGold}`, background: showTrending ? "rgba(255,167,38,0.18)" : glassCard, color: showTrending ? gold : "#fef0e0", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
            {isTrendingLoading ? <IconSpinner size={14} /> : <IconTrending size={14} />} Тренды
          </button>
          <button onClick={() => { haptic("light"); setShowSleepMenu(!showSleepMenu); }} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${sleepTimerRemaining ? gold + "88" : borderGold}`, background: sleepTimerRemaining ? "rgba(255,167,38,0.18)" : glassCard, color: sleepTimerRemaining ? gold : "#fef0e0", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
            <IconMoon size={14} /> {sleepTimerRemaining ? `${Math.ceil(sleepTimerRemaining / 60)}м` : "Сон"}
          </button>
          {track && (
            <button onClick={() => { haptic("light"); if (track) onAddToQueue?.(track); }} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${borderGold}`, background: glassCard, color: "#fef0e0", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
              <IconPlus size={14} /> В очередь
            </button>
          )}
          {track && (
            <button onClick={() => { haptic("light"); onAddToPlaylist?.(); }} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${borderGold}`, background: glassCard, color: "#fef0e0", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
              <IconMusic size={14} /> В плейлист
            </button>
          )}
        </div>

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
              onInput={(e) => { const v = (e.target as HTMLInputElement).value; setAiPrompt(v); if (!v.trim()) { setShowAiPlaylist(false); setAiPlaylistTracks([]); } }}
              onKeyDown={(e) => { if (e.key === "Enter") handleAiPlaylist(); }}
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
                onClick={() => { haptic("medium"); onSleepTimer?.(m); setShowSleepMenu(false); }}
                style={{ padding: "7px 16px", borderRadius: 14, border: `1px solid ${borderGold}`, background: "rgba(255,213,79,0.08)", color: "#fef0e0", fontSize: 13, cursor: "pointer" }}
              >
                {m} мин
              </button>
            ))}
            {sleepTimerRemaining && (
              <button
                onClick={() => { haptic("light"); onSleepTimer?.(null); setShowSleepMenu(false); }}
                style={{ padding: "7px 16px", borderRadius: 14, border: "1px solid rgba(255, 109, 0, 0.4)", background: "rgba(255, 109, 0, 0.15)", color: "#ff6d00", fontSize: 13, cursor: "pointer" }}
              >
                Отмена
              </button>
            )}
          </div>
        )}

        </div>
        )}
        {/* end showSettings tequila */}

        <style>{`
          @keyframes partyPulse {
            0% { box-shadow: 0 0 8px rgba(255, 109, 0, 0.3); }
            50% { box-shadow: 0 0 20px rgba(224, 64, 251, 0.5); }
            100% { box-shadow: 0 0 8px rgba(255, 109, 0, 0.3); }
          }
        `}</style>

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
    <div style={{ textAlign: "center", padding: "16px 0", position: "relative" }}>
      <style>{`
        @keyframes bgShift {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes dtFade {
          0% { opacity: 1; transform: translateY(-50%) scale(1); }
          100% { opacity: 0; transform: translateY(-50%) scale(1.3); }
        }
        @keyframes vinylSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      {/* ── Cover Area ── */}
      <div onClick={handleCoverDoubleTap} style={{ position: "relative", width: 320, margin: "0 auto 24px", cursor: "pointer", perspective: 800 }}>
        {/* Double-tap indicator */}
        {doubleTapIndicator && (
          <div style={{
            position: "absolute", top: "50%", [doubleTapIndicator === "left" ? "left" : "right"]: 20,
            transform: "translateY(-50%)", zIndex: 20, pointerEvents: "none",
            animation: "dtFade 0.6s ease forwards",
          }}>
            <div style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)", borderRadius: 16, padding: "8px 14px", color: "#fff", fontSize: 16, fontWeight: 700 }}>
              {doubleTapIndicator === "left" ? "−15s" : "+15s"}
            </div>
          </div>
        )}
        {/* Tonearm — vinyl only */}
        {vinylSpin && (
          <svg viewBox="0 0 60 130" style={{
            position: "absolute", top: -14, right: 4, width: 48, height: 106, zIndex: 12, pointerEvents: "none",
            transformOrigin: "48px 10px",
            transform: state.is_playing && track ? "rotate(24deg)" : "rotate(0deg)",
            transition: "transform 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)",
            filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.6))",
          }}>
            <circle cx="54" cy="3" r="5" fill="#444" stroke="#666" strokeWidth="0.5" />
            <circle cx="48" cy="10" r="6.5" fill="#2a2a3e" stroke={accentColor} strokeWidth="0.8" />
            <circle cx="48" cy="10" r="2.5" fill="#1a1a2e" />
            <line x1="48" y1="16" x2="12" y2="108" stroke="url(#df-arm-grad)" strokeWidth="2.8" strokeLinecap="round" />
            <line x1="12" y1="108" x2="6" y2="122" stroke="#aaa" strokeWidth="3.5" strokeLinecap="round" />
            <rect x="1" y="120" width="12" height="5" rx="1.5" fill="#888" stroke={accentColor} strokeWidth="0.5" />
            <line x1="7" y1="125" x2="7" y2="129" stroke="#ccc" strokeWidth="1.2" />
            <defs><linearGradient id="df-arm-grad" x1="48" y1="16" x2="12" y2="108" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#999" /><stop offset="100%" stopColor="#666" />
            </linearGradient></defs>
          </svg>
        )}

        {/* Case — jewel case wrapper */}
        {caseMode && track && (
          <div style={{
            position: "absolute", inset: -6, borderRadius: 18,
            background: "linear-gradient(145deg, rgba(124,77,255,0.06), rgba(224,64,251,0.03))",
            border: `1.5px solid ${accentColorAlpha}`,
            boxShadow: `0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05)`,
            zIndex: 0, pointerEvents: "none",
          }} />
        )}

        {/* Disc */}
        <div
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          style={{
            position: "relative", width: 300, height: 300, margin: "0 auto",
            borderRadius: isRound ? "50%" : 20,
            background: track ? "var(--tg-theme-secondary-bg-color, #2a2a3e)" : `linear-gradient(135deg, ${accentColor} 0%, ${accentColorAlpha} 100%)`,
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 64,
            boxShadow: track ? (isRound ? `0 8px 24px rgba(0,0,0,0.4), 0 0 0 2px ${accentColor}, 0 0 0 4px rgba(26,26,46,0.8), 0 0 0 5px ${accentColorAlpha}` : "0 8px 24px rgba(0,0,0,0.3)") : "none",
            overflow: "hidden",
            transition: swipeOffset === 0 ? "transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)" : "none",
            transform: `translate3d(${swipeOffset}px, 0, 0) scale(${state.is_playing && !isRound ? 1.02 : 1}) rotateX(${state.is_playing ? 4 : 0}deg)`,
            transformStyle: "preserve-3d",
            animation: isDiscSpin && state.is_playing && track ? `vinylSpin ${cdMode ? "6s" : "4s"} linear infinite` : "none",
            willChange: "transform", touchAction: "pan-y", userSelect: "none",
          }}
        >
          {track?.cover_url ? (
            <img src={track.cover_url} alt="Cover"
              style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none", borderRadius: isRound ? "50%" : 0 }}
              draggable={false} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          ) : (
            track ? <IconMusic size={64} color="rgba(255,255,255,0.8)" /> : <IconMusicNote size={48} color="rgba(255,255,255,0.5)" />
          )}

          {/* Vinyl grooves */}
          {vinylSpin && track && (
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "repeating-radial-gradient(circle, transparent 0px, transparent 3px, rgba(0,0,0,0.07) 3.5px, transparent 4px)", pointerEvents: "none", zIndex: 1 }} />
          )}

          {/* CD rainbow reflection */}
          {cdMode && track && (
            <div style={{
              position: "absolute", inset: 0, borderRadius: "50%", pointerEvents: "none", zIndex: 1,
              background: `conic-gradient(from 0deg, transparent 0deg, rgba(255,50,50,0.07) 30deg, rgba(255,255,50,0.09) 60deg, rgba(50,255,50,0.07) 90deg, rgba(50,255,255,0.09) 120deg, rgba(50,50,255,0.07) 150deg, rgba(255,50,255,0.09) 180deg, transparent 210deg, rgba(255,50,50,0.07) 240deg, rgba(255,255,50,0.09) 270deg, rgba(50,255,50,0.07) 300deg, rgba(50,50,255,0.09) 330deg, transparent 360deg)`,
            }} />
          )}

          {/* Case — static disc overlay */}
          {caseMode && track && (
            <div style={{
              position: "absolute", width: 230, height: 230, borderRadius: "50%",
              border: `2px solid ${accentColorAlpha}`,
              boxShadow: "0 4px 20px rgba(0,0,0,0.4), inset 0 0 30px rgba(0,0,0,0.3)",
              overflow: "hidden", zIndex: 2, display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              {track.cover_url && <img src={track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%", opacity: 0.85 }} draggable={false} />}
              <div style={{ position: "absolute", width: 28, height: 28, borderRadius: "50%", background: "radial-gradient(circle, #1a1a2e 35%, transparent 100%)", border: `1.5px solid ${accentColor}`, boxShadow: "0 0 8px rgba(0,0,0,0.6)" }} />
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", pointerEvents: "none", background: `conic-gradient(from 45deg, transparent 0deg, rgba(124,77,255,0.06) 90deg, rgba(224,64,251,0.04) 180deg, rgba(50,200,255,0.06) 270deg, transparent 360deg)` }} />
            </div>
          )}

          {/* Vinyl center label */}
          {vinylSpin && track && (
            <div style={{
              position: "absolute", width: 94, height: 94, borderRadius: "50%",
              background: "radial-gradient(circle at 35% 35%, #2a2a3e, #1a1a2e 70%)",
              border: `1.5px solid ${accentColor}`, boxShadow: `0 0 16px rgba(0,0,0,0.7), inset 0 1px 3px ${accentColorAlpha}`,
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              zIndex: 3, padding: "6px 8px", overflow: "hidden",
            }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#0a0a1e", border: `1px solid ${accentColor}`, marginBottom: 3, flexShrink: 0 }} />
              <div style={{ fontSize: 7, color: "var(--tg-theme-hint-color, #aaa)", textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.2, letterSpacing: "0.04em", textTransform: "uppercase" }}>{track.artist}</div>
              <div style={{ fontSize: "clamp(6.5px, 2vw, 8.5px)", color: "#fff", fontWeight: 700, textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.2, marginTop: 1 }}>{track.title}</div>
              <div style={{ fontSize: 6, color: "var(--tg-theme-hint-color, rgba(170,170,170,0.5))", marginTop: 2, letterSpacing: "0.08em" }}>{track.duration_fmt}</div>
            </div>
          )}

          {/* CD center hole */}
          {cdMode && track && (
            <div style={{ position: "absolute", width: 32, height: 32, borderRadius: "50%", background: "radial-gradient(circle, #1a1a2e 35%, rgba(26,26,46,0.9) 60%, transparent 100%)", border: `2px solid ${accentColor}`, boxShadow: "0 0 12px rgba(0,0,0,0.6)", zIndex: 2 }} />
          )}

          {/* Audio Visualizer */}
          {track && <AudioVisualizer isPlaying={state.is_playing} accentColor={accentColor} />}
        </div>

        {/* Progress ring */}
        {track && duration > 0 && (
          <svg style={{
            position: "absolute", top: "50%", left: "50%",
            width: 318, height: 318,
            transform: "translate(-50%, -50%)",
            pointerEvents: "none", zIndex: 10,
          }} viewBox="0 0 318 318">
            <circle cx="159" cy="159" r="156" fill="none" stroke={`${accentColorAlpha}`} strokeWidth="2.5" />
            <circle cx="159" cy="159" r="156" fill="none" stroke={accentColor} strokeWidth="2.5"
              strokeDasharray={2 * Math.PI * 156}
              strokeDashoffset={2 * Math.PI * 156 * (1 - elapsed / duration)}
              strokeLinecap="round"
              transform="rotate(-90 159 159)"
              style={{ transition: "stroke-dashoffset 0.5s linear" }}
            />
          </svg>
        )}
      </div>

      {/* Glass info card */}
      <div style={{
        margin: "0 16px 16px",
        padding: "14px 20px",
        borderRadius: 20,
        background: "rgba(255,255,255,0.06)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        border: `1px solid ${accentColorAlpha}`,
      }}>
        <Marquee
          text={track?.title ?? "Ничего не играет"}
          style={{ fontSize: 18, fontWeight: 600 }}
        />
        <Marquee
          text={track ? `${track.artist}  ·  ${track.duration_fmt}  ·  ${qualityLabel}` : "—"}
          style={{ fontSize: 13, color: "var(--tg-theme-hint-color, #aaa)", marginTop: 4 }}
        />
      </div>

      {/* Seek waveform bar */}
      {track && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 24px", marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36, textAlign: "right" }}>
            {fmtTime(elapsed)}
          </span>
          <div style={{ flex: 1, touchAction: "none" }}>
            <WaveformSeek elapsed={elapsed} duration={duration} accentColor={accentColor} onSeek={(pos) => { haptic("light"); onAction("seek", track.video_id, pos); }} />
          </div>
          <span style={{ fontSize: 11, color: "var(--tg-theme-hint-color, #aaa)", minWidth: 36 }}>
            {duration > 0 ? fmtTime(duration) : "-:--"}
          </span>
        </div>
      )}

      {/* Controls with haptic feedback */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 16 }}>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("shuffle"); }} aria-label={state.shuffle ? "Disable shuffle" : "Enable shuffle"}>
          <IconShuffle active={state.shuffle} color={accentColor} />
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("prev"); }} aria-label="Previous track">
          <IconSkipBack />
        </button>
        <button
          style={{ ...btnStyle, background: accentColor, color: "#fff", borderRadius: "50%", padding: 14, width: 76, height: 76, boxShadow: `0 4px 12px ${accentColorAlpha}`, transition: "background 0.5s ease, box-shadow 0.5s ease", position: "relative" }}
          onClick={() => { haptic("heavy"); onAction(state.is_playing ? "pause" : "play"); }}
          aria-label={state.is_playing ? "Pause" : "Play"}
        >
          {buffering ? (
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ animation: "spin 1s linear infinite" }}>
              <path d="M12 2a10 10 0 0 1 10 10" />
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </svg>
          ) : state.is_playing ? <IconPause /> : <IconPlay />}
        </button>
        <button style={btnStyle} onClick={() => { haptic("medium"); onAction("next"); }} aria-label="Next track">
          <IconSkipForward />
        </button>
        <button style={btnStyle} onClick={() => { haptic("light"); onAction("repeat"); }} aria-label={`Repeat: ${state.repeat_mode || "off"}`}>
          <IconRepeat mode={state.repeat_mode} activeColor={accentColor} />
        </button>
      </div>

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
            {/* Настройки */}
            <button
              onClick={() => { haptic("light"); setShowSettings(!showSettings); }}
              style={{
                padding: "10px 18px",
                borderRadius: 20,
                border: showSettings ? `1px solid ${accentColor}` : "1px solid var(--tg-theme-hint-color, #555)",
                background: showSettings ? `${accentColorAlpha}` : "rgba(255,255,255,0.06)",
                backdropFilter: "blur(12px)",
                color: showSettings ? accentColor : "var(--tg-theme-text-color, #eee)",
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
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              Настройки
            </button>
          </div>
          {/* Carousel fade edges */}
          <div style={{ position: "absolute", top: 0, left: 0, width: 20, height: "100%", background: "linear-gradient(90deg, var(--tg-theme-bg-color, #1a1a2e), transparent)", pointerEvents: "none" }} />
          <div style={{ position: "absolute", top: 0, right: 0, width: 20, height: "100%", background: "linear-gradient(270deg, var(--tg-theme-bg-color, #1a1a2e), transparent)", pointerEvents: "none" }} />
        </div>
      )}

      {/* ── Settings Panel (all heavy UI sections) ── */}
      {showSettings && (
      <div style={{
        marginTop: 16,
        display: "flex",
        flexDirection: "column",
        gap: 0,
        animation: "fadeSlideIn 0.25s ease",
      }}>

      {/* Quick Actions Row */}
      <div style={{
        display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center",
        marginBottom: 12,
      }}>
        <button onClick={() => { haptic("medium"); onWave?.(); }} disabled={isWaveLoading} style={{ padding: "8px 16px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.1)", background: "linear-gradient(135deg, rgba(124,77,255,0.15), rgba(224,64,251,0.12))", color: "var(--tg-theme-text-color, #eee)", cursor: isWaveLoading ? "wait" : "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6, opacity: isWaveLoading ? 0.6 : 1 }}>
          {isWaveLoading ? <IconSpinner size={14} /> : <IconWave size={14} />} Волна
        </button>
        <button onClick={handleSimilar} disabled={!track || isSimilarLoading} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${showSimilar ? accentColor : "rgba(255,255,255,0.1)"}`, background: showSimilar ? accentColorAlpha : "rgba(255,255,255,0.05)", color: showSimilar ? accentColor : "var(--tg-theme-text-color, #eee)", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
          {isSimilarLoading ? <IconSpinner size={14} /> : <IconSimilar size={14} />} Похожие
        </button>
        <button onClick={handleTrending} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${showTrending ? accentColor : "rgba(255,255,255,0.1)"}`, background: showTrending ? accentColorAlpha : "rgba(255,255,255,0.05)", color: showTrending ? accentColor : "var(--tg-theme-text-color, #eee)", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
          {isTrendingLoading ? <IconSpinner size={14} /> : <IconTrending size={14} />} Тренды
        </button>
        <button onClick={() => { haptic("light"); setShowSleepMenu(!showSleepMenu); }} style={{ padding: "8px 16px", borderRadius: 14, border: `1px solid ${sleepTimerRemaining ? accentColor : "rgba(255,255,255,0.1)"}`, background: sleepTimerRemaining ? accentColorAlpha : "rgba(255,255,255,0.05)", color: sleepTimerRemaining ? accentColor : "var(--tg-theme-text-color, #eee)", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
          <IconMoon size={14} /> {sleepTimerRemaining ? `${Math.ceil(sleepTimerRemaining / 60)}м` : "Сон"}
        </button>
        {track && (
          <button onClick={() => { haptic("light"); if (track) onAddToQueue?.(track); }} style={{ padding: "8px 16px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.05)", color: "var(--tg-theme-text-color, #eee)", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
            <IconPlus size={14} /> В очередь
          </button>
        )}
        {track && (
          <button onClick={() => { haptic("light"); onAddToPlaylist?.(); }} style={{ padding: "8px 16px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.05)", color: "var(--tg-theme-text-color, #eee)", cursor: "pointer", fontSize: 12, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 }}>
            <IconMusic size={14} /> В плейлист
          </button>
        )}
      </div>

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
            onInput={(e) => { const v = (e.target as HTMLInputElement).value; setAiPrompt(v); if (!v.trim()) { setShowAiPlaylist(false); setAiPlaylistTracks([]); } }}
            onKeyDown={(e) => { if (e.key === "Enter") handleAiPlaylist(); }}
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

      </div>
      )}
      {/* end showSettings */}

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
});
