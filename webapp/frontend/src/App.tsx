import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { PlaylistView } from "./components/PlaylistView";
import { ChartsView } from "./components/ChartsView";
import { SearchBar } from "./components/SearchBar";
import { LyricsView } from "./components/LyricsView";
import { MiniPlayer } from "./components/MiniPlayer";
import { SpectrumVisualizer } from "./components/SpectrumVisualizer";
import { IconCrown, IconShield, IconMoon, IconLime, IconSunrise, IconMusicNote, IconMusic, IconPlaySmall, IconDiamond, IconSearch, IconSpectrum, IconChart } from "./components/Icons";
import { fetchPlayerState, sendAction, getStreamUrl, reorderQueue, fetchWave, fetchUserProfile, updateUserAudioSettings, type EqPreset, type PlayerState, type Track, type UserProfile } from "./api";
import { extractDominantColor, rgbToCSS, rgbaToCSS } from "./colorExtractor";
import { getStreamUrl as getCachedStreamUrl, prefetchTracks } from "./offlineCache";
import { themes, getThemeById, getSavedThemeId, saveThemeId, type Theme } from "./themes";

type View = "player" | "playlists" | "charts" | "search" | "lyrics";

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
    gains: [5.2, 4.8, 3.6, 2, 0.6, -0.8, -1.2, -1.6, -0.6, 0.8],
    preamp: -2.5,
    makeup: 0.35,
  },
  vocal: {
    gains: [-2, -1.6, -0.8, 0.6, 2.4, 3.8, 3.6, 2, 0.4, -0.6],
    preamp: -1.4,
    makeup: 0.28,
  },
  club: {
    gains: [3.8, 2.8, 1.2, -0.8, -1.4, 0.6, 2, 3, 2.6, 1],
    preamp: -2,
    makeup: 0.42,
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
    gains: [4.2, 3.6, 2.2, 0.4, -1.2, -0.4, 1.6, 3.2, 4, 2.4],
    preamp: -2.2,
    makeup: 0.4,
  },
  vocal_boost: {
    gains: [-2.8, -2.2, -1, 0.6, 2.6, 4.2, 4.8, 3, 0.6, -0.4],
    preamp: -1.6,
    makeup: 0.32,
  },
};

// Per-band Q factor: wide on extremes, precise in mids (studio practice)
const EQ_Q: number[] = [0.6, 0.7, 0.85, 1.0, 1.2, 1.2, 1.1, 0.9, 0.75, 0.6];

