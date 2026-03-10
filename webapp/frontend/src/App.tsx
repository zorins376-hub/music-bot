import { useState, useEffect, useCallback } from "preact/hooks";
import { Player } from "./components/Player";
import { TrackList } from "./components/TrackList";
import { PlaylistView } from "./components/PlaylistView";
import { SearchBar } from "./components/SearchBar";
import { LyricsView } from "./components/LyricsView";
import { fetchPlayerState, sendAction, type PlayerState, type Track } from "./api";

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

  useEffect(() => {
    if (userId) fetchPlayerState(userId).then(setState).catch(() => {});
  }, [userId]);

  const action = useCallback(
    async (act: string, trackId?: string) => {
      try {
        const s = await sendAction(act, trackId);
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
        <LyricsView trackId={lyricsTrackId} onBack={() => setView("player")} />
      )}
    </div>
  );
}
