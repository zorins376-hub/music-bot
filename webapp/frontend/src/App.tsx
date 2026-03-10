import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { PlaylistView } from "./components/PlaylistView";
import { SearchBar } from "./components/SearchBar";
import { LyricsView } from "./components/LyricsView";
import { MiniPlayer } from "./components/MiniPlayer";
import { fetchPlayerState, sendAction, getStreamUrl, reorderQueue, type PlayerState, type Track } from "./api";
import { extractDominantColor, rgbToCSS, rgbaToCSS } from "./colorExtractor";

type View = "player" | "playlists" | "search" | "lyrics";

export function App() {
  const user = window.Telegram.WebApp.initDataUnsafe.user;
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
  const [accentColor, setAccentColor] = useState("rgb(124, 77, 255)");
  const [accentColorAlpha, setAccentColorAlpha] = useState("rgba(124, 77, 255, 0.4)");

  // Create persistent audio element
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    // Preload element for gapless playback
    const preload = new Audio();
    preload.preload = "auto";
    preloadRef.current = preload;

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

      // Gapless: preload next track 15 seconds before end
      if (audio.duration && audio.duration - audio.currentTime < 15 && audio.duration > 20) {
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

    return () => { audio.pause(); audio.src = ""; preload.src = ""; };
  }, []);

  // Sync audio with current track
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const track = state.current_track;
    if (!track) {
      audio.pause(); audio.src = "";
      if ("mediaSession" in navigator) navigator.mediaSession.metadata = null;
      return;
    }

    const newSrc = getStreamUrl(track.video_id);
    if (audio.src !== newSrc) {
      audio.src = newSrc;
    }
    if (state.is_playing) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }

    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: track.title,
        artist: track.artist || "Black Room Radio",
        artwork: track.cover_url ? [
          { src: track.cover_url, sizes: "480x360", type: "image/jpeg" }
        ] : []
      });

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
    }
  }, [state.current_track?.video_id, state.is_playing]);

  // Dynamic Color Extraction from cover
  useEffect(() => {
    const coverUrl = state.current_track?.cover_url;
    if (coverUrl) {
      extractDominantColor(coverUrl).then((color) => {
        setAccentColor(rgbToCSS(color));
        setAccentColorAlpha(rgbaToCSS(color, 0.4));
      });
    } else {
      setAccentColor("rgb(124, 77, 255)");
      setAccentColorAlpha("rgba(124, 77, 255, 0.4)");
    }
  }, [state.current_track?.cover_url]);

  useEffect(() => {
    if (userId) fetchPlayerState(userId).then(setState).catch(() => {});
  }, [userId]);
  useEffect(() => {
    elapsedRef.current = 0;
    setElapsed(0);
  }, [state.current_track?.video_id]);

  const action = useCallback(
    async (act: string, trackId?: string, seekPos?: number) => {
      try {
        const s = await sendAction(act, trackId, seekPos);
        if (act === "seek" && seekPos !== undefined && audioRef.current) {
          audioRef.current.currentTime = seekPos;
        }
        setState(s);
      } catch {}
    },
    []
  );

  const showLyrics = (trackId: string) => {
    setLyricsTrackId(trackId);
    setView("lyrics");
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      {/* Glassmorphism Background */}
      {state.current_track?.cover_url && (
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
      <nav style={{ display: "flex", gap: 8, marginBottom: 12, justifyContent: "center" }}>
        {(["player", "playlists", "search"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            style={{
              padding: "6px 14px",
              borderRadius: 16,
              border: "none",
              background: view === v ? accentColor : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
              color: view === v ? "#fff" : "var(--tg-theme-hint-color, #aaa)",
              fontSize: 13,
              cursor: "pointer",
              transition: "background 0.5s ease",
            }}
          >
            {v === "player" ? "▸ Плеер" : v === "playlists" ? "▸ Плейлисты" : "◈ Поиск"}
          </button>
        ))}
      </nav>

      {/* Views */}
      {view === "player" && (
        <>
          <Player state={state} onAction={action} onShowLyrics={showLyrics} accentColor={accentColor} accentColorAlpha={accentColorAlpha} />
          {state.queue.length > 0 && (
            <TrackList
              tracks={state.queue}
              currentIndex={state.position}
              onPlay={(t) => action("play", t.video_id)}
              onReorder={(newTracks) => {
                reorderQueue(newTracks.map(t => t.video_id)).then(setState).catch(() => {});
              }}
              accentColor={accentColor}
            />
          )}
        </>
      )}

      {view === "playlists" && <PlaylistView userId={userId} onPlayTrack={(t) => { action("play", t.video_id); setView("player"); }} />}

      {view === "search" && <SearchBar onSelect={(t) => { action("play", t.video_id); setView("player"); }} />}

      {view === "lyrics" && lyricsTrackId && (
        <LyricsView trackId={lyricsTrackId} elapsed={elapsed} onBack={() => setView("player")} accentColor={accentColor} />
      )}
      </div>

      {/* Floating Mini-Player (visible when NOT on Player view) */}
      {view !== "player" && state.current_track && (
        <MiniPlayer
          state={state}
          accentColor={accentColor}
          onAction={(act) => action(act)}
          onExpand={() => setView("player")}
        />
      )}
    </div>
  );
}