function dbToGain(value: number): number {
  return Math.pow(10, value / 20);
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
  const user = window.Telegram?.WebApp?.initDataUnsafe?.user;
  const userId = user?.id ?? 0;

  const [view, setView] = useState<View>("player");
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
  const [sleepTimerEnd, setSleepTimerEnd] = useState<number | null>(null);
  const [sleepRemaining, setSleepRemaining] = useState<number | null>(null);
  const [audioDuration, setAudioDuration] = useState(0);
  const [isWaveLoading, setIsWaveLoading] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [eqPreset, setEqPreset] = useState<EqPreset>(() => getSavedEqPreset());
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
  const subsonicFilterRef = useRef<BiquadFilterNode | null>(null);
  const compressorRef = useRef<DynamicsCompressorNode | null>(null);

  // ─── Soft play/pause: ramp outputGain to avoid clicks through EQ/compressor chain ──
  const softPause = useCallback(async (audio: HTMLAudioElement) => {
    const ctx = audioContextRef.current;
    const outGain = eqOutputGainRef.current;
    if (ctx && outGain && !audio.paused) {
      const t = ctx.currentTime;
      outGain.gain.setValueAtTime(outGain.gain.value, t);
      outGain.gain.linearRampToValueAtTime(0, t + 0.06);
      await new Promise(r => setTimeout(r, 70));
    }
    audio.pause();
  }, []);

  const softPlay = useCallback(async (audio: HTMLAudioElement) => {
    const ctx = audioContextRef.current;
    const outGain = eqOutputGainRef.current;
    if (ctx && outGain) {
      outGain.gain.setValueAtTime(0, ctx.currentTime);
    }
    await audio.play().catch(() => {});
    if (ctx && outGain) {
      const t = ctx.currentTime;
      outGain.gain.setValueAtTime(0, t);
      outGain.gain.linearRampToValueAtTime(1, t + 0.08);
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
    audio.addEventListener("waiting", () => setBuffering(true));
    audio.addEventListener("playing", () => setBuffering(false));
    audio.addEventListener("canplay", () => setBuffering(false));
    audio.addEventListener("error", () => setBuffering(false));

    audio.addEventListener("ended", () => {
      // Don't swap audio elements — it breaks AudioContext source connection.
      // Cache + prefetch ensures the next track loads almost instantly.
      sendAction("next").then(setState).catch(() => {});
    });
    audio.addEventListener("timeupdate", () => {
      const t = Math.floor(audio.currentTime);
      elapsedRef.current = t;
      setElapsed(t);

      // Gapless: preload next track 30 seconds before end
      if (audio.duration && audio.duration - audio.currentTime < 30 && audio.duration > 35) {
        const nextIdx = (state.position + 1) % state.queue.length;
        if (state.queue.length > 1 && preloadRef.current) {
          const nextTrack = state.queue[nextIdx];
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

    return () => { audio.pause(); audio.src = ""; preload.src = ""; };
  }, []);

  const ensureEqualizerGraph = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (sourceNodeRef.current && eqFiltersRef.current.length) return;

    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;

    const ctx = audioContextRef.current || new AudioContextCtor();
    audioContextRef.current = ctx;

    if (!sourceNodeRef.current) {
      const source = ctx.createMediaElementSource(audio);
      const crossfadeGain = ctx.createGain();
      const inputGain = ctx.createGain();
      const outputGain = ctx.createGain();

      // ── Subsonic filter: HPF @ 20Hz removes inaudible rumble ──
      const subsonicFilter = ctx.createBiquadFilter();
      subsonicFilter.type = "highpass";
      subsonicFilter.frequency.value = 20;
      subsonicFilter.Q.value = 0.7;
      subsonicFilterRef.current = subsonicFilter;

      // ── 10-band parametric EQ with studio Q values ──
      const filters = EQ_BANDS.map((freq, idx) => {
        const filter = ctx.createBiquadFilter();
        filter.type = idx === 0 ? "lowshelf" : idx === EQ_BANDS.length - 1 ? "highshelf" : "peaking";
        filter.frequency.value = freq;
        filter.Q.value = EQ_Q[idx];
        return filter;
      });

      // ── Gentle glue compressor — soft knee + slow attack to avoid transient clicks ──
      const compressor = ctx.createDynamicsCompressor();
      compressor.threshold.value = -18;
      compressor.knee.value = 30;
      compressor.ratio.value = 2;
      compressor.attack.value = 0.08;
      compressor.release.value = 0.25;
      compressorRef.current = compressor;

      // ── Stereo panner for 3D spatial audio ──
      const panner = ctx.createStereoPanner();
      panner.pan.value = 0;

      // ── Real-time analyser for spectrum visualizer ──
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.82;

      // ── Signal chain: source → crossfade → preamp → HPF → EQ → compressor → panner → analyser → output ──
      source.connect(crossfadeGain);
      crossfadeGain.connect(inputGain);
      inputGain.connect(subsonicFilter);

      let node: AudioNode = subsonicFilter;
      filters.forEach((filter) => {
        node.connect(filter);
        node = filter;
      });
      node.connect(compressor);
      compressor.connect(panner);
      panner.connect(analyser);
      analyser.connect(outputGain);
      outputGain.connect(ctx.destination);

      sourceNodeRef.current = source;
      eqFiltersRef.current = filters;
      eqInputGainRef.current = inputGain;
      eqOutputGainRef.current = outputGain;
      crossfadeGainRef.current = crossfadeGain;
      analyserRef.current = analyser;
      pannerRef.current = panner;
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
    // Fade out → switch nodes → fade in (no click)
    outputGain.gain.setValueAtTime(outputGain.gain.value, now);
    outputGain.gain.linearRampToValueAtTime(0, now + 0.06);
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
      }
      const t2 = ctx.currentTime;
      outputGain.gain.setValueAtTime(0, t2);
      outputGain.gain.linearRampToValueAtTime(1, t2 + 0.08);
    }, 70);
  }, [ensureEqualizerGraph, applyEqPreset, eqPreset, panValue]);

  useEffect(() => {
    try {
      localStorage.setItem(EQ_STORAGE_KEY, eqPreset);
    } catch {}
    applyEqPreset(eqPreset);
  }, [eqPreset, applyEqPreset]);

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
      setBuffering(true);

      // Resume AudioContext if suspended (required on mobile after user gesture)
      const ctx = audioContextRef.current;
      if (ctx && ctx.state === "suspended") {
        await ctx.resume().catch(() => {});
      }

      // Crossfade out (120ms) before switching source — exponential for smooth hearing
      const cfGain = crossfadeGainRef.current;
      if (ctx && cfGain && !audio.paused) {
        const t = ctx.currentTime;
        cfGain.gain.setValueAtTime(cfGain.gain.value, t);
        cfGain.gain.exponentialRampToValueAtTime(0.001, t + 0.12);
        await new Promise(r => setTimeout(r, 130));
      }

      audio.pause();
      // Ensure outputGain is at 0 during source swap to prevent any click
      const outGain = eqOutputGainRef.current;
      if (ctx && outGain) {
        outGain.gain.setValueAtTime(0, ctx.currentTime);
      }
      const apiUrl = getStreamUrl(track.video_id);
      const cachedUrl = await getCachedStreamUrl(track.video_id, apiUrl);
      audio.src = cachedUrl;
      audio.load();
      
      if (state.is_playing) {
        await audio.play().catch(() => {});
      }

      // Crossfade in (300ms) — smooth ramp from zero through both gains
      if (ctx && cfGain) {
        const t = ctx.currentTime;
        cfGain.gain.setValueAtTime(0.001, t);
        cfGain.gain.exponentialRampToValueAtTime(1, t + 0.3);
      }
      if (ctx && outGain) {
        const t = ctx.currentTime;
        outGain.gain.setValueAtTime(0, t);
        outGain.gain.linearRampToValueAtTime(1, t + 0.15);
      }

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
    };
    
    loadAudio().then(async () => {
      if (state.is_playing && audio.paused) {
        await softPlay(audio);
      } else if (!state.is_playing && !audio.paused) {
        await softPause(audio);
      }
    }).catch((e) => {
      console.error("Audio playback error:", e);
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
      extractDominantColor(coverUrl).then((color) => {
        setAccentColor(rgbToCSS(color));
        setAccentColorAlpha(rgbaToCSS(color, 0.4));
      });
    } else {
      setAccentColor(theme.accent);
      setAccentColorAlpha(theme.accentAlpha);
    }
  }, [state.current_track?.cover_url, theme]);

  useEffect(() => {
    if (userId) {
      fetchUserProfile().then(setUserProfile).catch(() => {});
      fetchPlayerState(userId).then((s) => {
        // On initial load, force paused state — user must press play
        setState({ ...s, is_playing: false });
      }).catch(() => {});
    }
    // Handle deep link from share: startapp=play_VIDEOID
    const startParam = window.Telegram?.WebApp?.initDataUnsafe?.start_param;
    if (startParam && startParam.startsWith("play_")) {
      const videoId = startParam.slice(5);
      if (videoId) {
        sendAction("play", videoId).then(setState).catch(() => {});
      }
    }
  }, [userId]);
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
        // Add all recommendations to queue
        for (const track of recs) {
          await sendAction("add", track.video_id);
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
        if (act === "play") {
          ensureEqualizerGraph();
          audioContextRef.current?.resume().catch(() => {});
          if (audioRef.current && audioRef.current.paused) {
            if (trackId && trackId !== currentTrackIdRef.current) {
              // Different track: just unlock audio context/element using the user gesture
              audioRef.current.play().then(() => audioRef.current?.pause()).catch(() => {});
            } else {
              // Same track: call softPlay immediately to satisfy gesture and unpause instantly
              softPlay(audioRef.current).catch(() => {});
            }
          }
        } else if (act === "pause") {
          if (audioRef.current && !audioRef.current.paused) {
            softPause(audioRef.current).catch(() => {});
          }
        }
        
        const s = await sendAction(act, trackId, seekPos, track);
        if (act === "seek" && seekPos !== undefined && audioRef.current) {
          audioRef.current.currentTime = seekPos;
        }
        setState(s);
      } catch (e) {
        console.error("Action error:", act, e);
      }
    },
    [ensureEqualizerGraph, softPlay, softPause]
  );

  const updateQuality = useCallback(async (quality: string) => {
    try {
      const profile = await updateUserAudioSettings(quality);
      setUserProfile(profile);
    } catch (e) {
      console.error("Quality update failed", e);
    }
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

  // Party Mode — bass boost + club EQ + slight speed up
  const handlePartyMode = useCallback((on: boolean) => {
    setPartyMode(on);
    if (on) {
      setEqPreset("club");
      handleBassBoost(true);
      handleSpeedChange(1.02);
    } else {
      handleBassBoost(false);
      handleSpeedChange(1);
    }
  }, [handleBassBoost, handleSpeedChange]);

  const showLyrics = (trackId: string) => {
    setLyricsTrackId(trackId);
    setView("lyrics");
  };

  const isTequila = theme.id === "tequila";
  const hasAudioControls = Boolean(userProfile?.is_premium || userProfile?.is_admin);

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
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
          }}
        />
      )}
      {/* Glassmorphism Background (cover blur) */}
      {state.current_track?.cover_url && !theme.bgImage && (
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
          }}
        />
      )}
      <div style={{ padding: "8px 12px", maxWidth: 480, margin: "0 auto", paddingBottom: view !== "player" && state.current_track ? 72 : 12 }}>
      {/* Nav */}
      <nav style={{
        display: "flex",
        gap: 8,
        marginBottom: isTequila ? 4 : 12,
        justifyContent: "center",
        alignItems: "center",
        ...(isTequila ? {
          padding: "6px 12px",
          borderRadius: 22,
          background: "rgba(40, 25, 15, 0.5)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          border: "1px solid rgba(255, 213, 79, 0.12)",
          maxWidth: 380,
          margin: "0 auto 4px",
        } : {}),
      }}>
        {(["player", "playlists", "charts", "search"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            style={{
              padding: isTequila ? "7px 16px" : "6px 14px",
              borderRadius: isTequila ? 18 : 16,
              border: isTequila && view === v ? "1px solid rgba(255,213,79,0.3)" : "none",
              background: view === v
                ? (isTequila ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))" : accentColor)
                : theme.navInactiveBg,
              color: view === v
                ? (isTequila ? "#ffd54f" : "#fff")
                : theme.hintColor,
              fontSize: 13,
              fontWeight: isTequila && view === v ? 600 : 400,
              letterSpacing: isTequila ? 0.5 : 0,
              cursor: "pointer",
              transition: "all 0.4s ease",
            }}
          >
            {v === "player" ? (<><IconMusicNote size={12} color="currentColor" /> Плеер</>) : v === "playlists" ? (<><IconMusic size={12} color="currentColor" /> Плейлисты</>) : v === "charts" ? (<><IconChart size={12} color="currentColor" /> Чарты</>) : (<><IconSearch size={12} color="currentColor" /> Поиск</>)}
          </button>
        ))}
        {/* Theme switcher */}
        <button
          onClick={switchTheme}
          title={`Switch theme (${theme.name})`}
          style={{
            padding: "6px 10px",
            borderRadius: 16,
            border: `1px solid ${theme.accentAlpha}`,
            background: `linear-gradient(135deg, ${theme.accentAlpha}, transparent)`,
            color: theme.accent,
            fontSize: 11,
            fontWeight: 600,
            cursor: "pointer",
            transition: "all 0.4s ease",
            display: "flex",
            alignItems: "center",
            gap: 4,
            letterSpacing: 0.3,
          }}
        >
          {theme.id === "tequila" ? <IconLime size={14} /> :
           theme.id === "neon" ? <IconDiamond size={14} /> :
           theme.id === "midnight" ? <IconMoon size={14} /> :
           theme.id === "emerald" ? <IconPlaySmall size={14} /> :
           <IconMoon size={14} />}
        </button>
      </nav>
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
        <>
          <Player state={state} onAction={action} onShowLyrics={showLyrics} accentColor={accentColor} accentColorAlpha={accentColorAlpha} onSleepTimer={handleSleepTimer} sleepTimerRemaining={sleepRemaining} audioDuration={audioDuration} onWave={handleWave} isWaveLoading={isWaveLoading} elapsed={elapsed} buffering={buffering} themeId={theme.id} isPremium={Boolean(userProfile?.is_premium)} isAdmin={Boolean(userProfile?.is_admin)} canUseAudioControls={hasAudioControls} quality={userProfile?.quality || "192"} eqPreset={eqPreset} onQualityChange={updateQuality} onEqPresetChange={setEqPreset} bassBoost={bassBoost} onBassBoost={handleBassBoost} partyMode={partyMode} onPartyMode={handlePartyMode} playbackSpeed={playbackSpeed} onSpeedChange={handleSpeedChange} panValue={panValue} onPanChange={handlePanChange} showSpectrum={showSpectrum} onToggleSpectrum={() => setShowSpectrum(v => !v)} spectrumStyle={spectrumStyle} onSpectrumStyleChange={(s: "bars" | "wave" | "circle") => setSpectrumStyle(s)} moodFilter={moodFilter} onMoodChange={setMoodFilter} bypassProcessing={bypassProcessing} onBypassToggle={handleBypass} />

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

          {state.queue.length > 0 && (
            <TrackList
              tracks={state.queue}
              currentIndex={state.position}
              onPlay={(t) => action("play", t.video_id)}
              onReorder={(fromIndex, toIndex) => {
                reorderQueue(fromIndex, toIndex).then(setState).catch(() => {});
              }}
              onRemove={(t) => {
                action("remove", t.video_id);
              }}
              accentColor={accentColor}
              accentColorAlpha={accentColorAlpha}
              themeId={theme.id}
            />
          )}
        </>
      )}

      {view === "playlists" && <PlaylistView userId={userId} onPlayTrack={(t) => { action("play", t.video_id, undefined, t); setView("player"); }} accentColor={accentColor} themeId={theme.id} currentTrack={state.current_track} />}

      {view === "charts" && <ChartsView userId={userId} onPlayTrack={(t) => { action("play", t.video_id, undefined, t); setView("player"); }} accentColor={accentColor} themeId={theme.id} />}

      {view === "search" && <SearchBar onSelect={(t) => { action("play", t.video_id, undefined, t); setView("player"); }} accentColor={accentColor} themeId={theme.id} />}

      {view === "lyrics" && lyricsTrackId && (
        <LyricsView trackId={lyricsTrackId} elapsed={elapsed} onBack={() => setView("player")} accentColor={accentColor} themeId={theme.id} />
      )}
      </div>

      {/* Floating Mini-Player (visible when NOT on Player view) */}
      {view !== "player" && state.current_track && (
        <MiniPlayer
          state={state}
          accentColor={accentColor}
          themeId={theme.id}
          onAction={(act) => action(act)}
          onExpand={() => setView("player")}
        />
      )}
    </div>
  );
}
