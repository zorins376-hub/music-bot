import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { PlaylistView } from "./components/PlaylistView";
import { SearchBar } from "./components/SearchBar";
import { LyricsView } from "./components/LyricsView";
import { MiniPlayer } from "./components/MiniPlayer";
import { fetchPlayerState, sendAction, getStreamUrl, reorderQueue, fetchWave, type PlayerState, type Track } from "./api";
import { extractDominantColor, rgbToCSS, rgbaToCSS } from "./colorExtractor";
import { getStreamUrl as getCachedStreamUrl, prefetchTracks } from "./offlineCache";
import { themes, getThemeById, getSavedThemeId, saveThemeId, type Theme } from "./themes";

type View = "player" | "playlists" | "search" | "lyrics";

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
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);

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
      // If preloaded, swap instantly (gapless)
      if (preloadRef.current && preloadRef.current.src && preloadRef.current.readyState >= 2) {
        const old = audioRef.current;
        audioRef.current = preloadRef.current;
        audioRef.current.play().catch(() => {});
        preloadRef.current = old || new Audio();
        preloadRef.current.preload = "auto";
        preloadRef.current.src = "";
      }
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

    // Load audio with cache
    const loadAudio = async () => {
      if (currentTrackIdRef.current === track.video_id) return;
      currentTrackIdRef.current = track.video_id;
      setBuffering(true);
      
      const apiUrl = getStreamUrl(track.video_id);
      const cachedUrl = await getCachedStreamUrl(track.video_id, apiUrl);
      audio.src = cachedUrl;
      
      if (state.is_playing) {
        audio.play().catch(() => {});
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
    
    loadAudio();
    
    if (!state.is_playing) {
      audio.pause();
    } else if (audio.src && audio.paused) {
      audio.play().catch(() => {});
    }

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
        // Pause playback
        if (audioRef.current) audioRef.current.pause();
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
    if (isWaveLoading) return;
    setIsWaveLoading(true);
    try {
      const recs = await fetchWave(1, 10); // user_id=1 for now
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
  }, [isWaveLoading, state.is_playing]);

  const action = useCallback(
    async (act: string, trackId?: string, seekPos?: number, track?: Track) => {
      try {
        const s = await sendAction(act, trackId, seekPos, track);
        if (act === "seek" && seekPos !== undefined && audioRef.current) {
          audioRef.current.currentTime = seekPos;
        }
        setState(s);
      } catch (e) {
        console.error("Action error:", act, e);
      }
    },
    []
  );

  const showLyrics = (trackId: string) => {
    setLyricsTrackId(trackId);
    setView("lyrics");
  };

  const isTequila = theme.id === "tequila";

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
        {(["player", "playlists", "search"] as View[]).map((v) => (
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
            {v === "player" ? (isTequila ? "♪ Плеер" : "▸ Плеер") : v === "playlists" ? (isTequila ? "♫ Плейлисты" : "▸ Плейлисты") : (isTequila ? "◆ Поиск" : "◈ Поиск")}
          </button>
        ))}
        {/* Theme switcher */}
        <button
          onClick={switchTheme}
          title={theme.id === "tequila" ? "BLACK ROOM" : "𝐓𝐄𝐐𝐔𝐈𝐋𝐀"}
          style={{
            padding: "6px 10px",
            borderRadius: 16,
            border: theme.id === "tequila" ? "1px solid rgba(255,167,38,0.5)" : "1px solid rgba(124,77,255,0.3)",
            background: theme.id === "tequila"
              ? "linear-gradient(135deg, rgba(255,109,0,0.25), rgba(255,213,79,0.15))"
              : "rgba(124,77,255,0.12)",
            color: theme.id === "tequila" ? "#ffd54f" : "#b388ff",
            fontSize: 14,
            cursor: "pointer",
            transition: "all 0.4s ease",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          {theme.id === "tequila" ? "🌙" : "🌅"}
        </button>
      </nav>
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
          <Player state={state} onAction={action} onShowLyrics={showLyrics} accentColor={accentColor} accentColorAlpha={accentColorAlpha} onSleepTimer={handleSleepTimer} sleepTimerRemaining={sleepRemaining} audioDuration={audioDuration} onWave={handleWave} isWaveLoading={isWaveLoading} elapsed={elapsed} buffering={buffering} themeId={theme.id} />
          {state.queue.length > 0 && (
            <TrackList
              tracks={state.queue}
              currentIndex={state.position}
              onPlay={(t) => action("play", t.video_id)}
              onReorder={(newTracks) => {
                reorderQueue(newTracks.map(t => t.video_id)).then(setState).catch(() => {});
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

      {view === "playlists" && <PlaylistView userId={userId} onPlayTrack={(t) => { action("play", t.video_id); setView("player"); }} accentColor={accentColor} themeId={theme.id} />}

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
