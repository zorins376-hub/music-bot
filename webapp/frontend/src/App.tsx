import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import type { JSX } from "preact";
import { lazy, Suspense } from "preact/compat";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { SearchBar } from "./components/SearchBar";
import { MiniPlayer } from "./components/MiniPlayer";
import { SpectrumVisualizer } from "./components/SpectrumVisualizer";
import { IconCrown, IconShield, IconMoon, IconLime, IconSunrise, IconMusicNote, IconMusic, IconPlaySmall, IconDiamond, IconSearch, IconSpectrum, IconChart, IconPlus, IconSpinner, IconParty, IconRocket, IconHeadphones, IconHome, IconChat, IconRobot, IconFire, IconTV, IconStage, IconClipboard, IconLink, IconBell, IconMic, IconDiscover, IconUser, IconStar, IconBroadcast, IconThemeBlackroom, IconThemeTequila, IconThemeNeon, IconThemeMidnight, IconThemeEmerald } from "./components/Icons";
import { ActionSheet } from "./components/ActionSheet";
import { ViewErrorBoundary } from "./components/ViewErrorBoundary";

// Lazy-loaded views (code-split into separate chunks)
const PlaylistView = lazy(() => import("./components/PlaylistView").then(m => ({ default: m.PlaylistView })));
const PartyView = lazy(() => import("./components/PartyView").then(m => ({ default: m.PartyView })));
const ChartsView = lazy(() => import("./components/ChartsView").then(m => ({ default: m.ChartsView })));
const LyricsView = lazy(() => import("./components/LyricsView").then(m => ({ default: m.LyricsView })));
const ForYouView = lazy(() => import("./components/ForYouView").then(m => ({ default: m.ForYouView })));
const ProfileView = lazy(() => import("./components/ProfileView").then(m => ({ default: m.ProfileView })));
const LeaderboardView = lazy(() => import("./components/LeaderboardView").then(m => ({ default: m.LeaderboardView })));
const BattleView = lazy(() => import("./components/BattleView").then(m => ({ default: m.BattleView })));
const ActivityFeedView = lazy(() => import("./components/ActivityFeedView").then(m => ({ default: m.ActivityFeedView })));
const WrappedView = lazy(() => import("./components/WrappedView").then(m => ({ default: m.WrappedView })));
const SleepSoundsView = lazy(() => import("./components/SleepSoundsView").then(m => ({ default: m.SleepSoundsView })));
const LiveRadioView = lazy(() => import("./components/LiveRadioView").then(m => ({ default: m.LiveRadioView })));
import { fetchPlayerState, sendAction, getStreamUrl, reorderQueue, fetchWave, fetchSimilar, fetchRadioNext, fetchUserProfile, updateUserAudioSettings, fetchPlaylists, addTrackToPlaylist, playPlaylist, ingestEvent, isOnline, onNetworkChange, fetchBroadcast, getInitDataUnsafe, type EqPreset, type PlayerState, type Track, type UserProfile, type Playlist } from "./api";
import { extractDominantColor, extractColors, rgbToCSS, rgbaToCSS } from "./colorExtractor";
import { getStreamUrl as getCachedStreamUrl, prefetchTracks } from "./offlineCache";
import { themes, getThemeById, getSavedThemeId, saveThemeId, applyThemeCSSVars, type Theme } from "./themes";
import { ToastContainer, showToast } from "./components/Toast";

type View = "player" | "playlists" | "party" | "charts" | "search" | "lyrics" | "foryou" | "profile" | "leaderboard" | "battle" | "feed" | "wrapped" | "sleep" | "broadcast";

const EQ_STORAGE_KEY = "tma:eq-preset";
const EQ_BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000] as const;

type EqProfile = {
  gains: number[];
  preamp: number;
  makeup: number;
};

const EQ_PRESETS: Record<EqPreset, EqProfile> = {
  flat: {
    gains: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    preamp: 0,
    makeup: 0,
  },
  bass: {
    gains: [4.5, 4, 3, 1.5, 0.4, -0.6, -1, -1.2, -0.4, 0.6],
    preamp: -3.5,
    makeup: 0.2,
  },
  vocal: {
    gains: [-2, -1.6, -0.8, 0.6, 2.4, 3.8, 3.6, 2, 0.4, -0.6],
    preamp: -1.4,
    makeup: 0.28,
  },
  club: {
    gains: [3.2, 2.4, 1, -0.6, -1.2, 0.4, 1.6, 2.4, 2, 0.8],
    preamp: -2.5,
    makeup: 0.3,
  },
  bright: {
    gains: [-1.2, -0.8, -0.4, 0.2, 1, 1.8, 3, 4, 4.5, 3],
    preamp: -1.8,
    makeup: 0.22,
  },
  night: {
    gains: [2.4, 1.8, 1.2, 0.4, -0.4, -1, -1.6, -2, -2.8, -3.4],
    preamp: -1.5,
    makeup: 0.12,
  },
  soft: {
    gains: [1.2, 1, 0.6, 0.4, 0.2, 0, -0.2, 0.2, 0.6, 0.8],
    preamp: -0.6,
    makeup: 0.18,
  },
  techno: {
    gains: [3.5, 3, 1.8, 0.3, -1, -0.3, 1.2, 2.6, 3.2, 2],
    preamp: -3,
    makeup: 0.25,
  },
  vocal_boost: {
    gains: [-2.4, -1.8, -0.8, 0.4, 2.2, 3.5, 4, 2.4, 0.4, -0.3],
    preamp: -2,
    makeup: 0.2,
  },
};

// Per-band Q factor: wide on extremes, precise in mids (studio practice)
const EQ_Q: number[] = [0.6, 0.7, 0.85, 1.0, 1.2, 1.2, 1.1, 0.9, 0.75, 0.6];

function dbToGain(value: number): number {
  return Math.pow(10, value / 20);
}

// ── Luxury Audio: WaveShaper curve generators ──
const LINEAR_CURVE = new Float32Array([-1, 1]);

function createTapeCurve(samples = 8192): Float32Array {
  const curve = new Float32Array(samples);
  const k = 0.8; // gentler saturation — subtle warmth without harsh harmonics
  const norm = Math.tanh(k);
  for (let i = 0; i < samples; i++) {
    const x = (2 * i) / (samples - 1) - 1;
    curve[i] = Math.tanh(k * x) / norm;
  }
  return curve;
}

function createSoftClipCurve(samples = 8192): Float32Array {
  const curve = new Float32Array(samples);
  const ceil = 0.933; // -0.6 dBFS — extra headroom for inter-sample peaks
  for (let i = 0; i < samples; i++) {
    const x = (2 * i) / (samples - 1) - 1;
    if (Math.abs(x) <= ceil) {
      curve[i] = x;
    } else {
      const over = (Math.abs(x) - ceil) / (1 - ceil);
      curve[i] = (x > 0 ? 1 : -1) * (ceil + (1 - ceil) * (over / (1 + over)));
    }
  }
  return curve;
}

// ── Virtual Room: algorithmically generated impulse responses ──
type RoomPreset = "studio" | "concert" | "club" | "cathedral";

const ROOM_PARAMS: Record<RoomPreset, { duration: number; decay: number; lpFreq: number; preDelay: number }> = {
  studio:    { duration: 0.8,  decay: 2.0,  lpFreq: 8000,  preDelay: 0.005 },
  concert:   { duration: 2.5,  decay: 3.5,  lpFreq: 5000,  preDelay: 0.020 },
  club:      { duration: 1.2,  decay: 2.5,  lpFreq: 6000,  preDelay: 0.010 },
  cathedral: { duration: 4.0,  decay: 5.0,  lpFreq: 3500,  preDelay: 0.035 },
};

function generateImpulseResponse(ctx: AudioContext, preset: RoomPreset): AudioBuffer {
  const params = ROOM_PARAMS[preset];
  const sampleRate = ctx.sampleRate;
  const length = Math.ceil(sampleRate * params.duration);
  const buffer = ctx.createBuffer(2, length, sampleRate);
  const preDelaySamples = Math.floor(params.preDelay * sampleRate);

  for (let ch = 0; ch < 2; ch++) {
    const data = buffer.getChannelData(ch);
    for (let i = preDelaySamples; i < length; i++) {
      const t = (i - preDelaySamples) / sampleRate;
      const envelope = Math.exp(-t * params.decay);
      const lpFade = Math.exp(-t * (sampleRate / params.lpFreq) * 0.001);
      data[i] = (Math.random() * 2 - 1) * envelope * lpFade;
    }
  }
  return buffer;
}

function getSavedEqPreset(): EqPreset {
  try {
    const value = localStorage.getItem(EQ_STORAGE_KEY);
    if (value === "flat" || value === "bass" || value === "vocal" || value === "club" || value === "bright" || value === "night" || value === "soft" || value === "techno" || value === "vocal_boost") {
      return value;
    }
  } catch {}
  return "flat";
}

