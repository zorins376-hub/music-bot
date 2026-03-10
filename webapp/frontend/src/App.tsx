import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { PlaylistView } from "./components/PlaylistView";
import { SearchBar } from "./components/SearchBar";
import { LyricsView } from "./components/LyricsView";
import { fetchPlayerState, sendAction, getStreamUrl, type PlayerState, type Track } from "./api";

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

  // Create persistent audio element
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    audio.addEventListener("ended", () => {
      // Auto-next on track end
      sendAction("next").then(setState).catch(() => {});
    });
    audio.addEventListener("timeupdate", () => {
      const t = Math.floor(audio.currentTime);
      elapsedRef.current = t;
      setElapsed(t);
    });

    return () => { audio.pause(); audio.src = ""; };
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
    <div style={{ padding: "8px 12px", maxWidth: 480, margin: "0 auto" }}>
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
              background: view === v ? "var(--tg-theme-button-color, #7c4dff)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
              color: view === v ? "#fff" : "var(--tg-theme-hint-color, #aaa)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {v === "player" ? "▸ Плеер" : v === "playlists" ? "▸ Плейлисты" : "◈ Поиск"}
          </button>
        ))}
      </nav>

      {/* Views */}
      {view === "player" && (
        <>
          <Player state={state} onAction={action} onShowLyrics={showLyrics} />
          {state.queue.length > 0 && (
            <TrackList
              tracks={state.queue}
              currentIndex={state.position}
              onPlay={(t) => action("play", t.video_id)}
            />
          )}
        </>
      )}

      {view === "playlists" && <PlaylistView userId={userId} onPlayTrack={(t) => { action("play", t.video_id); setView("player"); }} />}

      {view === "search" && <SearchBar onSelect={(t) => { action("play", t.video_id); setView("player"); }} />}

      {view === "lyrics" && lyricsTrackId && (
        <LyricsView trackId={lyricsTrackId} elapsed={elapsed} onBack={() => setView("player")} />
      )}
    </div>
  );
}