export function App() {
  const initDataUnsafe = getInitDataUnsafe();
  const user = initDataUnsafe?.user;
  const userId = user?.id ?? 0;

  const [view, setView] = useState<View>("foryou");
  const [partyCode, setPartyCode] = useState<string | null>(null);
  const [partyReadonly, setPartyReadonly] = useState(false);
  const [state, setState] = useState<PlayerState>({
    current_track: null,
    queue: [],
    position: 0,
    is_playing: false,
    repeat_mode: "off",
    shuffle: false,
  });
  const [lyricsTrackId, setLyricsTrackId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const elapsedRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const preloadRef = useRef<HTMLAudioElement | null>(null);
  const [theme, setThemeState] = useState<Theme>(() => getThemeById(getSavedThemeId()));
  const [accentColor, setAccentColor] = useState(theme.accent);
  const [accentColorAlpha, setAccentColorAlpha] = useState(theme.accentAlpha);
  const [meshColors, setMeshColors] = useState<string[]>([]);
  const [sleepTimerEnd, setSleepTimerEnd] = useState<number | null>(null);
  const [sleepRemaining, setSleepRemaining] = useState<number | null>(null);
  const [audioDuration, setAudioDuration] = useState(0);
  const [isWaveLoading, setIsWaveLoading] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [eqPreset, setEqPreset] = useState<EqPreset>(() => getSavedEqPreset());
  const navCarouselRef = useRef<HTMLElement | null>(null);
  const navTouchStartXRef = useRef(0);
  const navTouchStartYRef = useRef(0);
  const navTouchMovedRef = useRef(false);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaElementAudioSourceNode | null>(null);
  const eqFiltersRef = useRef<BiquadFilterNode[]>([]);
  const eqInputGainRef = useRef<GainNode | null>(null);
  const eqOutputGainRef = useRef<GainNode | null>(null);
  const crossfadeGainRef = useRef<GainNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const pannerRef = useRef<StereoPannerNode | null>(null);
  const [showSpectrum, setShowSpectrum] = useState(false);
  const [spectrumStyle, setSpectrumStyle] = useState<"bars" | "wave" | "circle">("bars");
  const [panValue, setPanValue] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [bassBoost, setBassBoost] = useState(false);
  const [partyMode, setPartyMode] = useState(false);
  const [moodFilter, setMoodFilter] = useState<string | null>(null);
  const [bypassProcessing, setBypassProcessing] = useState(false);
  const [crossfadeDuration, setCrossfadeDuration] = useState(() => {
    try { const v = localStorage.getItem("tma:crossfade"); return v ? parseInt(v, 10) : 0; } catch { return 0; }
  });
  const crossfadeDurationRef = useRef(crossfadeDuration);
  crossfadeDurationRef.current = crossfadeDuration;
  const [coverMode, setCoverMode] = useState<"default" | "vinyl" | "cd" | "case">(() => {
    try {
      const v = localStorage.getItem("tma:cover-mode");
      if (v === "default" || v === "vinyl" || v === "cd" || v === "case") return v;
      // migrate old boolean
      const old = localStorage.getItem("tma:vinyl-spin");
      return old === "false" ? "default" : "vinyl";
    } catch { return "vinyl"; }
  });
  const [tapeWarmth, setTapeWarmth] = useState(false);
  const [airBand, setAirBand] = useState(false);
  const [stereoWiden, setStereoWiden] = useState(false);
  const [softClip, setSoftClip] = useState(false);
  const [nightMode, setNightMode] = useState(false);
  const [reverbEnabled, setReverbEnabled] = useState(false);
  const [reverbPreset, setReverbPreset] = useState<RoomPreset>("studio");
  const [reverbMix, setReverbMix] = useState(0.3);
  const [karaokeMode, setKaraokeMode] = useState(false);
  const [showAddToPlaylist, setShowAddToPlaylist] = useState(false);
  const [a2pPlaylists, setA2pPlaylists] = useState<Playlist[]>([]);
  const [a2pAdding, setA2pAdding] = useState<number | null>(null);
  // ── Radio Mode ──
  const [radioMode, setRadioMode] = useState(false);
  const radioSeedRef = useRef<string | null>(null);
  const radioLoadingRef = useRef(false);
  const radioPlayedRef = useRef<string[]>([]);
  // ── Broadcast live indicator ──
  const [broadcastLive, setBroadcastLive] = useState(false);
  const [broadcastDJ, setBroadcastDJ] = useState("");
  const [liveBannerDismissed, setLiveBannerDismissed] = useState(false);
  // ── Action Sheet ──
  const [actionSheetTrack, setActionSheetTrack] = useState<Track | null>(null);
  const [actionSheetVisible, setActionSheetVisible] = useState(false);
  const subsonicFilterRef = useRef<BiquadFilterNode | null>(null);
  const compressorRef = useRef<DynamicsCompressorNode | null>(null);
  const loudnessGainRef = useRef<GainNode | null>(null);
  const bufferingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tapeWarmthRef = useRef<WaveShaperNode | null>(null);
  const airBandRef = useRef<BiquadFilterNode | null>(null);
  const softClipRef = useRef<WaveShaperNode | null>(null);
  const stereoWidenLRRef = useRef<GainNode | null>(null);
  const stereoWidenRLRef = useRef<GainNode | null>(null);
  const stereoMergerRef = useRef<ChannelMergerNode | null>(null);
  // Night Mode (heavy dynamic range compression)
  const nightCompressorRef = useRef<DynamicsCompressorNode | null>(null);
  const nightMakeupRef = useRef<GainNode | null>(null);
  // Virtual Room (convolution reverb)
  const reverbConvolverRef = useRef<ConvolverNode | null>(null);
  const reverbDryGainRef = useRef<GainNode | null>(null);
  const reverbWetGainRef = useRef<GainNode | null>(null);
  const reverbMixGainRef = useRef<GainNode | null>(null);
  // Karaoke (vocal removal via phase cancellation)
  const karaokeWetGainRef = useRef<GainNode | null>(null);
  const karaokeDryGainRef = useRef<GainNode | null>(null);
  // DJ dual-deck crossfade for party mode
  const mixDeckRef = useRef<HTMLAudioElement | null>(null);
  const mixDeckSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const mixDeckGainRef = useRef<GainNode | null>(null);
  const djCrossfadeActiveRef = useRef(false);
  const djCrossfadeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const nav = navCarouselRef.current;
    if (!nav) return;
    const activeButton = nav.querySelector<HTMLElement>(`[data-view="${view}"]`);
    if (!activeButton) return;
    const navRect = nav.getBoundingClientRect();
    const buttonRect = activeButton.getBoundingClientRect();
    const delta = (buttonRect.left - navRect.left) - (navRect.width / 2 - buttonRect.width / 2);
    nav.scrollTo({ left: nav.scrollLeft + delta, behavior: "smooth" });
  }, [view]);

  const activateView = useCallback((nextView: View) => {
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.("light"); } catch {}
    setView(nextView);
  }, []);

  const handleNavTouchStart = useCallback((event: TouchEvent) => {
    const touch = event.touches[0];
    if (!touch) return;
    navTouchStartXRef.current = touch.clientX;
    navTouchStartYRef.current = touch.clientY;
    navTouchMovedRef.current = false;
  }, []);

  const handleNavTouchMove = useCallback((event: TouchEvent) => {
    const touch = event.touches[0];
    if (!touch) return;
    const deltaX = Math.abs(touch.clientX - navTouchStartXRef.current);
    const deltaY = Math.abs(touch.clientY - navTouchStartYRef.current);
    if (deltaX > 8 || deltaY > 8) {
      navTouchMovedRef.current = true;
    }
  }, []);

  const handleNavTouchEnd = useCallback(() => {
    window.setTimeout(() => {
      navTouchMovedRef.current = false;
    }, 0);
  }, []);
  const loudnessTimerRef = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const viewRef = useRef(view);
  viewRef.current = view;
  const autoplayCountRef = useRef(0);
  const userIdRef = useRef(userId);
  userIdRef.current = userId;

  // ─── Soft play/pause: ramp outputGain to avoid clicks through EQ/compressor chain ──
  const softPause = useCallback(async (audio: HTMLAudioElement) => {
    const ctx = audioContextRef.current;
    const outGain = eqOutputGainRef.current;
    if (ctx && outGain && !audio.paused) {
      const t = ctx.currentTime;
      outGain.gain.cancelScheduledValues(t);
      outGain.gain.setValueAtTime(outGain.gain.value, t);
      outGain.gain.setTargetAtTime(0.0001, t, 0.04); // 40ms τ ≈ 160ms to silence
      await new Promise(r => setTimeout(r, 180)); // wait ~4.5 time constants
    }
    audio.pause();
  }, []);

  const softPlay = useCallback(async (audio: HTMLAudioElement) => {
    const ctx = audioContextRef.current;
    const outGain = eqOutputGainRef.current;
    if (ctx && outGain) {
      outGain.gain.cancelScheduledValues(ctx.currentTime);
      outGain.gain.setValueAtTime(0.0001, ctx.currentTime);
    }
    await audio.play().catch((e) => {
      console.warn("softPlay failed:", e?.message || e);
    });
    if (ctx && outGain) {
      const t = ctx.currentTime;
      outGain.gain.setTargetAtTime(1, t, 0.06); // 60ms τ ≈ 240ms to 98% — no pop
    }
  }, []);

  // Create persistent audio element
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    // Preload element for gapless playback
    const preload = new Audio();
    preload.preload = "auto";
    preloadRef.current = preload;

    // Mix deck for DJ crossfade (party mode)
    const mixDeck = new Audio();
    mixDeck.preload = "auto";
    mixDeckRef.current = mixDeck;

    // Keep OS media notification in sync with playback position
    const updatePositionState = () => {
      if ("mediaSession" in navigator && isFinite(audio.duration) && audio.duration > 0) {
        try {
          navigator.mediaSession.setPositionState({
            duration: Math.max(audio.duration, 0),
            playbackRate: audio.playbackRate || 1,
            position: Math.max(audio.currentTime, 0),
          });
        } catch (e) {}
      }
    };
    audio.addEventListener("playing", updatePositionState);
    audio.addEventListener("pause", updatePositionState);
    audio.addEventListener("seeked", updatePositionState);
    audio.addEventListener("ratechange", updatePositionState);

    // Buffering detection
    const onWaiting = () => {
      setBuffering(true);
      // Auto-reset buffering state after 10s to prevent infinite spinner
      if (bufferingTimeoutRef.current) clearTimeout(bufferingTimeoutRef.current);
      bufferingTimeoutRef.current = setTimeout(() => {
        console.warn("Buffering timeout — forcing spinner to stop");
        setBuffering(false);
        bufferingTimeoutRef.current = null;
      }, 10000);
    };
    const onBufferingClear = () => {
      setBuffering(false);
      if (bufferingTimeoutRef.current) {
        clearTimeout(bufferingTimeoutRef.current);
        bufferingTimeoutRef.current = null;
      }
    };
    let _errorRetryCount = 0;
    const onError = () => {
      setBuffering(false);
      if (bufferingTimeoutRef.current) {
        clearTimeout(bufferingTimeoutRef.current);
        bufferingTimeoutRef.current = null;
      }
      // Only auto-skip if user was actually playing — prevents ghost state on cold start
      const s = stateRef.current;
      if (s.is_playing && s.current_track) {
        // Retry once before skipping — stream may still be loading on server
        if (_errorRetryCount < 1) {
          _errorRetryCount++;
          console.warn("Audio error, retrying in 1.5s...");
          setBuffering(true);
          setTimeout(() => {
            const a = audioRef.current;
            if (a && a.src) {
              const src = a.src;
              a.src = "";
              a.src = src;
              a.play().catch(() => {});
            }
          }, 1500);
          return;
        }
        _errorRetryCount = 0;
        console.warn("Audio error during playback, auto-skipping to next track");
        showToast(`Track unavailable, skipping...`, "warning", 2500);
        sendAction("next").then(setState).catch(() => {});
      }
    };
    // Reset retry counter on successful play
    const onPlaying = () => {
      _errorRetryCount = 0;
      onBufferingClear();
    };
    audio.addEventListener("waiting", onWaiting);
    audio.addEventListener("playing", onPlaying);
    audio.addEventListener("canplay", onBufferingClear);
    audio.addEventListener("error", onError);

    audio.addEventListener("ended", async () => {
      // DJ crossfade already handled the transition — skip double-advance
      if (djCrossfadeActiveRef.current) return;
      // Don't swap audio elements — it breaks AudioContext source connection.
      // Cache + prefetch ensures the next track loads almost instantly.
      const s = stateRef.current;
      const isLastTrack = s.queue.length > 0 && s.position >= s.queue.length - 1;

      if (isLastTrack && autoplayCountRef.current < (radioMode ? 50 : 3)) {
        // Infinity autoplay: queue exhausted — fetch more tracks
        autoplayCountRef.current++;
        try {
          const currentId = s.current_track?.video_id;
          let recs: Track[] = [];
          if (radioMode && currentId) {
            // Radio mode: use dedicated radio endpoint with seed
            const seed = radioSeedRef.current || currentId;
            recs = await fetchRadioNext(seed, radioPlayedRef.current.slice(-30), 8);
            if (recs.length > 0) {
              recs.forEach(t => radioPlayedRef.current.push(t.video_id));
            }
          } else if (currentId) {
            recs = await fetchSimilar(currentId, 8);
          }
          if (recs.length === 0) recs = await fetchWave(userIdRef.current, 8, null);
          if (recs.length > 0) {
            for (const t of recs) await sendAction("add", t.video_id, undefined, t);
            const ns = await sendAction("next");
            setState(ns);
            return;
          }
        } catch {}
      }

      if (!isLastTrack) autoplayCountRef.current = 0;
      sendAction("next").then(setState).catch(() => {});
    });
    audio.addEventListener("timeupdate", () => {
      const t = Math.floor(audio.currentTime);
      elapsedRef.current = t;
      setElapsed(t);
      const s = stateRef.current;

      // Aggressive pre-fetch: start caching next tracks at 70% playback
      if (audio.duration && audio.currentTime / audio.duration >= 0.7) {
        const nextIds: string[] = [];
        for (let i = 1; i <= 2; i++) {
          const idx = (s.position + i) % s.queue.length;
          if (s.queue.length > 1 && s.queue[idx]?.video_id) {
            nextIds.push(s.queue[idx].video_id);
          }
        }
        if (nextIds.length) prefetchTracks(nextIds);
      }

      // ── Crossfade: smooth transition between tracks ──
      // Works in party mode (always 5s), broadcast mode (always 8s), OR regular mode (user-configurable)
      const remaining = audio.duration ? audio.duration - audio.currentTime : Infinity;
      const cfDur = viewRef.current === "party" ? 5 : crossfadeDurationRef.current;
      const shouldCrossfade = s.queue.length > 1 && cfDur > 0;
      if (shouldCrossfade && remaining <= cfDur && remaining > 0.5 && audio.duration > cfDur * 2 && !djCrossfadeActiveRef.current) {
        const nextIdx = (s.position + 1) % s.queue.length;
        const nextTrack = s.queue[nextIdx];
        if (nextTrack && nextTrack.video_id !== s.current_track?.video_id) {
          djCrossfadeActiveRef.current = true;
          const mix = mixDeckRef.current;
          const mixGain = mixDeckGainRef.current;
          const cfGain = crossfadeGainRef.current;
          const ctx = audioContextRef.current;
          if (mix && mixGain && cfGain && ctx) {
            // Load and play next track on mix deck
            const apiUrl = getStreamUrl(nextTrack.video_id);
            mix.src = apiUrl;
            mix.load();
            // Check cache in parallel
            getCachedStreamUrl(nextTrack.video_id, apiUrl).then((cached) => {
              if (cached !== apiUrl) mix.src = cached;
            });
            mix.play().catch(() => {});
            // Crossfade: main deck down, mix deck up over cfDur-0.5 seconds
            const fadeDur = Math.max(1, cfDur - 0.5);
            const now = ctx.currentTime;
            cfGain.gain.setValueAtTime(cfGain.gain.value, now);
            cfGain.gain.exponentialRampToValueAtTime(0.001, now + fadeDur);
            mixGain.gain.setValueAtTime(0.001, now);
            mixGain.gain.exponentialRampToValueAtTime(1, now + fadeDur);
            // After crossfade completes: advance to next track on main deck
            djCrossfadeTimerRef.current = window.setTimeout(() => {
              // Stop mix deck
              mix.pause();
              mix.src = "";
              if (ctx) mixGain.gain.setValueAtTime(0, ctx.currentTime);
              // Restore main deck gain
              if (ctx) cfGain.gain.setValueAtTime(1, ctx.currentTime);
              djCrossfadeActiveRef.current = false;
              sendAction("next").then(setState).catch(() => {});
            }, (fadeDur + 0.1) * 1000);
          }
        }
      }

      // Gapless: preload next track 30 seconds before end
      if (audio.duration && audio.duration - audio.currentTime < 30 && audio.duration > 35) {
        const nextIdx = (s.position + 1) % s.queue.length;
        if (s.queue.length > 1 && preloadRef.current) {
          const nextTrack = s.queue[nextIdx];
          const nextSrc = getStreamUrl(nextTrack.video_id);
          if (preloadRef.current.src !== nextSrc) {
            preloadRef.current.src = nextSrc;
            preloadRef.current.load();
          }
        }
      }
    });

    // Update duration from audio metadata if track has no duration
    audio.addEventListener("loadedmetadata", () => {
      updatePositionState();
      if (audio.duration && isFinite(audio.duration)) {
        const realDuration = Math.floor(audio.duration);
        setAudioDuration(realDuration);
        setState((prev) => {
          if (prev.current_track && (!prev.current_track.duration || prev.current_track.duration === 0)) {
            const mins = Math.floor(realDuration / 60);
            const secs = realDuration % 60;
            return {
              ...prev,
              current_track: {
                ...prev.current_track,
                duration: realDuration,
                duration_fmt: `${mins}:${secs < 10 ? "0" : ""}${secs}`,
              },
            };
          }
          return prev;
        });
      }
    });

    return () => {
      audio.removeEventListener("playing", updatePositionState);
      audio.removeEventListener("pause", updatePositionState);
      audio.removeEventListener("seeked", updatePositionState);
      audio.removeEventListener("ratechange", updatePositionState);
      audio.removeEventListener("waiting", onWaiting);
      audio.removeEventListener("playing", onPlaying);
      audio.removeEventListener("canplay", onBufferingClear);
      audio.removeEventListener("error", onError);
      audio.pause();
      audio.src = "";
      preload.src = "";
    };
  }, []);

  const ensureEqualizerGraph = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (sourceNodeRef.current && eqFiltersRef.current.length) return;

    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;

    // Let browser pick optimal sampleRate (avoids resampling artifacts when source is 48kHz)
    const ctx = audioContextRef.current || new AudioContextCtor({
      latencyHint: "playback", // "playback" = larger buffer = fewer underrun glitches
    });
    audioContextRef.current = ctx;

    if (!sourceNodeRef.current) {
      const source = ctx.createMediaElementSource(audio);
      const crossfadeGain = ctx.createGain();
      const inputGain = ctx.createGain();
      const outputGain = ctx.createGain();

      // ── Loudness normalization gain — adjusted per-track to ~-14 LUFS ──
      const loudnessGain = ctx.createGain();
      loudnessGain.gain.value = 1;
      loudnessGainRef.current = loudnessGain;

      // ── Subsonic filter: HPF @ 20Hz removes inaudible rumble + DC offset ──
      const subsonicFilter = ctx.createBiquadFilter();
      subsonicFilter.type = "highpass";
      subsonicFilter.frequency.value = 20;
      subsonicFilter.Q.value = 0.707; // Butterworth Q — maximally flat passband
      subsonicFilterRef.current = subsonicFilter;

      // ── DC blocker: HPF @ 5Hz catches any DC offset from waveshapers ──
      const dcBlocker = ctx.createBiquadFilter();
      dcBlocker.type = "highpass";
      dcBlocker.frequency.value = 5;
      dcBlocker.Q.value = 0.5;

      // ── 10-band parametric EQ with studio Q values ──
      const filters = EQ_BANDS.map((freq, idx) => {
        const filter = ctx.createBiquadFilter();
        filter.type = idx === 0 ? "lowshelf" : idx === EQ_BANDS.length - 1 ? "highshelf" : "peaking";
        filter.frequency.value = freq;
        filter.Q.value = EQ_Q[idx];
        return filter;
      });

      // ── Transparent peak limiter — brickwall safety net, NOT a compressor ──
      const compressor = ctx.createDynamicsCompressor();
      compressor.threshold.value = -2;   // -2dBFS — extra headroom catches inter-sample peaks
      compressor.knee.value = 0.5;       // Hard knee = true limiter behavior, no pumping
      compressor.ratio.value = 20;       // Brickwall ratio — clamps peaks, doesn't compress
      compressor.attack.value = 0.0005;  // 0.5ms — catches transients before they clip
      compressor.release.value = 0.08;   // 80ms — fast release, no artifacts since rarely triggers
      compressorRef.current = compressor;

      // ── Night Mode: heavy dynamic range compression for quiet listening ──
      const nightCompressor = ctx.createDynamicsCompressor();
      nightCompressor.threshold.value = 0;    // pass-through default
      nightCompressor.knee.value = 40;
      nightCompressor.ratio.value = 1;        // 1:1 = no compression when off
      nightCompressor.attack.value = 0.005;
      nightCompressor.release.value = 0.2;
      nightCompressorRef.current = nightCompressor;

      const nightMakeup = ctx.createGain();
      nightMakeup.gain.value = 1;
      nightMakeupRef.current = nightMakeup;

      // ── Tape Saturation (WaveShaperNode) — warm analog character ──
      const tapeSat = ctx.createWaveShaper();
      tapeSat.curve = LINEAR_CURVE;
      tapeSat.oversample = "2x"; // oversample prevents aliasing crackle from waveshaper
      tapeWarmthRef.current = tapeSat;

      // ── Air Band — high shelf +2dB at 12kHz for sparkle/detail ──
      const airFilter = ctx.createBiquadFilter();
      airFilter.type = "highshelf";
      airFilter.frequency.value = 12000;
      airFilter.gain.value = 0;
      airBandRef.current = airFilter;

      // ── Stereo panner for 3D spatial audio ──
      const panner = ctx.createStereoPanner();
      panner.pan.value = 0;

      // ── Stereo Widener (mid/side crossfeed matrix) ──
      const splitter = ctx.createChannelSplitter(2);
      const merger = ctx.createChannelMerger(2);
      const gainLL = ctx.createGain(); gainLL.gain.value = 1;
      const gainRR = ctx.createGain(); gainRR.gain.value = 1;
      const gainLR = ctx.createGain(); gainLR.gain.value = 0; // R→L crossfeed (OFF)
      const gainRL = ctx.createGain(); gainRL.gain.value = 0; // L→R crossfeed (OFF)
      splitter.connect(gainLL, 0); splitter.connect(gainRL, 0); // L channel
      splitter.connect(gainRR, 1); splitter.connect(gainLR, 1); // R channel
      gainLL.connect(merger, 0, 0); gainLR.connect(merger, 0, 0); // → L out
      gainRR.connect(merger, 0, 1); gainRL.connect(merger, 0, 1); // → R out
      stereoWidenLRRef.current = gainLR;
      stereoWidenRLRef.current = gainRL;
      stereoMergerRef.current = merger;

      // ── Real-time analyser for spectrum visualizer ──
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.82;

      // ── Soft Clipper — true peak limiter at -0.5dBFS ──
      const clipper = ctx.createWaveShaper();
      clipper.curve = LINEAR_CURVE;
      clipper.oversample = "2x";
      softClipRef.current = clipper;

      // ── Signal chain: source → loudness → crossfade → preamp → HPF → EQ
      //    → limiter → tapeSat → airBand → panner → widener → analyser → clipper → dcBlock → output ──
      source.connect(loudnessGain);
      loudnessGain.connect(crossfadeGain);
      crossfadeGain.connect(inputGain);
      inputGain.connect(subsonicFilter);

      let node: AudioNode = subsonicFilter;
      filters.forEach((filter) => {
        node.connect(filter);
        node = filter;
      });
      node.connect(compressor);
      compressor.connect(nightCompressor);
      nightCompressor.connect(nightMakeup);
      nightMakeup.connect(tapeSat);
      tapeSat.connect(airFilter);
      airFilter.connect(panner);
      panner.connect(splitter);

      // ── Virtual Room (convolution reverb) — parallel wet/dry after widener ──
      const reverbDryGain = ctx.createGain();
      reverbDryGain.gain.value = 1;
      const reverbConvolver = ctx.createConvolver();
      reverbConvolver.buffer = generateImpulseResponse(ctx, "studio");
      const reverbWetGain = ctx.createGain();
      reverbWetGain.gain.value = 0; // OFF by default
      const reverbMixGain = ctx.createGain();
      reverbMixGain.gain.value = 1;
      reverbConvolverRef.current = reverbConvolver;
      reverbDryGainRef.current = reverbDryGain;
      reverbWetGainRef.current = reverbWetGain;
      reverbMixGainRef.current = reverbMixGain;

      merger.connect(reverbDryGain);
      merger.connect(reverbConvolver);
      reverbConvolver.connect(reverbWetGain);
      reverbDryGain.connect(reverbMixGain);
      reverbWetGain.connect(reverbMixGain);
      reverbMixGain.connect(analyser);

      analyser.connect(clipper);
      clipper.connect(dcBlocker);

      // ── Karaoke (vocal removal via center channel phase cancellation) ──
      const karaokeSplitter = ctx.createChannelSplitter(2);
      const karaokeInvert = ctx.createGain();
      karaokeInvert.gain.value = -1;
      const karaokeSummer = ctx.createGain();
      karaokeSummer.gain.value = 0.5;
      const karaokeMerger = ctx.createChannelMerger(2);
      const karaokeWetGain = ctx.createGain();
      karaokeWetGain.gain.value = 0; // OFF by default
      const karaokeDryGain = ctx.createGain();
      karaokeDryGain.gain.value = 1;
      karaokeWetGainRef.current = karaokeWetGain;
      karaokeDryGainRef.current = karaokeDryGain;

      karaokeSplitter.connect(karaokeSummer, 0);
      karaokeSplitter.connect(karaokeInvert, 1);
      karaokeInvert.connect(karaokeSummer);
      karaokeSummer.connect(karaokeMerger, 0, 0);
      karaokeSummer.connect(karaokeMerger, 0, 1);
      karaokeMerger.connect(karaokeWetGain);

      dcBlocker.connect(karaokeSplitter);
      dcBlocker.connect(karaokeDryGain);
      karaokeWetGain.connect(outputGain);
      karaokeDryGain.connect(outputGain);
      outputGain.connect(ctx.destination);

      sourceNodeRef.current = source;
      eqFiltersRef.current = filters;
      eqInputGainRef.current = inputGain;
      eqOutputGainRef.current = outputGain;
      crossfadeGainRef.current = crossfadeGain;
      analyserRef.current = analyser;
      pannerRef.current = panner;

      // ── DJ Mix Deck: second audio source for true dual-deck crossfade ──
      const mixAudio = mixDeckRef.current;
      if (mixAudio && !mixDeckSourceRef.current) {
        const mixSource = ctx.createMediaElementSource(mixAudio);
        const mixGain = ctx.createGain();
        mixGain.gain.value = 0; // silent by default
        mixSource.connect(mixGain);
        mixGain.connect(loudnessGain); // sums with main deck at loudnessGain
        mixDeckSourceRef.current = mixSource;
        mixDeckGainRef.current = mixGain;
      }
    }
  }, []);

  const applyEqPreset = useCallback((preset: EqPreset) => {
    ensureEqualizerGraph();
    const profile = EQ_PRESETS[preset] || EQ_PRESETS.flat;
    const ctx = audioContextRef.current;
    if (!ctx) return;
    const now = ctx.currentTime;

    // Smooth ramp: anchor current value then exponentially approach target
    // Time constant 0.15 = ~450ms to reach 95% of target (no clicks)
    eqFiltersRef.current.forEach((filter, idx) => {
      const target = profile.gains[idx] ?? 0;
      filter.gain.setValueAtTime(filter.gain.value, now);
      filter.gain.setTargetAtTime(target, now, 0.15);
    });

    if (eqInputGainRef.current) {
      const g = eqInputGainRef.current.gain;
      g.setValueAtTime(g.value, now);
      g.setTargetAtTime(dbToGain(profile.preamp), now, 0.15);
    }

    if (eqOutputGainRef.current) {
      const g = eqOutputGainRef.current.gain;
      g.setValueAtTime(g.value, now);
      g.setTargetAtTime(dbToGain(profile.makeup), now, 0.2);
    }
  }, [ensureEqualizerGraph]);

  // ── Loudness normalization: measure RMS of raw source and gently nudge gain ──
  const measureLoudness = useCallback(() => {
    if (loudnessTimerRef.current) clearInterval(loudnessTimerRef.current);
    const ctx = audioContextRef.current;
    const lg = loudnessGainRef.current;
    if (!ctx || !lg) return;

    // Ensure audio is actually playing before measuring
    const audio = audioRef.current;
    if (!audio || audio.paused || audio.currentTime < 0.5) return;

    // Create a temporary analyser connected BEFORE the processing chain
    // to measure raw source level, not post-EQ/compressor level
    const rawAnalyser = ctx.createAnalyser();
    rawAnalyser.fftSize = 2048; // larger FFT = more accurate RMS
    rawAnalyser.smoothingTimeConstant = 0;
    const source = sourceNodeRef.current;
    if (!source) return;
    source.connect(rawAnalyser); // tap raw signal (doesn't affect chain)

    const buf = new Float32Array(rawAnalyser.fftSize);
    const TARGET_RMS_DB = -16; // conservative target
    const MEASURE_WINDOW = 3; // seconds
    const framesNeeded = Math.ceil((ctx.sampleRate * MEASURE_WINDOW) / rawAnalyser.fftSize);
    let frameCount = 0;
    let sumSquares = 0;
    let totalSamples = 0;

    loudnessTimerRef.current = window.setInterval(() => {
      rawAnalyser.getFloatTimeDomainData(buf);

      // Skip silent frames
      let frameEnergy = 0;
      for (let i = 0; i < buf.length; i++) frameEnergy += buf[i] * buf[i];
      if (frameEnergy / buf.length < 1e-8) return;

      for (let i = 0; i < buf.length; i++) sumSquares += buf[i] * buf[i];
      totalSamples += buf.length;
      frameCount++;

      if (frameCount >= framesNeeded) {
        if (loudnessTimerRef.current) clearInterval(loudnessTimerRef.current);
        loudnessTimerRef.current = null;
        rawAnalyser.disconnect(); // clean up tap

        const rms = Math.sqrt(sumSquares / totalSamples);
        if (rms > 0.002) {
          const currentDb = 20 * Math.log10(rms);
          const correction = TARGET_RMS_DB - currentDb;
          // Clamp to ±3dB — very conservative, just levels out loud vs quiet tracks
          const clampedDb = Math.max(-3, Math.min(3, correction));
          const gain = Math.pow(10, clampedDb / 20);
          const t = ctx.currentTime;
          // 1s time constant = ~3s to settle — completely imperceptible
          lg.gain.setValueAtTime(Math.max(lg.gain.value, 0.01), t);
          lg.gain.setTargetAtTime(Math.max(gain, 0.25), t, 1.0);
        }
      }
    }, 250); // 4x/sec
  }, []);

  // Bypass all processing (raw audio signal)
  const handleBypass = useCallback((on: boolean) => {
    setBypassProcessing(on);
    ensureEqualizerGraph();
    const ctx = audioContextRef.current;
    const cfGain = crossfadeGainRef.current;
    const inputGain = eqInputGainRef.current;
    const analyser = analyserRef.current;
    const outputGain = eqOutputGainRef.current;
    if (!ctx || !cfGain || !inputGain || !analyser || !outputGain) return;

    const now = ctx.currentTime;
    // Fade out using setTargetAtTime (click-free exponential decay)
    outputGain.gain.setTargetAtTime(0.0001, now, 0.02);
    setTimeout(() => {
      if (on) {
        cfGain.disconnect();
        cfGain.connect(analyser);
      } else {
        cfGain.disconnect();
        cfGain.connect(inputGain);
        applyEqPreset(eqPreset);
        if (pannerRef.current) {
          const t2 = ctx.currentTime;
          pannerRef.current.pan.setValueAtTime(panValue, t2);
        }
        // Restore luxury audio states
        if (tapeWarmthRef.current) tapeWarmthRef.current.curve = tapeWarmth ? createTapeCurve() : LINEAR_CURVE;
        if (airBandRef.current) airBandRef.current.gain.value = airBand ? 2 : 0;
        if (softClipRef.current) softClipRef.current.curve = softClip ? createSoftClipCurve() : LINEAR_CURVE;
        // Night mode, reverb, karaoke nodes stay connected and retain their params through bypass
      }
      const t2 = ctx.currentTime;
      // Fade in using setTargetAtTime
      outputGain.gain.setValueAtTime(0.0001, t2);
      outputGain.gain.setTargetAtTime(1, t2, 0.025);
    }, 100); // Increased delay for safer switching
  }, [ensureEqualizerGraph, applyEqPreset, eqPreset, panValue, tapeWarmth, airBand, softClip]);

  useEffect(() => {
    try {
      localStorage.setItem(EQ_STORAGE_KEY, eqPreset);
    } catch {}
    applyEqPreset(eqPreset);
  }, [eqPreset, applyEqPreset]);

  // Persist luxury audio settings
  useEffect(() => {
    try {
      localStorage.setItem("tma:luxury-audio", JSON.stringify({ tapeWarmth, airBand, stereoWiden, softClip, nightMode, reverbEnabled, reverbPreset, reverbMix, karaokeMode }));
    } catch {}
  }, [tapeWarmth, airBand, stereoWiden, softClip, nightMode, reverbEnabled, reverbPreset, reverbMix, karaokeMode]);

  // Listen for media control actions from Service Worker notifications
  useEffect(() => {
    const onSWMessage = (event: MessageEvent) => {
      if (event.data?.type === "MEDIA_ACTION") {
        const action = event.data.action;
        if (action === "pause" || action === "toggle") {
          const a = audioRef.current;
          if (a && !a.paused) {
            sendAction("pause").then(setState).catch(() => {});
          } else {
            sendAction("play").then(setState).catch(() => {});
          }
        } else if (action === "next") {
          sendAction("next").then(setState).catch(() => {});
        } else if (action === "prev") {
          sendAction("prev").then(setState).catch(() => {});
        }
      }
    };
    navigator.serviceWorker?.addEventListener("message", onSWMessage);
    return () => navigator.serviceWorker?.removeEventListener("message", onSWMessage);
  }, []);

  // Screen Wake Lock: keep screen on while playing
  useEffect(() => {
    const acquireWakeLock = async () => {
      if (!("wakeLock" in navigator)) return;
      try {
        wakeLockRef.current = await navigator.wakeLock.request("screen");
        wakeLockRef.current.addEventListener("release", () => {
          wakeLockRef.current = null;
        });
      } catch {}
    };
    const releaseWakeLock = () => {
      wakeLockRef.current?.release().catch(() => {});
      wakeLockRef.current = null;
    };

    if (state.is_playing) {
      acquireWakeLock();
      // Re-acquire after tab becomes visible again (browser releases on hide)
      const onVisibility = () => {
        if (document.visibilityState === "visible" && state.is_playing) acquireWakeLock();
      };
      document.addEventListener("visibilitychange", onVisibility);
      return () => { document.removeEventListener("visibilitychange", onVisibility); releaseWakeLock(); };
    } else {
      releaseWakeLock();
    }
  }, [state.is_playing]);

  // Track ID ref to detect changes
  const currentTrackIdRef = useRef<string | null>(null);

  // Sync audio with current track (with offline cache)
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const track = state.current_track;
    if (!track) {
      audio.pause(); audio.src = "";
      currentTrackIdRef.current = null;
      if ("mediaSession" in navigator) navigator.mediaSession.metadata = null;
      // Hide notification shade entry
      if (navigator.serviceWorker?.controller) {
        navigator.serviceWorker.controller.postMessage({ type: "HIDE_NOW_PLAYING" });
      }
      return;
    }

    // Load audio with crossfade
    const loadAudio = async () => {
      if (currentTrackIdRef.current === track.video_id) return;
      currentTrackIdRef.current = track.video_id;
      if (bufferingTimeoutRef.current) clearTimeout(bufferingTimeoutRef.current);
      setBuffering(true);

      // Resume AudioContext if suspended (required on mobile after user gesture)
      const ctx = audioContextRef.current;
      if (ctx && ctx.state === "suspended") {
        await ctx.resume().catch(() => {});
      }

      // Crossfade out before switching source — setTargetAtTime avoids numerical artifacts
      const cfGain = crossfadeGainRef.current;
      const outGain = eqOutputGainRef.current;
      if (ctx && outGain && !audio.paused) {
        const t = ctx.currentTime;
        outGain.gain.cancelScheduledValues(t);
        outGain.gain.setValueAtTime(outGain.gain.value, t);
        outGain.gain.setTargetAtTime(0.0001, t, 0.03); // 30ms τ ≈ 120ms to silence
        await new Promise(r => setTimeout(r, 140));
      }

      audio.pause();

      // Resolve source URL: try cache first (instant), fallback to API stream
      const apiUrl = getStreamUrl(track.video_id);
      const cachedUrl = await getCachedStreamUrl(track.video_id, apiUrl);
      audio.src = cachedUrl; // uses cache blob URL if available, otherwise API URL
      // No audio.load() — setting src already triggers load; explicit load() aborts & restarts connection

      // Broadcast radio sync: seek to the DJ's current position
      const seekToStart = track.startAt;

      // Wait for browser to buffer enough before playing (prevents underrun clicks)
      if (state.is_playing) {
        await new Promise<void>((resolve) => {
          const onReady = () => { audio.removeEventListener("canplaythrough", onReady); resolve(); };
          if (audio.readyState >= 4) { resolve(); } // HAVE_ENOUGH_DATA — fully buffered
          else { audio.addEventListener("canplaythrough", onReady, { once: true }); }
          // Timeout fallback: don't block forever on slow networks
          setTimeout(resolve, 8000);
        });
        if (seekToStart && seekToStart > 1) {
          audio.currentTime = seekToStart;
        }
        await audio.play().catch((e) => {
          console.warn("loadAudio play() rejected:", e?.message || e);
        });
      }

      // Smooth fade in — single gain node, no competing ramps
      if (ctx && outGain) {
        const t = ctx.currentTime;
        outGain.gain.cancelScheduledValues(t);
        outGain.gain.setValueAtTime(0.0001, t);
        outGain.gain.setTargetAtTime(1, t, 0.05); // 50ms τ ≈ 200ms to full volume
      }
      // Reset crossfade gain to unity (it may have been touched by DJ crossfade)
      if (ctx && cfGain) {
        cfGain.gain.cancelScheduledValues(ctx.currentTime);
        cfGain.gain.setValueAtTime(1, ctx.currentTime);
      }

      // Reset loudness gain to unity, then measure after audio is actually playing
      const lg = loudnessGainRef.current;
      if (ctx && lg) {
        lg.gain.setValueAtTime(1, ctx.currentTime);
      }
      // Delay loudness measurement until audio has been playing ~1.5s
      setTimeout(() => measureLoudness(), 1500);

      // Prefetch next 2 tracks in queue so they start instantly
      if (state.queue.length > 1) {
        const nextIds: string[] = [];
        for (let i = 1; i <= 2; i++) {
          const idx = (state.position + i) % state.queue.length;
          if (state.queue[idx]?.video_id !== track.video_id) {
            nextIds.push(state.queue[idx].video_id);
          }
        }
        if (nextIds.length) prefetchTracks(nextIds);
      }

      setBuffering(false);
    };
    
    loadAudio().then(async () => {
      if (state.is_playing && audio.paused) {
        await softPlay(audio);
      } else if (!state.is_playing && !audio.paused) {
        await softPause(audio);
      }
    }).catch((e) => {
      console.error("Audio playback error:", e);
      setBuffering(false);
    });

    if ("mediaSession" in navigator) {
      const artworkSrc = track.cover_url || `${window.location.origin}/icon.svg`;
      const artworkType = track.cover_url ? "image/jpeg" : "image/svg+xml";
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: track.title,
        artist: track.artist || "Black Room Radio",
        artwork: track.cover_url
          ? [
              { src: track.cover_url, sizes: "96x96", type: "image/jpeg" },
              { src: track.cover_url, sizes: "128x128", type: "image/jpeg" },
              { src: track.cover_url, sizes: "192x192", type: "image/jpeg" },
              { src: track.cover_url, sizes: "256x256", type: "image/jpeg" },
              { src: track.cover_url, sizes: "384x384", type: "image/jpeg" },
              { src: track.cover_url, sizes: "512x512", type: "image/jpeg" },
            ]
          : [
              { src: artworkSrc, sizes: "any", type: artworkType },
            ]
      });
      navigator.mediaSession.playbackState = state.is_playing ? "playing" : "paused";

      // Push persistent notification to notification shade via Service Worker
      if (navigator.serviceWorker?.controller) {
        navigator.serviceWorker.controller.postMessage({
          type: "SHOW_NOW_PLAYING",
          title: track.title,
          artist: track.artist || "Black Room Radio",
          icon: track.cover_url || "/icon.svg",
        });
      }

      navigator.mediaSession.setActionHandler("play", () => {
        sendAction("play").then(setState).catch(() => {});
      });
      navigator.mediaSession.setActionHandler("pause", () => {
        sendAction("pause").then(setState).catch(() => {});
      });
      navigator.mediaSession.setActionHandler("previoustrack", () => {
        sendAction("prev").then(setState).catch(() => {});
      });
      navigator.mediaSession.setActionHandler("nexttrack", () => {
        sendAction("next").then(setState).catch(() => {});
      });
      
      // Support for scrubbing/seeking from notification shade (lock screen)
      navigator.mediaSession.setActionHandler("seekto", (details) => {
        const seekTime = details.seekTime || 0;
        audio.currentTime = seekTime;
        sendAction("seek", Math.floor(seekTime).toString()).then(setState).catch(() => {});
      });
      navigator.mediaSession.setActionHandler("seekforward", (details) => {
        const skip = details.seekOffset || 10;
        const newTime = Math.min(audio.currentTime + skip, audio.duration || 0);
        audio.currentTime = newTime;
        sendAction("seek", Math.floor(newTime).toString()).then(setState).catch(() => {});
      });
      navigator.mediaSession.setActionHandler("seekbackward", (details) => {
        const skip = details.seekOffset || 10;
        const newTime = Math.max(audio.currentTime - skip, 0);
        audio.currentTime = newTime;
        sendAction("seek", Math.floor(newTime).toString()).then(setState).catch(() => {});
      });
    }
  }, [state.current_track?.video_id, state.is_playing]);

  // Apply theme to body
  useEffect(() => {
    document.body.style.background = theme.bgColor;
    document.body.style.color = theme.textColor;
    applyThemeCSSVars(theme);
  }, [theme]);

  const switchTheme = useCallback(() => {
    setThemeState((prev) => {
      const idx = themes.findIndex((t) => t.id === prev.id);
      const next = themes[(idx + 1) % themes.length];
      saveThemeId(next.id);
      // Reset accent to new theme default
      setAccentColor(next.accent);
      setAccentColorAlpha(next.accentAlpha);
      // Re-extract cover color after theme switch
      if (state.current_track?.cover_url) {
        extractDominantColor(state.current_track.cover_url).then((color) => {
          setAccentColor(rgbToCSS(color));
          setAccentColorAlpha(rgbaToCSS(color, 0.4));
        });
      }
      return next;
    });
  }, [state.current_track?.cover_url]);

  // Dynamic Color Extraction from cover
  useEffect(() => {
    const coverUrl = state.current_track?.cover_url;
    if (coverUrl) {
      extractColors(coverUrl).then(({ dominant, top3 }) => {
        setAccentColor(rgbToCSS(dominant));
        setAccentColorAlpha(rgbaToCSS(dominant, 0.4));
        setMeshColors(top3.map((c) => rgbaToCSS(c, 0.35)));
      });
    } else {
      setAccentColor(theme.accent);
      setAccentColorAlpha(theme.accentAlpha);
      setMeshColors([]);
    }
  }, [state.current_track?.cover_url, theme]);

  useEffect(() => {
    // Notify Telegram that WebApp is ready & expand to full height
    try { window.Telegram?.WebApp?.ready?.(); window.Telegram?.WebApp?.expand?.(); } catch {}

    if (userId) {
      fetchUserProfile().then(setUserProfile).catch(() => {});
      fetchPlayerState(userId).then((s) => {
        // On initial load, force paused state — user must press play
        setState({ ...s, is_playing: false });
        // If user has a track loaded, switch to player view
        if (s.current_track) setView("player");
      }).catch(() => {});
    }
    // Handle deep link from share: startapp=play_VIDEOID
    const startParam = initDataUnsafe?.start_param;
    if (startParam && startParam.startsWith("play_")) {
      const videoId = startParam.slice(5);
      if (videoId) {
        setView("player");
        sendAction("play", videoId).then(setState).catch(() => {});
      }
    }
    if (startParam && startParam.startsWith("party_")) {
      const code = startParam.slice(6);
      if (code) {
        setPartyReadonly(false);
        setPartyCode(code);
        setView("party");
      }
    }
    if (startParam && startParam.startsWith("partytv_")) {
      const code = startParam.slice(8);
      if (code) {
        setPartyReadonly(true);
        setPartyCode(code);
        setView("party");
      }
    }
    if (startParam === "broadcast") {
      setView("broadcast");
    }
  }, [userId]);

  // ── Broadcast live polling ──
  const broadcastLiveRef = useRef(false);
  const broadcastDJRef = useRef("DJ");
  useEffect(() => {
    let active = true;
    const check = () => {
      fetchBroadcast().then((b) => {
        if (!active) return;
        const wasLive = broadcastLiveRef.current;
        const newDJ = b.dj_name || "DJ";
        if (b.is_live !== wasLive) {
          broadcastLiveRef.current = b.is_live;
          setBroadcastLive(b.is_live);
        }
        if (newDJ !== broadcastDJRef.current) {
          broadcastDJRef.current = newDJ;
          setBroadcastDJ(newDJ);
        }
        if (b.is_live && !wasLive) setLiveBannerDismissed(false);
      }).catch(() => {});
    };
    check();
    const iv = setInterval(check, 30000);
    return () => { active = false; clearInterval(iv); };
  }, []);

  // ── Network status monitor ──
  useEffect(() => {
    return onNetworkChange((online) => {
      if (online) {
        showToast("Back online", "success", 2000);
      } else {
        showToast("No internet connection", "warning", 5000);
      }
    });
  }, []);

  useEffect(() => {
    elapsedRef.current = 0;
    setElapsed(0);
    setAudioDuration(state.current_track?.duration ?? 0);
  }, [state.current_track?.video_id]);

  // Sleep Timer countdown
  useEffect(() => {
    if (!sleepTimerEnd) { setSleepRemaining(null); return; }
    const tick = () => {
      const left = Math.max(0, Math.round((sleepTimerEnd - Date.now()) / 1000));
      setSleepRemaining(left);
      if (left <= 0) {
        setSleepTimerEnd(null);
        setSleepRemaining(null);
        // Pause playback (with fade)
        if (audioRef.current) softPause(audioRef.current);
        sendAction("pause").then(setState).catch(() => {});
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [sleepTimerEnd]);

  const handleSleepTimer = useCallback((minutes: number | null) => {
    if (minutes === null) {
      setSleepTimerEnd(null);
      setSleepRemaining(null);
    } else {
      setSleepTimerEnd(Date.now() + minutes * 60 * 1000);
    }
  }, []);

  const handleWave = useCallback(async () => {
    if (isWaveLoading || !userId) return;
    setIsWaveLoading(true);
    try {
      const recs = await fetchWave(userId, 10, moodFilter);
      if (recs.length > 0) {
        // Add all recommendations to queue with metadata
        for (const track of recs) {
          await sendAction("add", track.video_id, undefined, track);
        }
        // Play first if nothing playing
        if (!state.is_playing) {
          await sendAction("play", recs[0].video_id);
        }
        const s = await sendAction("status");
        setState(s);
      }
    } catch (e) {
      console.error("Wave error:", e);
    } finally {
      setIsWaveLoading(false);
    }
  }, [isWaveLoading, state.is_playing, userId, moodFilter]);

  const action = useCallback(
    async (act: string, trackId?: string, seekPos?: number, track?: Track) => {
      try {
        // ── Optimistic UI: instantly toggle play/pause icon ──
        if (act === "play" && !trackId) {
          setState((prev) => ({ ...prev, is_playing: true }));
        } else if (act === "pause") {
          setState((prev) => ({ ...prev, is_playing: false }));
        }

        if (act === "play") {
          // Show buffering spinner immediately if switching to a new track
          if (trackId && trackId !== currentTrackIdRef.current) {
            if (bufferingTimeoutRef.current) clearTimeout(bufferingTimeoutRef.current);
            setBuffering(true);
          }
          ensureEqualizerGraph();
          audioContextRef.current?.resume().catch(() => {});
          if (audioRef.current && audioRef.current.paused) {
            if (trackId && trackId !== currentTrackIdRef.current) {
              // Different track: just unlock audio context/element using the user gesture
              audioRef.current.play().then(() => audioRef.current?.pause()).catch((e) => {
                console.warn("Audio unlock play failed:", e?.message || e);
              });
            } else {
              // Same track: call softPlay immediately to satisfy gesture and unpause instantly
              softPlay(audioRef.current).catch((e) => {
                console.warn("softPlay failed:", e?.message || e);
                setBuffering(false);
              });
            }
          }
          // Ingest play event for AI learning
          const playTrack = track || state.current_track;
          if (playTrack) {
            ingestEvent("play", playTrack, undefined, "wave");
          }
        } else if (act === "pause") {
          if (audioRef.current && !audioRef.current.paused) {
            softPause(audioRef.current).catch(() => {});
          }
        } else if (act === "next" || act === "skip") {
          // Ingest skip event for AI learning
          if (state.current_track) {
            const listened = audioRef.current ? Math.round(audioRef.current.currentTime) : 0;
            ingestEvent("skip", state.current_track, listened, "wave");
          }
        }

        const s = await sendAction(act, trackId, seekPos, track);
        if (act === "seek" && seekPos !== undefined && audioRef.current) {
          audioRef.current.currentTime = seekPos;
        }
        setState(s);
      } catch (e: unknown) {
        console.error("Action error:", act, e);
        // Revert optimistic update on failure
        if (act === "play") setState((prev) => ({ ...prev, is_playing: false }));
        if (act === "pause") setState((prev) => ({ ...prev, is_playing: true }));
        const msg = e instanceof Error ? e.message : "Unknown error";
        if (msg.includes("timed out") || msg.includes("Failed to fetch")) {
          showToast("Connection lost — try again", "error");
        }
      }
    },
    [ensureEqualizerGraph, softPlay, softPause, state.current_track]
  );

  const updateQuality = useCallback(async (quality: string) => {
    try {
      const profile = await updateUserAudioSettings(quality);
      setUserProfile(profile);
    } catch (e) {
      console.error("Quality update failed", e);
    }
  }, []);

  const handlePlayAndOpenPlayer = useCallback((track: Track) => {
    action("play", track.video_id, undefined, track);
    setView("player");
  }, [action]);

  // Stable callbacks for memo'd children
  const handlePlayAllAndOpenPlayer = useCallback(async (tracks: Track[]) => {
    for (const t of tracks) await action("add", t.video_id, undefined, t);
    if (tracks.length) await action("play", tracks[0].video_id);
    setView("player");
  }, [action]);

  const handleTrackPlay = useCallback((t: Track) => {
    action("play", t.video_id);
  }, [action]);

  const handleTrackReorder = useCallback((fromIndex: number, toIndex: number) => {
    reorderQueue(fromIndex, toIndex).then(setState).catch(() => {});
  }, []);

  const handleTrackRemove = useCallback((t: Track) => {
    action("remove", t.video_id);
  }, [action]);

  const handleClearQueue = useCallback(() => {
    action("clear");
  }, [action]);

  const handlePlayPlaylist = useCallback(async (playlistId: number) => {
    setBuffering(true);
    try {
      const s = await playPlaylist(playlistId);
      setState(s);
      setView("player");
    } catch (e) {
      console.error("Play playlist error:", e);
    }
  }, []);

  const handlePartyPlayTrack = useCallback((t: Track) => {
    action("play", t.video_id, undefined, t);
  }, [action]);

  const handlePartyPlaybackAction = useCallback((playbackAction: string, track?: Track, position?: number) => {
    if (playbackAction === "play" && track) return action("play", track.video_id, undefined, track);
    if (playbackAction === "pause") return action("pause");
    if (playbackAction === "seek") return action("seek", undefined, position);
  }, [action]);

  const handleToggleSpectrum = useCallback(() => {
    setShowSpectrum(v => !v);
  }, []);

  const handleSpectrumStyleChange = useCallback((s: "bars" | "wave" | "circle") => {
    setSpectrumStyle(s);
  }, []);

  const handleAddToPlaylist = useCallback(() => {
    if (state.current_track) {
      setShowAddToPlaylist(true);
      fetchPlaylists(userId).then(setA2pPlaylists).catch(() => setA2pPlaylists([]));
    }
  }, [state.current_track, userId]);

  const handlePlayerPlayTrack = useCallback(async (t: Track) => {
    await action("add", t.video_id, undefined, t);
    await action("play", t.video_id);
  }, [action]);

  const handlePlayerPlayAll = useCallback(async (tracks: Track[]) => {
    for (const t of tracks) await action("add", t.video_id, undefined, t);
    if (tracks.length) await action("play", tracks[0].video_id);
  }, [action]);

  const handleLyricsBack = useCallback(() => {
    setView("player");
  }, []);

  const handleActionSheetClose = useCallback(() => {
    setActionSheetVisible(false);
    setActionSheetTrack(null);
  }, []);

  const handleMiniPlayerAction = useCallback((act: string) => {
    action(act);
  }, [action]);

  const handleMiniPlayerExpand = useCallback(() => {
    setView("player");
  }, []);

  // 3D Spatial Panner
  const handlePanChange = useCallback((value: number) => {
    setPanValue(value);
    const panner = pannerRef.current;
    const ctx = audioContextRef.current;
    if (panner && ctx) {
      panner.pan.setValueAtTime(panner.pan.value, ctx.currentTime);
      panner.pan.linearRampToValueAtTime(value, ctx.currentTime + 0.05);
    }
  }, []);

  // Playback Speed
  const handleSpeedChange = useCallback((speed: number) => {
    setPlaybackSpeed(speed);
    if (audioRef.current) {
      audioRef.current.playbackRate = speed;
    }
  }, []);

  // Bass Boost toggle
  const handleBassBoost = useCallback((on: boolean) => {
    setBassBoost(on);
    ensureEqualizerGraph();
    const ctx = audioContextRef.current;
    const filters = eqFiltersRef.current;
    if (!ctx || filters.length < 4) return;
    const now = ctx.currentTime;
    const profile = EQ_PRESETS[eqPreset] || EQ_PRESETS.flat;
    // Boost first 4 bands (sub-bass to low-mids) by +6dB
    for (let i = 0; i < 4; i++) {
      const base = profile.gains[i] ?? 0;
      const target = on ? base + 6 : base;
      filters[i].gain.setValueAtTime(filters[i].gain.value, now);
      filters[i].gain.setTargetAtTime(target, now, 0.15);
    }
  }, [ensureEqualizerGraph, eqPreset]);

  // ── Luxury Audio toggles ──
  const handleTapeWarmth = useCallback((on: boolean) => {
    setTapeWarmth(on);
    const node = tapeWarmthRef.current;
    if (node) node.curve = on ? createTapeCurve() : LINEAR_CURVE;
  }, []);

  const handleAirBand = useCallback((on: boolean) => {
    setAirBand(on);
    const node = airBandRef.current;
    const ctx = audioContextRef.current;
    if (node && ctx) {
      const now = ctx.currentTime;
      node.gain.setValueAtTime(node.gain.value, now);
      node.gain.setTargetAtTime(on ? 2 : 0, now, 0.15);
    }
  }, []);

  const handleStereoWiden = useCallback((on: boolean) => {
    setStereoWiden(on);
    const ctx = audioContextRef.current;
    const lr = stereoWidenLRRef.current;
    const rl = stereoWidenRLRef.current;
    if (ctx && lr && rl) {
      const now = ctx.currentTime;
      const v = on ? -0.15 : 0;
      lr.gain.setValueAtTime(lr.gain.value, now);
      lr.gain.setTargetAtTime(v, now, 0.15);
      rl.gain.setValueAtTime(rl.gain.value, now);
      rl.gain.setTargetAtTime(v, now, 0.15);
    }
  }, []);

  const handleSoftClip = useCallback((on: boolean) => {
    setSoftClip(on);
    const node = softClipRef.current;
    if (node) node.curve = on ? createSoftClipCurve() : LINEAR_CURVE;
  }, []);

  // ── Night Mode toggle ──
  const handleNightMode = useCallback((on: boolean) => {
    setNightMode(on);
    ensureEqualizerGraph();
    const comp = nightCompressorRef.current;
    const makeup = nightMakeupRef.current;
    const ctx = audioContextRef.current;
    if (!comp || !makeup || !ctx) return;
    const now = ctx.currentTime;
    if (on) {
      comp.threshold.setValueAtTime(comp.threshold.value, now);
      comp.threshold.setTargetAtTime(-30, now, 0.15);
      comp.ratio.setValueAtTime(comp.ratio.value, now);
      comp.ratio.setTargetAtTime(12, now, 0.15);
      comp.knee.setValueAtTime(comp.knee.value, now);
      comp.knee.setTargetAtTime(10, now, 0.15);
      makeup.gain.setValueAtTime(makeup.gain.value, now);
      makeup.gain.setTargetAtTime(dbToGain(6), now, 0.2);
    } else {
      comp.threshold.setValueAtTime(comp.threshold.value, now);
      comp.threshold.setTargetAtTime(0, now, 0.15);
      comp.ratio.setValueAtTime(comp.ratio.value, now);
      comp.ratio.setTargetAtTime(1, now, 0.15);
      comp.knee.setValueAtTime(comp.knee.value, now);
      comp.knee.setTargetAtTime(40, now, 0.15);
      makeup.gain.setValueAtTime(makeup.gain.value, now);
      makeup.gain.setTargetAtTime(1, now, 0.2);
    }
  }, [ensureEqualizerGraph]);

  // ── Virtual Room (reverb) toggles ──
  const handleReverb = useCallback((on: boolean) => {
    setReverbEnabled(on);
    ensureEqualizerGraph();
    const ctx = audioContextRef.current;
    const wet = reverbWetGainRef.current;
    const dry = reverbDryGainRef.current;
    if (!ctx || !wet || !dry) return;
    const now = ctx.currentTime;
    if (on) {
      const conv = reverbConvolverRef.current;
      if (conv) conv.buffer = generateImpulseResponse(ctx, reverbPreset);
      wet.gain.setValueAtTime(wet.gain.value, now);
      wet.gain.setTargetAtTime(reverbMix, now, 0.15);
      dry.gain.setValueAtTime(dry.gain.value, now);
      dry.gain.setTargetAtTime(1 - reverbMix * 0.5, now, 0.15);
    } else {
      wet.gain.setValueAtTime(wet.gain.value, now);
      wet.gain.setTargetAtTime(0, now, 0.15);
      dry.gain.setValueAtTime(dry.gain.value, now);
      dry.gain.setTargetAtTime(1, now, 0.15);
    }
  }, [ensureEqualizerGraph, reverbPreset, reverbMix]);

  const handleReverbPreset = useCallback((preset: RoomPreset) => {
    setReverbPreset(preset);
    const ctx = audioContextRef.current;
    const conv = reverbConvolverRef.current;
    if (ctx && conv && reverbEnabled) {
      conv.buffer = generateImpulseResponse(ctx, preset);
    }
  }, [reverbEnabled]);

  const handleReverbMix = useCallback((mix: number) => {
    setReverbMix(mix);
    const ctx = audioContextRef.current;
    const wet = reverbWetGainRef.current;
    const dry = reverbDryGainRef.current;
    if (!ctx || !wet || !dry || !reverbEnabled) return;
    const now = ctx.currentTime;
    wet.gain.setValueAtTime(wet.gain.value, now);
    wet.gain.setTargetAtTime(mix, now, 0.15);
    dry.gain.setValueAtTime(dry.gain.value, now);
    dry.gain.setTargetAtTime(1 - mix * 0.5, now, 0.15);
  }, [reverbEnabled]);

  // ── Karaoke Mode toggle ──
  const handleKaraokeMode = useCallback((on: boolean) => {
    setKaraokeMode(on);
    ensureEqualizerGraph();
    const ctx = audioContextRef.current;
    const wet = karaokeWetGainRef.current;
    const dry = karaokeDryGainRef.current;
    if (!ctx || !wet || !dry) return;
    const now = ctx.currentTime;
    wet.gain.setValueAtTime(wet.gain.value, now);
    wet.gain.setTargetAtTime(on ? 1 : 0, now, 0.15);
    dry.gain.setValueAtTime(dry.gain.value, now);
    dry.gain.setTargetAtTime(on ? 0 : 1, now, 0.15);
  }, [ensureEqualizerGraph]);

  // Restore luxury audio settings from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem("tma:luxury-audio");
      if (raw) {
        const s = JSON.parse(raw);
        if (s.tapeWarmth) handleTapeWarmth(true);
        if (s.airBand) handleAirBand(true);
        if (s.stereoWiden) handleStereoWiden(true);
        if (s.softClip) handleSoftClip(true);
        if (s.nightMode) handleNightMode(true);
        if (s.reverbEnabled) handleReverb(true);
        if (s.reverbPreset) setReverbPreset(s.reverbPreset);
        if (s.reverbMix !== undefined) setReverbMix(s.reverbMix);
        if (s.karaokeMode) handleKaraokeMode(true);
      }
    } catch {}
  }, [handleTapeWarmth, handleAirBand, handleStereoWiden, handleSoftClip, handleNightMode, handleReverb, handleKaraokeMode]);

  // ── Crossfade duration persistence ──
  const handleCrossfadeDuration = useCallback((sec: number) => {
    setCrossfadeDuration(sec);
    try { localStorage.setItem("tma:crossfade", String(sec)); } catch {}
  }, []);

  // ── Vinyl spin toggle persistence ──
  const handleCoverMode = useCallback((mode: "default" | "vinyl" | "cd" | "case") => {
    setCoverMode(mode);
    try { localStorage.setItem("tma:cover-mode", mode); } catch {}
  }, []);

  // Party Mode — bass boost + club EQ + slight speed up + luxury warmth & air
  const handlePartyMode = useCallback((on: boolean) => {
    setPartyMode(on);
    if (on) {
      setEqPreset("club");
      handleBassBoost(true);
      handleSpeedChange(1.02);
      handleTapeWarmth(true);
      handleAirBand(true);
    } else {
      handleBassBoost(false);
      handleSpeedChange(1);
      handleTapeWarmth(false);
      handleAirBand(false);
    }
  }, [handleBassBoost, handleSpeedChange, handleTapeWarmth, handleAirBand]);

  const showLyrics = (trackId: string) => {
    setLyricsTrackId(trackId);
    setView("lyrics");
  };

  const isTequila = theme.id === "tequila";
  const hasAudioControls = Boolean(userProfile?.is_premium || userProfile?.is_admin);

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      <ToastContainer />
      {isTequila && (
        <>
          <div
            style={{
              position: "fixed",
              top: -120,
              left: "50%",
              transform: "translateX(-50%)",
              width: 420,
              height: 220,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(255,213,79,0.22) 0%, rgba(255,167,38,0.12) 35%, rgba(255,167,38,0) 72%)",
              filter: "blur(22px)",
              zIndex: -1,
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "fixed",
              bottom: -90,
              right: -60,
              width: 280,
              height: 280,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(255,109,0,0.18) 0%, rgba(255,109,0,0.08) 40%, rgba(255,109,0,0) 72%)",
              filter: "blur(28px)",
              zIndex: -1,
              pointerEvents: "none",
            }}
          />
        </>
      )}
      {/* Theme Background Image */}
      {theme.bgImage && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundImage: `url(${theme.bgImage})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
            zIndex: -2,
            pointerEvents: "none",
          }}
        />
      )}
      {theme.bgOverlay && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: theme.bgOverlay,
            zIndex: -1,
            pointerEvents: "none",
          }}
        />
      )}
      {/* Animated Mesh Gradient Background (from cover colors) */}
      {state.current_track?.cover_url && !theme.bgImage && meshColors.length >= 3 && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: `
              radial-gradient(ellipse at 20% 20%, ${meshColors[0]} 0%, transparent 50%),
              radial-gradient(ellipse at 80% 30%, ${meshColors[1]} 0%, transparent 50%),
              radial-gradient(ellipse at 50% 80%, ${meshColors[2]} 0%, transparent 50%),
              ${theme.bgColor}
            `,
            animation: "meshRotate 20s ease-in-out infinite",
            zIndex: -1,
            pointerEvents: "none",
          }}
        />
      )}
      {state.current_track?.cover_url && !theme.bgImage && meshColors.length < 3 && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundImage: `url(${state.current_track.cover_url})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
            filter: "blur(60px) brightness(0.4)",
            transform: "scale(1.2)",
            zIndex: -1,
            pointerEvents: "none",
          }}
        />
      )}
      <div style={{ padding: "8px 12px", maxWidth: 480, margin: "0 auto", paddingBottom: view !== "player" && state.current_track ? 72 : 12 }}>

      {/* ON AIR Banner */}
      {broadcastLive && view !== "broadcast" && !liveBannerDismissed && (
        <div
          onClick={() => { setView("broadcast"); setLiveBannerDismissed(true); }}
          style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "10px 14px", borderRadius: 14, marginBottom: 8,
            background: "linear-gradient(135deg, rgba(255,50,50,0.15), rgba(255,100,50,0.1))",
            border: "1px solid rgba(255,50,50,0.25)",
            cursor: "pointer", animation: "live-banner-in 0.4s ease",
            position: "relative",
          }}
        >
          <span style={{
            width: 10, height: 10, borderRadius: "50%",
            background: "#ff3232", flexShrink: 0,
            animation: "live-dot-pulse 1.5s ease-in-out infinite",
            boxShadow: "0 0 8px rgba(255,50,50,0.6)",
          }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#ff4444" }}>ON AIR</div>
            <div style={{ fontSize: 11, color: theme.hintColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {broadcastDJ} in broadcast — tap to listen
            </div>
          </div>
          <IconBroadcast size={18} color="#ff4444" />
          <span
            onClick={(e) => { e.stopPropagation(); setLiveBannerDismissed(true); }}
            style={{
              position: "absolute", top: 4, right: 6,
              fontSize: 14, color: theme.hintColor, cursor: "pointer",
              padding: "2px 4px", lineHeight: 1,
            }}
          >x</span>
        </div>
      )}

      {/* Nav */}
      <div style={{
        position: "relative",
        marginBottom: isTequila ? 4 : 12,
        zIndex: 10,
      }}>
        <div style={{
          pointerEvents: "none",
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 22,
          zIndex: 1,
          borderRadius: 22,
          background: `linear-gradient(90deg, ${theme.bgColor}, transparent)`,
        }} />
        <div style={{
          pointerEvents: "none",
          position: "absolute",
          right: 0,
          top: 0,
          bottom: 0,
          width: 22,
          zIndex: 1,
          borderRadius: 22,
          background: `linear-gradient(270deg, ${theme.bgColor}, transparent)`,
        }} />
        <nav ref={navCarouselRef} className="luxury-carousel" style={{
          display: "flex",
          gap: isTequila ? 7 : 10,
          alignItems: "center",
          overflowX: "auto",
          overflowY: "hidden",
          WebkitOverflowScrolling: "touch",
          scrollbarWidth: "none",
          msOverflowStyle: "none",
          whiteSpace: "nowrap",
          scrollSnapType: "x proximity",
          scrollPaddingLeft: 12,
          scrollPaddingRight: 12,
          padding: isTequila ? "8px 12px" : "8px 12px",
          borderRadius: 24,
          background: isTequila
            ? "linear-gradient(135deg, rgba(40, 25, 15, 0.72), rgba(82, 45, 18, 0.38))"
            : `linear-gradient(135deg, ${theme.cardBg}, rgba(255,255,255,0.04))`,
          backdropFilter: "blur(18px) saturate(140%)",
          WebkitBackdropFilter: "blur(18px) saturate(140%)",
          border: isTequila
            ? "1px solid rgba(255, 213, 79, 0.16)"
            : `1px solid ${theme.accentAlpha}`,
          boxShadow: isTequila
            ? "0 10px 30px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,224,130,0.08)"
            : `0 10px 30px rgba(0,0,0,0.22), inset 0 1px 0 ${theme.accentAlpha}`,
          maxWidth: "100%",
          margin: "0 auto",
          position: "relative",
          zIndex: 2,
          touchAction: "pan-x",
        }}>
          {(["player", "foryou", "playlists", "party", "broadcast", "charts", "leaderboard", "battle", "feed", "wrapped", "sleep", "search", "profile"] as View[]).map((v) => {
            const isActive = view === v;
            const isParty = v === "party";
            return (
              <button
                key={v}
                data-view={v}
                className={`luxury-tab${isActive ? " is-active" : ""}${isParty ? " is-party" : ""}`}
                onClick={() => activateView(v)}
                style={{
                  padding: isTequila ? "9px 14px" : "9px 15px",
                  borderRadius: 18,
                  border: isActive
                    ? (isTequila ? "1px solid rgba(255,213,79,0.26)" : `1px solid ${theme.accent}`)
                    : (isTequila ? "1px solid rgba(255,255,255,0.06)" : "1px solid rgba(255,255,255,0.06)"),
                  background: isActive
                    ? (isParty
                        ? "linear-gradient(135deg, #ff6d00, #ffb300)"
                        : (isTequila
                            ? "linear-gradient(135deg, rgba(255,109,0,0.42), rgba(255,213,79,0.18))"
                            : `linear-gradient(135deg, ${accentColor}, ${accentColorAlpha})`))
                    : "linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))",
                  color: isActive
                    ? (isTequila ? "#ffe082" : "#fff")
                    : theme.textColor,
                  fontSize: isTequila ? 12 : 13,
                  fontWeight: isActive ? 700 : 500,
                  letterSpacing: isTequila ? 0.45 : 0.2,
                  cursor: "pointer",
                  transition: "all 0.35s ease",
                  flexShrink: 0,
                  whiteSpace: "nowrap",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  scrollSnapAlign: "start",
                  boxShadow: isActive
                    ? (isParty
                        ? "0 10px 24px rgba(255,109,0,0.28), inset 0 1px 0 rgba(255,255,255,0.18)"
                        : `0 10px 24px ${accentColorAlpha}, inset 0 1px 0 rgba(255,255,255,0.18)`)
                    : "inset 0 1px 0 rgba(255,255,255,0.08)",
                  textShadow: isActive ? "0 1px 10px rgba(0,0,0,0.18)" : "none",
                  position: "relative",
                  overflow: "hidden",
                  transform: isActive ? "translateY(-1px) scale(1.02)" : "translateY(0) scale(1)",
                }}
              >
                {v === "player" ? (<><IconMusicNote size={13} color="currentColor" /> Плеер</>) : v === "foryou" ? (<><IconDiscover size={13} color="currentColor" /> Для тебя</>) : v === "playlists" ? (<><IconMusic size={13} color="currentColor" /> Плейлисты</>) : v === "party" ? (<><IconParty size={13} color="currentColor" /> Party</>) : v === "charts" ? (<><IconChart size={13} color="currentColor" /> Чарты</>) : v === "leaderboard" ? (<><IconCrown size={13} color="currentColor" /> Рейтинг</>) : v === "battle" ? (<><IconFire size={13} color="currentColor" /> Батл</>) : v === "feed" ? (<><IconHeadphones size={13} color="currentColor" /> Лента</>) : v === "wrapped" ? (<><IconStar size={13} color="currentColor" filled /> Рекап</>) : v === "broadcast" ? (<><IconBroadcast size={13} color="currentColor" /> Эфир{broadcastLive && !isActive && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#ff3232", animation: "live-dot-pulse 1.5s ease-in-out infinite", boxShadow: "0 0 6px rgba(255,50,50,0.5)", marginLeft: 2 }} />}</>) : v === "sleep" ? (<><IconMoon size={13} color="currentColor" /> Sleep</>) : v === "profile" ? (<><IconUser size={13} color="currentColor" /> Профиль</>) : (<><IconSearch size={13} color="currentColor" /> Поиск</>)}
              </button>
            );
          })}
          {/* Theme switcher */}
          <button
            className="luxury-theme-chip"
            onClick={() => { try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.("light"); } catch {} switchTheme(); }}
            title={`Switch theme (${theme.name})`}
            style={{
              padding: "9px 12px",
              borderRadius: 18,
              border: `1px solid ${theme.accentAlpha}`,
              background: `linear-gradient(135deg, ${theme.accentAlpha}, rgba(255,255,255,0.02))`,
              color: theme.accent,
              fontSize: 11,
              fontWeight: 700,
              cursor: "pointer",
              transition: "all 0.35s ease",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              letterSpacing: 0.45,
              flexShrink: 0,
              scrollSnapAlign: "end",
              boxShadow: `0 8px 20px ${theme.accentAlpha}, inset 0 1px 0 rgba(255,255,255,0.14)`,
              position: "relative",
              overflow: "hidden",
            }}
          >
            {theme.id === "tequila" ? <IconThemeTequila size={14} /> :
             theme.id === "neon" ? <IconThemeNeon size={14} /> :
             theme.id === "midnight" ? <IconThemeMidnight size={14} /> :
             theme.id === "emerald" ? <IconThemeEmerald size={14} /> :
             <IconThemeBlackroom size={14} />}
          </button>
        </nav>
      </div>
      {(userProfile?.is_premium || userProfile?.is_admin) && (
        <div style={{ display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap", margin: theme.id === "tequila" ? "8px 0 2px" : "4px 0 10px" }}>
          {userProfile?.is_premium && (
            <span
              title="Premium"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 34,
                height: 34,
                borderRadius: 999,
                color: theme.id === "tequila" ? "#1a120b" : "#fff",
                background: theme.id === "tequila" ? "linear-gradient(135deg, #ffb300, #ffd54f)" : "linear-gradient(135deg, #7c4dff, #e040fb)",
                border: theme.id === "tequila" ? "1px solid rgba(255, 213, 79, 0.22)" : "1px solid rgba(179, 136, 255, 0.22)",
                boxShadow: theme.id === "tequila" ? "0 6px 18px rgba(255, 179, 0, 0.22)" : "0 6px 18px rgba(124, 77, 255, 0.22)",
              }}
            >
              <IconCrown size={16} color={theme.id === "tequila" ? "#1a120b" : "#fff"} />
            </span>
          )}
          {userProfile?.is_admin && (
            <span
              title="Admin"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 34,
                height: 34,
                borderRadius: 999,
                color: theme.id === "tequila" ? "#1a120b" : "#fff",
                background: theme.id === "tequila" ? "linear-gradient(135deg, #ff6d00, #ffd54f)" : "linear-gradient(135deg, #5e35b1, #7c4dff)",
                border: theme.id === "tequila" ? "1px solid rgba(255, 213, 79, 0.22)" : "1px solid rgba(179, 136, 255, 0.22)",
                boxShadow: theme.id === "tequila" ? "0 6px 18px rgba(255, 109, 0, 0.2)" : "0 6px 18px rgba(94, 53, 177, 0.24)",
              }}
            >
              <IconShield size={16} color={theme.id === "tequila" ? "#1a120b" : "#fff"} />
            </span>
          )}
        </div>
      )}
      {/* Theme label for TEQUILA */}
      {theme.id === "tequila" && view === "player" && (
        <div style={{
          textAlign: "center",
          margin: "10px auto 6px",
          padding: "8px 24px",
          maxWidth: 320,
          borderRadius: 16,
          background: "rgba(255, 213, 79, 0.06)",
          border: "1px solid rgba(255, 213, 79, 0.1)",
        }}>
          <div style={{
            fontSize: 14,
            fontWeight: 700,
            letterSpacing: 4,
            color: "#ffd54f",
            textShadow: "0 0 20px rgba(255, 167, 38, 0.3)",
          }}>𝐓 𝐄 𝐐 𝐔 𝐈 𝐋 𝐀  𝐌 𝐔 𝐒 𝐈 𝐂</div>
          <div style={{
            fontSize: 9,
            color: "#c8a882",
            marginTop: 3,
            letterSpacing: 2,
            textTransform: "uppercase",
          }}>inspired by 𝗧𝗘𝗤𝗨𝗜𝗟𝗔 𝗦𝗨𝗡𝗦𝗛𝗜𝗡𝗘.</div>
        </div>
      )}

      {isTequila && view === "player" && !state.current_track && (
        <div style={{
          margin: "12px auto 10px",
          maxWidth: 360,
          padding: "16px 18px",
          borderRadius: 22,
          background: "rgba(40, 25, 15, 0.48)",
          border: "1px solid rgba(255, 213, 79, 0.14)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
          textAlign: "center",
          boxShadow: "0 14px 40px rgba(0,0,0,0.18)",
        }}>
          <div style={{ fontSize: 12, letterSpacing: 3, color: "#ffd54f", marginBottom: 8 }}>SUNSET LUXURY MODE</div>
          <div style={{ fontSize: 15, lineHeight: 1.5, color: "#fef0e0", fontWeight: 600 }}>
            Выбери трек и включи атмосферу тёплого, дорогого, мягкого вайба.
          </div>
          <div style={{ fontSize: 11, color: "#c8a882", marginTop: 8 }}>
            amber glow · warm glass · premium motion
          </div>
        </div>
      )}

      {/* Views */}
      {view === "player" && (
        <ViewErrorBoundary viewName="Player" fallbackColor={theme.hintColor}>
        <>
          <Player state={state} onAction={action} onShowLyrics={showLyrics} accentColor={accentColor} accentColorAlpha={accentColorAlpha} onSleepTimer={handleSleepTimer} sleepTimerRemaining={sleepRemaining} audioDuration={audioDuration} onWave={handleWave} isWaveLoading={isWaveLoading} elapsed={elapsed} buffering={buffering} themeId={theme.id} isPremium={Boolean(userProfile?.is_premium)} isAdmin={Boolean(userProfile?.is_admin)} canUseAudioControls={hasAudioControls} quality={userProfile?.quality || "192"} eqPreset={eqPreset} onQualityChange={updateQuality} onEqPresetChange={setEqPreset} bassBoost={bassBoost} onBassBoost={handleBassBoost} partyMode={partyMode} onPartyMode={handlePartyMode} playbackSpeed={playbackSpeed} onSpeedChange={handleSpeedChange} panValue={panValue} onPanChange={handlePanChange} showSpectrum={showSpectrum} onToggleSpectrum={handleToggleSpectrum} spectrumStyle={spectrumStyle} onSpectrumStyleChange={handleSpectrumStyleChange} moodFilter={moodFilter} onMoodChange={setMoodFilter} bypassProcessing={bypassProcessing} onBypassToggle={handleBypass} tapeWarmth={tapeWarmth} onTapeWarmth={handleTapeWarmth} airBand={airBand} onAirBand={handleAirBand} stereoWiden={stereoWiden} onStereoWiden={handleStereoWiden} softClip={softClip} onSoftClip={handleSoftClip} nightMode={nightMode} onNightMode={handleNightMode} reverbEnabled={reverbEnabled} onReverb={handleReverb} reverbPreset={reverbPreset} onReverbPreset={handleReverbPreset} reverbMix={reverbMix} onReverbMix={handleReverbMix} karaokeMode={karaokeMode} onKaraokeMode={handleKaraokeMode} crossfadeDuration={crossfadeDuration} onCrossfadeDuration={handleCrossfadeDuration} coverMode={coverMode} onCoverMode={handleCoverMode} onAddToPlaylist={handleAddToPlaylist} onPlayTrack={handlePlayerPlayTrack} onPlayAll={handlePlayerPlayAll} />

          {/* Spectrum Visualizer */}
          {showSpectrum && state.current_track && (
            <div style={{
              margin: "12px auto",
              maxWidth: 360,
              padding: "12px",
              borderRadius: 22,
              background: isTequila ? "rgba(40, 25, 15, 0.55)" : "rgba(20, 20, 30, 0.6)",
              backdropFilter: "blur(16px)",
              border: isTequila ? "1px solid rgba(255, 213, 79, 0.15)" : "1px solid rgba(124, 77, 255, 0.15)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
            }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
                {(["bars", "wave", "circle"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpectrumStyle(s)}
                    style={{
                      padding: "4px 12px",
                      borderRadius: 12,
                      border: "none",
                      background: spectrumStyle === s
                        ? (isTequila ? "linear-gradient(135deg, rgba(255,109,0,0.4), rgba(255,213,79,0.25))" : accentColor)
                        : "rgba(255,255,255,0.08)",
                      color: spectrumStyle === s ? "#fff" : theme.hintColor,
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: "pointer",
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <SpectrumVisualizer
                analyser={analyserRef.current}
                isPlaying={state.is_playing}
                accentColor={accentColor}
                themeId={theme.id}
                width={336}
                height={100}
                style={spectrumStyle}
              />
            </div>
          )}

          {/* Radio Mode Toggle */}
          {state.current_track && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 12,
              margin: "8px 0",
            }}>
              <button
                onClick={() => {
                  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.("medium"); } catch {}
                  if (!radioMode) {
                    radioSeedRef.current = state.current_track?.video_id || null;
                    radioPlayedRef.current = state.current_track ? [state.current_track.video_id] : [];
                    setRadioMode(true);
                    showToast("Radio Mode ON — endless similar tracks");
                  } else {
                    setRadioMode(false);
                    radioSeedRef.current = null;
                    radioPlayedRef.current = [];
                    showToast("Radio Mode OFF");
                  }
                }}
                style={{
                  padding: "10px 20px",
                  borderRadius: 16,
                  border: radioMode
                    ? (isTequila ? "1px solid rgba(255,213,79,0.4)" : `1px solid ${accentColor}`)
                    : (isTequila ? "1px solid rgba(255,213,79,0.12)" : "1px solid rgba(255,255,255,0.08)"),
                  background: radioMode
                    ? (isTequila ? "linear-gradient(135deg, rgba(255,109,0,0.4), rgba(255,213,79,0.25))" : `linear-gradient(135deg, ${accentColor}, rgba(224,64,251,0.7))`)
                    : (isTequila ? "rgba(255,213,79,0.05)" : "rgba(255,255,255,0.04)"),
                  color: radioMode ? "#fff" : theme.hintColor,
                  fontSize: 13,
                  fontWeight: radioMode ? 700 : 600,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  transition: "all 0.3s ease",
                  boxShadow: radioMode
                    ? (isTequila ? "0 4px 20px rgba(255,143,0,0.3)" : `0 4px 20px ${accentColorAlpha}`)
                    : "none",
                }}
              >
                <IconRocket size={14} color={radioMode ? "#fff" : theme.hintColor} />
                {radioMode ? "Radio ON" : "Radio"}
              </button>
            </div>
          )}

          {state.queue.length > 0 && (
            <TrackList
              tracks={state.queue}
              currentIndex={state.position}
              onPlay={handleTrackPlay}
              onReorder={handleTrackReorder}
              onRemove={handleTrackRemove}
              onClearQueue={handleClearQueue}
              accentColor={accentColor}
              accentColorAlpha={accentColorAlpha}
              themeId={theme.id}
            />
          )}
        </>
        </ViewErrorBoundary>
      )}

      {view === "playlists" && <Suspense fallback={null}><ViewErrorBoundary viewName="Playlists" fallbackColor={theme.hintColor}><PlaylistView userId={userId} onPlayTrack={handlePlayAndOpenPlayer} onPlayPlaylist={handlePlayPlaylist} accentColor={accentColor} themeId={theme.id} currentTrack={state.current_track} /></ViewErrorBoundary></Suspense>}

      {view === "party" && (
        <Suspense fallback={null}><ViewErrorBoundary viewName="Party" fallbackColor={theme.hintColor}>
        userProfile?.is_admin ? (
          <PartyView userId={userId} onPlayTrack={handlePartyPlayTrack} onPlaybackAction={handlePartyPlaybackAction} accentColor={accentColor} themeId={theme.id} initialCode={partyCode} readOnlyMode={partyReadonly} />
        ) : (
          /* Coming Soon Banner for non-admins */
          <div style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            padding: "24px 16px",
            overflowY: "auto",
          }}>
            {/* Hero Card */}
            <div style={{
              background: isTequila
                ? "linear-gradient(135deg, rgba(255,109,0,0.2), rgba(255,213,79,0.12))"
                : "linear-gradient(135deg, rgba(124,77,255,0.2), rgba(168,85,247,0.12))",
              border: isTequila
                ? "1px solid rgba(255,213,79,0.25)"
                : "1px solid rgba(124,77,255,0.28)",
              borderRadius: 28,
              padding: "32px 24px",
              maxWidth: 400,
              width: "100%",
              backdropFilter: "blur(24px)",
              boxShadow: isTequila
                ? "0 24px 60px rgba(255,109,0,0.2)"
                : "0 24px 60px rgba(124,77,255,0.22)",
              marginBottom: 20,
            }}>
              {/* Rocket Icon */}
              <div style={{
                width: 80,
                height: 80,
                borderRadius: "50%",
                background: isTequila
                  ? "linear-gradient(135deg, #ff6d00, #ffb300)"
                  : "linear-gradient(135deg, #7c4dff, #a855f7)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 20px",
                boxShadow: isTequila
                  ? "0 16px 40px rgba(255,109,0,0.4)"
                  : "0 16px 40px rgba(124,77,255,0.45)",
              }}>
                <IconRocket size={40} color="#fff" />
              </div>
              {/* Title */}
              <h2 style={{
                fontSize: 28,
                fontWeight: 800,
                color: isTequila ? "#ffe082" : "#fff",
                margin: "0 0 8px",
                letterSpacing: 0.5,
                textAlign: "center",
              }}>Party Mode</h2>
              <div style={{
                fontSize: 13,
                fontWeight: 700,
                color: isTequila ? "#ffb74d" : "#a78bfa",
                marginBottom: 16,
                letterSpacing: 2,
                textTransform: "uppercase",
                textAlign: "center",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
              }}><IconRocket size={16} /> Скоро запуск!</div>
              {/* Tagline */}
              <p style={{
                fontSize: 15,
                lineHeight: 1.7,
                color: isTequila ? "#fef0e0" : "rgba(255,255,255,0.85)",
                margin: 0,
                textAlign: "center",
              }}>
                Слушай музыку с друзьями в реальном времени.<br/>
                Создавай комнаты, приглашай участников, голосуй за треки!
              </p>
            </div>

            {/* Features Grid */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
              maxWidth: 400,
              width: "100%",
              marginBottom: 20,
            }}>
              {/* Feature 1 — Sync */}
              <div style={{
                background: isTequila
                  ? "linear-gradient(135deg, rgba(40,25,15,0.7), rgba(60,35,18,0.5))"
                  : "linear-gradient(135deg, rgba(30,25,50,0.7), rgba(40,30,60,0.5))",
                border: isTequila ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(124,77,255,0.18)",
                borderRadius: 18,
                padding: "18px 14px",
                backdropFilter: "blur(16px)",
              }}>
                <div style={{ marginBottom: 8, color: isTequila ? "#ffd54f" : "#a78bfa" }}><IconHeadphones size={28} /></div>
                <div style={{ fontSize: 13, fontWeight: 700, color: isTequila ? "#ffe082" : "#fff", marginBottom: 4 }}>Синхрон</div>
                <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.65)", lineHeight: 1.4 }}>
                  Все слышат одну музыку в один момент. Идеальная синхронизация.
                </div>
              </div>
              {/* Feature 2 — Room */}
              <div style={{
                background: isTequila
                  ? "linear-gradient(135deg, rgba(40,25,15,0.7), rgba(60,35,18,0.5))"
                  : "linear-gradient(135deg, rgba(30,25,50,0.7), rgba(40,30,60,0.5))",
                border: isTequila ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(124,77,255,0.18)",
                borderRadius: 18,
                padding: "18px 14px",
                backdropFilter: "blur(16px)",
              }}>
                <div style={{ marginBottom: 8, color: isTequila ? "#ffd54f" : "#a78bfa" }}><IconHome size={28} /></div>
                <div style={{ fontSize: 13, fontWeight: 700, color: isTequila ? "#ffe082" : "#fff", marginBottom: 4 }}>Комнаты</div>
                <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.65)", lineHeight: 1.4 }}>
                  Создай свою или присоединись по коду. До 50 человек.
                </div>
              </div>
              {/* Feature 3 — Voting */}
              <div style={{
                background: isTequila
                  ? "linear-gradient(135deg, rgba(40,25,15,0.7), rgba(60,35,18,0.5))"
                  : "linear-gradient(135deg, rgba(30,25,50,0.7), rgba(40,30,60,0.5))",
                border: isTequila ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(124,77,255,0.18)",
                borderRadius: 18,
                padding: "18px 14px",
                backdropFilter: "blur(16px)",
              }}>
                <div style={{ marginBottom: 8, color: isTequila ? "#ffd54f" : "#a78bfa" }}><IconChart size={28} /></div>
                <div style={{ fontSize: 13, fontWeight: 700, color: isTequila ? "#ffe082" : "#fff", marginBottom: 4 }}>Голосование</div>
                <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.65)", lineHeight: 1.4 }}>
                  Голосуй за следующий трек. Демократия в действии!
                </div>
              </div>
              {/* Feature 4 — Chat */}
              <div style={{
                background: isTequila
                  ? "linear-gradient(135deg, rgba(40,25,15,0.7), rgba(60,35,18,0.5))"
                  : "linear-gradient(135deg, rgba(30,25,50,0.7), rgba(40,30,60,0.5))",
                border: isTequila ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(124,77,255,0.18)",
                borderRadius: 18,
                padding: "18px 14px",
                backdropFilter: "blur(16px)",
              }}>
                <div style={{ marginBottom: 8, color: isTequila ? "#ffd54f" : "#a78bfa" }}><IconChat size={28} /></div>
                <div style={{ fontSize: 13, fontWeight: 700, color: isTequila ? "#ffe082" : "#fff", marginBottom: 4 }}>Живой чат</div>
                <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.65)", lineHeight: 1.4 }}>
                  Общайся с участниками в реальном времени.
                </div>
              </div>
            </div>

            {/* Advanced Features List */}
            <div style={{
              background: isTequila
                ? "linear-gradient(135deg, rgba(40,25,15,0.6), rgba(50,30,15,0.4))"
                : "linear-gradient(135deg, rgba(25,20,45,0.6), rgba(35,28,55,0.4))",
              border: isTequila ? "1px solid rgba(255,213,79,0.12)" : "1px solid rgba(124,77,255,0.15)",
              borderRadius: 20,
              padding: "20px 18px",
              maxWidth: 400,
              width: "100%",
              backdropFilter: "blur(16px)",
              marginBottom: 20,
            }}>
              <div style={{
                fontSize: 11,
                fontWeight: 800,
                textTransform: "uppercase",
                letterSpacing: 1.8,
                color: isTequila ? "#c8a882" : "rgba(255,255,255,0.5)",
                marginBottom: 14,
              }}>Расширенные возможности</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {[
                  { icon: <IconMic size={18} />, title: "DJ Mode", desc: "Управляй очередью как диджей. Микшируй треки, используй переходы." },
                  { icon: <IconRobot size={18} />, title: "AI Auto-DJ", desc: "Умный подбор следующих треков на основе вкусов участников." },
                  { icon: <IconFire size={18} />, title: "Реакции", desc: "Отправляй огонь, сердечки и другие эмоции прямо во время трека." },
                  { icon: <IconTV size={18} />, title: "TV Mode", desc: "Выведи пати на большой экран. Идеально для вечеринок." },
                  { icon: <IconStage size={18} />, title: "Stage Mode", desc: "Полноэкранный режим с визуализацией и текстом песен." },
                  { icon: <IconCrown size={18} />, title: "Co-host", desc: "Назначай соведущих с правами управления плейлистом." },
                  { icon: <IconClipboard size={18} />, title: "История", desc: "Сохраняй плейлисты пати и смотри статистику после." },
                  { icon: <IconLink size={18} />, title: "Шеринг", desc: "Приглашай друзей одной ссылкой или QR-кодом." },
                ].map((f, i) => (
                  <div key={i} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                    <div style={{
                      width: 32,
                      height: 32,
                      borderRadius: 10,
                      background: isTequila
                        ? "linear-gradient(135deg, rgba(255,109,0,0.25), rgba(255,213,79,0.15))"
                        : "linear-gradient(135deg, rgba(124,77,255,0.25), rgba(168,85,247,0.15))",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                      color: isTequila ? "#ffd54f" : "#a78bfa",
                    }}>{f.icon}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: isTequila ? "#ffe082" : "#fff", marginBottom: 2 }}>{f.title}</div>
                      <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.6)", lineHeight: 1.4 }}>{f.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* CTA Footer */}
            <div style={{
              textAlign: "center",
              padding: "12px 20px",
              background: isTequila
                ? "linear-gradient(135deg, rgba(255,109,0,0.15), rgba(255,213,79,0.08))"
                : "linear-gradient(135deg, rgba(124,77,255,0.15), rgba(168,85,247,0.08))",
              borderRadius: 16,
              maxWidth: 400,
              width: "100%",
            }}>
              <div style={{ fontSize: 13, color: isTequila ? "#fef0e0" : "rgba(255,255,255,0.85)", marginBottom: 4, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                <IconBell size={14} /> Следи за обновлениями!
              </div>
              <div style={{ fontSize: 11, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.5)" }}>
                Party Mode уже на финальном этапе тестирования
              </div>
            </div>
          </div>
        )
        </ViewErrorBoundary></Suspense>
      )}

      {view === "foryou" && <Suspense fallback={null}><ViewErrorBoundary viewName="For You" fallbackColor={theme.hintColor}><ForYouView userId={userId} currentTrack={state.current_track} onPlayTrack={handlePlayAndOpenPlayer} onPlayAll={handlePlayAllAndOpenPlayer} accentColor={accentColor} themeId={theme.id} /></ViewErrorBoundary></Suspense>}

      {view === "charts" && <Suspense fallback={null}><ViewErrorBoundary viewName="Charts" fallbackColor={theme.hintColor}><ChartsView userId={userId} onPlayTrack={handlePlayAndOpenPlayer} accentColor={accentColor} themeId={theme.id} /></ViewErrorBoundary></Suspense>}

      {view === "search" && <SearchBar onSelect={handlePlayAndOpenPlayer} accentColor={accentColor} themeId={theme.id} />}

      {view === "leaderboard" && <Suspense fallback={null}><LeaderboardView userId={userId} accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "battle" && <Suspense fallback={null}><BattleView userId={userId} accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "feed" && <Suspense fallback={null}><ActivityFeedView userId={userId} onPlayTrack={handlePlayAndOpenPlayer} accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "wrapped" && <Suspense fallback={null}><WrappedView userId={userId} onPlayTrack={handlePlayAndOpenPlayer} accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "sleep" && <Suspense fallback={null}><SleepSoundsView accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "broadcast" && <Suspense fallback={null}><ViewErrorBoundary viewName="Broadcast" fallbackColor={theme.hintColor}><LiveRadioView userId={userId} isAdmin={Boolean(userProfile?.is_admin)} accentColor={accentColor} themeId={theme.id} /></ViewErrorBoundary></Suspense>}

      {view === "profile" && <Suspense fallback={null}><ProfileView userId={userId} username={user?.username} firstName={user?.first_name} isPremium={Boolean(userProfile?.is_premium)} onPlayTrack={handlePlayAndOpenPlayer} accentColor={accentColor} themeId={theme.id} /></Suspense>}

      {view === "lyrics" && lyricsTrackId && (
        <Suspense fallback={null}><LyricsView trackId={lyricsTrackId} elapsed={elapsed} onBack={handleLyricsBack} accentColor={accentColor} themeId={theme.id} /></Suspense>
      )}
      </div>

      {/* Add to Playlist — bottom sheet modal */}
      {showAddToPlaylist && state.current_track && (
        <div onClick={() => setShowAddToPlaylist(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 10000, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
          <div onClick={(e: JSX.TargetedMouseEvent<HTMLDivElement>) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 420, maxHeight: "60vh", overflowY: "auto", padding: "16px 16px 24px",
              borderRadius: "20px 20px 0 0",
              background: isTequila ? "rgba(40, 25, 15, 0.95)" : "var(--tg-theme-bg-color, #1a1a2e)",
              border: isTequila ? "1px solid rgba(255,213,79,0.15)" : "1px solid rgba(255,255,255,0.08)",
              backdropFilter: "blur(20px)",
            }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: theme.hintColor, opacity: 0.3, margin: "0 auto 12px" }} />
            <div style={{ fontSize: 13, color: theme.hintColor, marginBottom: 4 }}>Добавить в плейлист</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)", marginBottom: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {state.current_track.artist} — {state.current_track.title}
            </div>
            {a2pPlaylists.length === 0 ? (
              <div style={{ textAlign: "center", color: theme.hintColor, padding: 20 }}>Нет плейлистов</div>
            ) : (
              a2pPlaylists.map((p) => (
                <button key={p.id} onClick={async () => {
                    if (!state.current_track) return;
                    setA2pAdding(p.id);
                    try { await addTrackToPlaylist(p.id, state.current_track); } catch {}
                    setA2pAdding(null);
                    setShowAddToPlaylist(false);
                  }} disabled={a2pAdding === p.id}
                  style={{
                    display: "flex", alignItems: "center", width: "100%", padding: "10px 14px",
                    borderRadius: 12, border: isTequila ? "1px solid rgba(255,213,79,0.1)" : "1px solid rgba(255,255,255,0.06)",
                    background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
                    marginBottom: 6, cursor: "pointer", textAlign: "left",
                    opacity: a2pAdding === p.id ? 0.5 : 1,
                  }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: isTequila ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))" : `linear-gradient(135deg, ${accentColor}, rgba(124,77,255,0.3))`, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                    <IconMusic size={16} color="#fff" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, color: isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)" }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: theme.hintColor }}>{p.track_count} треков</div>
                  </div>
                  {a2pAdding === p.id ? <IconSpinner size={16} color={theme.hintColor} /> : <IconPlus size={16} color={isTequila ? "#ffd54f" : accentColor} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Action Sheet — context menu for tracks */}
      <ActionSheet
        track={actionSheetTrack}
        visible={actionSheetVisible}
        onClose={handleActionSheetClose}
        accentColor={accentColor}
        themeId={theme.id}
        onAction={(actionId, t) => {
          switch (actionId) {
            case "play":
              action("play", t.video_id, undefined, t);
              setView("player");
              break;
            case "queue":
              action("add", t.video_id, undefined, t);
              showToast("Added to queue");
              break;
            case "playlist":
              setShowAddToPlaylist(true);
              fetchPlaylists(userId).then(setA2pPlaylists).catch(() => {});
              break;
            case "similar":
              fetchSimilar(t.video_id, 10).then(async (similar) => {
                if (similar.length > 0) {
                  for (const s of similar) await sendAction("add", s.video_id, undefined, s);
                  showToast(`Added ${similar.length} similar tracks`);
                }
              }).catch(() => {});
              break;
            case "radio":
              radioSeedRef.current = t.video_id;
              radioPlayedRef.current = [t.video_id];
              setRadioMode(true);
              action("play", t.video_id, undefined, t);
              setView("player");
              showToast("Radio mode ON");
              break;
            case "share": {
              const text = `${t.title} — ${t.artist}`;
              const url = `https://t.me/TSmymusicbot_bot/app?startapp=play_${t.video_id}`;
              try {
                window.Telegram?.WebApp?.openTelegramLink?.(
                  `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`
                );
              } catch {
                window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`, "_blank");
              }
              break;
            }
          }
        }}
      />

      {/* Floating Mini-Player (visible when NOT on Player view) */}
      {view !== "player" && state.current_track && (
        <MiniPlayer
          state={state}
          accentColor={accentColor}
          themeId={theme.id}
          elapsed={elapsed}
          audioDuration={audioDuration}
          onAction={handleMiniPlayerAction}
          onExpand={handleMiniPlayerExpand}
        />
      )}

      <style>{`
        @keyframes live-dot-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.8); }
        }
        @keyframes live-banner-in {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}


