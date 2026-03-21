import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import type { JSX } from "preact";
import {
  fetchPlaylists, fetchPlaylistTracks, createPlaylist, deletePlaylist,
  renamePlaylist, removeTrackFromPlaylist, getStreamUrl,
  enableCollab, fetchCollabInfo, disableCollab,
  type Playlist, type Track, type CollabInfo,
} from "../api";
import { IconArrowLeft, IconMusic, IconSpinner, IconClose, IconPlus, IconEdit, IconDownload, IconCheck, IconLink, IconUser, IconFire, IconWave, IconParty, IconMoon, IconBolt, IconHeart, IconStar, IconRocket, IconVinyl, IconCD, IconCase, IconCoverArt } from "./Icons";
import { showToast } from "./Toast";
import { downloadPlaylistOffline, countCachedTracks, isPlaylistDownloading, cancelPlaylistDownload } from "../offlineCache";
import { getThemeById, themeColors } from "../themes";

// ── Preset playlist covers ──
// SVG icon renderers keyed by cover id
const COVER_ICONS: Record<string, (size: number) => JSX.Element> = {
  fire:   (s) => <IconFire size={s} color="#fff" />,
  chill:  (s) => <IconWave size={s} color="#fff" />,
  party:  (s) => <IconParty size={s} color="#fff" />,
  night:  (s) => <IconMoon size={s} color="#fff" />,
  energy: (s) => <IconBolt size={s} color="#fff" />,
  love:   (s) => <IconHeart size={s} color="#fff" filled />,
  gold:   (s) => <IconStar size={s} color="#fff" filled />,
  space:  (s) => <IconRocket size={s} color="#fff" />,
  vinyl:  (s) => <IconVinyl size={s} color="#fff" />,
  cd:     (s) => <IconCD size={s} color="#fff" />,
  case_:  (s) => <IconCase size={s} color="#fff" />,
  cover:  (s) => <IconCoverArt size={s} color="#fff" />,
};

const PLAYLIST_COVERS = [
  { id: "fire",   gradient: "linear-gradient(135deg, #ff4444, #ff8800)" },
  { id: "chill",  gradient: "linear-gradient(135deg, #4488ff, #aa44ff)" },
  { id: "party",  gradient: "linear-gradient(135deg, #ff44aa, #ffcc00)" },
  { id: "night",  gradient: "linear-gradient(135deg, #1a1a5e, #6633aa)" },
  { id: "energy", gradient: "linear-gradient(135deg, #22cc66, #00cccc)" },
  { id: "love",   gradient: "linear-gradient(135deg, #ee2244, #ff66aa)" },
  { id: "gold",   gradient: "linear-gradient(135deg, #ccaa00, #ff8800)" },
  { id: "space",  gradient: "linear-gradient(135deg, #4400aa, #2244cc)" },
  { id: "vinyl",  gradient: "linear-gradient(135deg, #1a1a1a, #444444)" },
  { id: "cd",     gradient: "linear-gradient(135deg, #6688cc, #aaccee)" },
  { id: "case_",  gradient: "linear-gradient(135deg, #334455, #667788)" },
  { id: "cover",  gradient: "linear-gradient(135deg, #cc5588, #8844aa)" },
] as const;

type CoverId = (typeof PLAYLIST_COVERS)[number]["id"];

function getPlaylistCover(playlistId: number): CoverId {
  try {
    const saved = localStorage.getItem(`playlist_cover_${playlistId}`) as CoverId | null;
    if (saved) return saved;
  } catch {}
  // Auto-assign a cover based on playlist id
  return PLAYLIST_COVERS[playlistId % PLAYLIST_COVERS.length].id;
}

function setPlaylistCover(playlistId: number, coverId: CoverId) {
  try {
    localStorage.setItem(`playlist_cover_${playlistId}`, coverId);
  } catch {}
}

function CoverPreview({ coverId, size = 42 }: { coverId: CoverId | null; size?: number }) {
  const cover = coverId ? PLAYLIST_COVERS.find((c) => c.id === coverId) : PLAYLIST_COVERS[0];
  if (!cover) return null;
  const renderIcon = COVER_ICONS[cover.id];
  return (
    <div style={{
      width: size, height: size, borderRadius: size > 40 ? 12 : 10, background: cover.gradient,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {renderIcon ? renderIcon(Math.round(size * 0.48)) : <IconMusic size={Math.round(size * 0.48)} color="#fff" />}
    </div>
  );
}

function CoverPicker({ selected, onSelect, size = 44 }: { selected: CoverId | null; onSelect: (id: CoverId) => void; size?: number }) {
  return (
    <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, WebkitOverflowScrolling: "touch" }}>
      {PLAYLIST_COVERS.map((c) => {
        const renderIcon = COVER_ICONS[c.id];
        return (
          <div
            key={c.id}
            onClick={() => onSelect(c.id)}
            style={{
              width: size, height: size, borderRadius: 12, background: c.gradient, flexShrink: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer",
              outline: selected === c.id ? "2px solid #fff" : "2px solid transparent",
              outlineOffset: 2, transition: "outline 0.15s ease",
            }}
          >
            {renderIcon ? renderIcon(Math.round(size * 0.45)) : <IconMusic size={Math.round(size * 0.45)} color="#fff" />}
          </div>
        );
      })}
    </div>
  );
}

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  onPlayAll?: (tracks: Track[]) => void;
  onPlayPlaylist?: (playlistId: number) => void;
  accentColor?: string;
  themeId?: string;
  currentTrack?: Track | null;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function PlaylistView({ userId, onPlayTrack, onPlayAll, onPlayPlaylist, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom", currentTrack }: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCover, setNewCover] = useState<CoverId | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [swipedTrackId, setSwipedTrackId] = useState<string | null>(null);
  const touchStartX = useRef(0);
  const [dlProgress, setDlProgress] = useState<{ total: number; completed: number; current: string | null } | null>(null);
  const [cachedCount, setCachedCount] = useState(0);
  const [showCoverPicker, setShowCoverPicker] = useState(false);
  const [detailCover, setDetailCover] = useState<CoverId | null>(null);
  const [collabInfo, setCollabInfo] = useState<CollabInfo | null>(null);
  const [collabLoading, setCollabLoading] = useState(false);

  const reload = useCallback(() => {
    setLoading(true);
    fetchPlaylists(userId)
      .then(setPlaylists)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (selectedId !== null) {
      setLoading(true);
      setDetailCover(getPlaylistCover(selectedId));
      setCollabInfo(null);
      fetchPlaylistTracks(selectedId)
        .then(setTracks)
        .catch(() => {})
        .finally(() => setLoading(false));
      // Load collab info (non-blocking)
      fetchCollabInfo(selectedId).then(setCollabInfo).catch(() => {});
    }
  }, [selectedId]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    haptic("medium");
    try {
      const result = await createPlaylist(name);
      if (newCover) {
        setPlaylistCover(result.id, newCover);
      }
      setNewName("");
      setNewCover(null);
      setShowCreate(false);
      showToast("Playlist created", "success", 2000);
      reload();
    } catch {
      showToast("Failed to create playlist", "error");
    }
  };

  const handleRename = async (id: number) => {
    const name = editName.trim();
    if (!name) return;
    haptic("light");
    try {
      await renamePlaylist(id, name);
      setEditingId(null);
      reload();
    } catch {}
  };

  const handleDelete = async (id: number) => {
    haptic("heavy");
    try {
      await deletePlaylist(id);
      setConfirmDeleteId(null);
      if (selectedId === id) { setSelectedId(null); setTracks([]); }
      showToast("Playlist deleted", "success", 2000);
      reload();
    } catch {
      showToast("Failed to delete playlist", "error");
    }
  };

  const handleRemoveTrack = async (videoId: string) => {
    if (selectedId === null) return;
    haptic("medium");
    setTracks((prev) => prev.filter((t) => t.video_id !== videoId));
    try {
      await removeTrackFromPlaylist(selectedId, videoId);
      reload();
    } catch {}
    setSwipedTrackId(null);
  };

  // Count cached tracks when tracks change
  useEffect(() => {
    if (tracks.length > 0) {
      countCachedTracks(tracks.map(t => t.video_id)).then(setCachedCount).catch(() => {});
    } else {
      setCachedCount(0);
    }
  }, [tracks]);

  const handleDownloadOffline = async () => {
    if (isPlaylistDownloading(`pl-${selectedId}`)) {
      cancelPlaylistDownload(`pl-${selectedId}`);
      setDlProgress(null);
      showToast("Скачивание отменено", "info", 2000);
      return;
    }
    haptic("medium");
    const result = await downloadPlaylistOffline(
      tracks.map(t => ({
        video_id: t.video_id,
        title: t.title,
        artist: t.artist,
        duration: t.duration,
        cover_url: t.cover_url,
      })),
      (videoId) => getStreamUrl(videoId),
      (progress) => setDlProgress(progress),
      `pl-${selectedId}`,
    );
    setDlProgress(null);
    setCachedCount(result.success);
    showToast(`Скачано ${result.success} из ${tracks.length} треков`, result.failed > 0 ? "info" : "success", 3000);
  };

  const onTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    setSwipedTrackId(null);
  };

  const onTouchEnd = (e: TouchEvent, videoId: string) => {
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (dx < -60) setSwipedTrackId(videoId);
  };

  const handleDetailCoverSelect = (coverId: CoverId) => {
    if (selectedId === null) return;
    setDetailCover(coverId);
    setPlaylistCover(selectedId, coverId);
    haptic("light");
  };

  const trackRow = (t: Track, idx: number) => {
    const swiped = swipedTrackId === t.video_id;
    return (
      <div key={t.video_id} style={{ position: "relative", overflow: "hidden", borderRadius: 14, marginBottom: 6 }}>
        {swiped && (
          <button
            onClick={() => handleRemoveTrack(t.video_id)}
            style={{
              position: "absolute", right: 0, top: 0, bottom: 0, width: 70,
              background: "linear-gradient(135deg, #e53935, #ff1744)", border: "none",
              color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: "0 14px 14px 0",
            }}
          >Удалить</button>
        )}
        <div
          data-no-synth-tap="true"
          onTouchStart={(e) => onTouchStart(e as unknown as TouchEvent)}
          onTouchEnd={(e) => onTouchEnd(e as unknown as TouchEvent, t.video_id)}
          onClick={() => { if (!swiped) { haptic("light"); onPlayTrack(t); } else setSwipedTrackId(null); }}
          style={{
            display: "flex", alignItems: "center", padding: "10px 12px",
            background: tc.cardBg, border: tc.cardBorder, borderRadius: 14, cursor: "pointer",
            transition: "transform 0.25s ease",
            transform: swiped ? "translateX(-70px)" : "translateX(0)",
            backdropFilter: tc.isTequila ? "blur(12px)" : undefined,
          }}
        >
          <div style={{ width: 14, fontSize: 11, color: tc.hintColor, fontWeight: 600, marginRight: 8, textAlign: "center", flexShrink: 0 }}>{idx + 1}</div>
          <div style={{
            width: 44, height: 44, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12,
            background: tc.coverPlaceholderBg,
            border: `1px solid ${tc.accentBorderAlpha}`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={22} color={tc.hintColor} />}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: tc.textColor }}>{t.title}</div>
            <div style={{ fontSize: 12, color: tc.hintColor }}>{t.artist}</div>
          </div>
          <div style={{ fontSize: 12, color: tc.hintColor, flexShrink: 0 }}>{t.duration_fmt}</div>
        </div>
      </div>
    );
  };

  if (loading && !playlists.length && selectedId === null) {
    return <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={tc.hintColor} /></div>;
  }

  // ── Tracks view ──
  if (selectedId !== null) {
    return (
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <button onClick={() => { setSelectedId(null); setTracks([]); setSwipedTrackId(null); setShowCoverPicker(false); }}
            style={{ background: "none", border: "none", color: tc.highlight, cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontSize: 14 }}>
            <IconArrowLeft size={16} /> Назад
          </button>
          <div style={{ flex: 1, fontSize: 15, fontWeight: 600, color: tc.textColor, textAlign: "center" }}>{selectedName}</div>
          <div style={{ width: 44 }} />
        </div>

        {/* Cover picker in detail view */}
        <div style={{ marginBottom: 12 }}>
          <div
            onClick={() => { setShowCoverPicker(!showCoverPicker); haptic("light"); }}
            style={{
              display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
              borderRadius: 14, background: tc.cardBg, border: tc.cardBorder, cursor: "pointer",
              backdropFilter: tc.isTequila ? "blur(12px)" : undefined,
            }}
          >
            {detailCover ? (
              <CoverPreview coverId={detailCover} size={36} />
            ) : (
              <div style={{
                width: 36, height: 36, borderRadius: 10, background: tc.activeBg,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <IconMusic size={18} color="#fff" />
              </div>
            )}
            <div style={{ flex: 1, fontSize: 12, color: tc.hintColor }}>Обложка плейлиста</div>
            <div style={{ fontSize: 11, color: tc.hintColor }}>{showCoverPicker ? "▲" : "▼"}</div>
          </div>
          {showCoverPicker && (
            <div style={{ marginTop: 8, padding: "8px 4px" }}>
              <CoverPicker selected={detailCover} onSelect={handleDetailCoverSelect} />
            </div>
          )}
        </div>

        {tracks.length > 0 && (
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <button onClick={() => { haptic("medium"); if (onPlayPlaylist && selectedId) onPlayPlaylist(selectedId); else if (onPlayAll) onPlayAll(tracks); else if (tracks[0]) onPlayTrack(tracks[0]); }}
              style={{ flex: 1, padding: "10px 0", borderRadius: 14, border: "none", background: tc.activeBg, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              ▶ Воспроизвести всё
            </button>
            <button onClick={handleDownloadOffline}
              style={{
                padding: "10px 14px", borderRadius: 14, border: tc.cardBorder,
                background: dlProgress ? "rgba(255,152,0,0.2)" : (cachedCount >= tracks.length && tracks.length > 0 ? "rgba(76,175,80,0.2)" : tc.cardBg),
                color: cachedCount >= tracks.length && tracks.length > 0 ? "#81c784" : tc.textColor,
                fontSize: 12, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 6,
              }}>
              {dlProgress ? (
                <><IconSpinner size={14} color={tc.highlight} /> {dlProgress.completed}/{dlProgress.total}</>
              ) : cachedCount >= tracks.length && tracks.length > 0 ? (
                <><IconCheck size={14} color="#81c784" /> Офлайн</>
              ) : (
                <><IconDownload size={14} color={tc.highlight} /> Скачать</>
              )}
            </button>
          </div>
        )}
        {dlProgress?.current && (
          <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            Скачивание: {dlProgress.current}...
          </div>
        )}

        {/* Collab section */}
        {selectedId && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
            padding: "10px 12px", borderRadius: 14,
            background: tc.cardBg, border: tc.cardBorder,
          }}>
            <IconUser size={16} color={collabInfo?.enabled ? tc.highlight : tc.hintColor} />
            {collabInfo?.enabled ? (
              <>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: tc.highlight }}>
                    Совместный · {collabInfo.member_count} чел.
                  </div>
                  {collabInfo.invite_code && (
                    <div style={{ fontSize: 10, color: tc.hintColor, marginTop: 2 }}>
                      Код: {collabInfo.invite_code}
                    </div>
                  )}
                </div>
                {collabInfo.invite_code && (
                  <button
                    onClick={() => {
                      haptic("light");
                      const code = collabInfo?.invite_code;
                      if (!code) return;
                      const url = `https://t.me/TSmymusicbot_bot/app?startapp=collab_${code}`;
                      try {
                        window.Telegram?.WebApp?.openTelegramLink?.(
                          `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(`Присоединяйся к плейлисту "${selectedName}"! 🎵`)}`
                        );
                      } catch {
                        navigator.clipboard?.writeText(code);
                        showToast("Код скопирован!");
                      }
                    }}
                    style={{
                      padding: "6px 12px", borderRadius: 10, border: "none",
                      background: tc.activeBg, color: tc.highlight,
                      fontSize: 11, fontWeight: 600, cursor: "pointer",
                      display: "flex", alignItems: "center", gap: 4,
                    }}
                  >
                    <IconLink size={12} color={tc.highlight} /> Пригласить
                  </button>
                )}
                {collabInfo.is_owner && (
                  <button
                    onClick={async () => {
                      haptic("medium");
                      setCollabLoading(true);
                      try {
                        await disableCollab(selectedId);
                        setCollabInfo({ ...collabInfo, enabled: false });
                        showToast("Совместный доступ отключён");
                      } catch {}
                      setCollabLoading(false);
                    }}
                    disabled={collabLoading}
                    style={{
                      padding: "6px 10px", borderRadius: 10, border: "none",
                      background: "rgba(239,83,80,0.15)", color: "#ef5350",
                      fontSize: 11, cursor: "pointer",
                    }}
                  >
                    <IconClose size={12} />
                  </button>
                )}
              </>
            ) : (
              <>
                <div style={{ flex: 1, fontSize: 12, color: tc.hintColor }}>
                  Совместный доступ
                </div>
                <button
                  onClick={async () => {
                    haptic("medium");
                    setCollabLoading(true);
                    try {
                      const res = await enableCollab(selectedId);
                      setCollabInfo({
                        enabled: true,
                        invite_code: res.invite_code,
                        member_count: 1,
                        is_member: true,
                        is_owner: true,
                      });
                      showToast("Совместный доступ включён!");
                    } catch {}
                    setCollabLoading(false);
                  }}
                  disabled={collabLoading}
                  style={{
                    padding: "6px 14px", borderRadius: 10, border: "none",
                    background: tc.activeBg, color: tc.highlight,
                    fontSize: 11, fontWeight: 600, cursor: "pointer",
                    opacity: collabLoading ? 0.5 : 1,
                  }}
                >
                  {collabLoading ? <IconSpinner size={12} color={tc.highlight} /> : "Включить"}
                </button>
              </>
            )}
          </div>
        )}

        <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
          {tracks.length} треков · свайп влево — удалить
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={tc.hintColor} /></div>
        ) : tracks.length === 0 ? (
          <div style={{ textAlign: "center", color: tc.hintColor, padding: 32 }}>Плейлист пуст</div>
        ) : tracks.map((t, idx) => trackRow(t, idx))}
      </div>
    );
  }

  // ── Playlists list ──
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: tc.textColor, letterSpacing: 0.4 }}>Мои плейлисты</div>
        <button onClick={() => { haptic("light"); setShowCreate(true); }}
          style={{ padding: "6px 14px", borderRadius: 14, border: "none", background: tc.activeBg, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
          + Создать
        </button>
      </div>

      {showCreate && (
        <div style={{ marginBottom: 12, padding: 12, borderRadius: 16, background: tc.cardBg, border: tc.cardBorder }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <input type="text" placeholder="Название плейлиста" maxLength={100} value={newName}
              onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
              style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: `1px solid ${tc.accentBorderAlpha}`, background: "transparent", color: tc.textColor, fontSize: 14, outline: "none" }} />
            <button onClick={handleCreate} style={{ padding: "8px 16px", borderRadius: 10, border: "none", background: accentColor, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>OK</button>
            <button onClick={() => { setShowCreate(false); setNewName(""); setNewCover(null); }} style={{ padding: "8px 12px", borderRadius: 10, border: tc.cardBorder, background: "transparent", color: tc.hintColor, fontSize: 13, cursor: "pointer" }}><IconClose size={14} /></button>
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 6 }}>Обложка:</div>
          <CoverPicker selected={newCover} onSelect={(id) => { setNewCover(id); haptic("light"); }} size={40} />
        </div>
      )}

      {playlists.length === 0 && !showCreate ? (
        <div style={{ textAlign: "center", color: tc.hintColor, padding: 32 }}>Нет плейлистов — нажмите «+ Создать»</div>
      ) : (
        playlists.map((p) => {
          const coverId = getPlaylistCover(p.id);
          return (
            <div key={p.id} style={{ marginBottom: 6 }}>
              {confirmDeleteId === p.id ? (
                <div style={{ display: "flex", gap: 8, padding: 12, borderRadius: 14, background: "rgba(229, 57, 53, 0.15)", border: "1px solid rgba(229, 57, 53, 0.3)", alignItems: "center" }}>
                  <span style={{ flex: 1, fontSize: 13, color: "#ef5350" }}>Удалить «{p.name}»?</span>
                  <button onClick={() => handleDelete(p.id)} style={{ padding: "6px 14px", borderRadius: 10, border: "none", background: "#e53935", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Да</button>
                  <button onClick={() => setConfirmDeleteId(null)} style={{ padding: "6px 14px", borderRadius: 10, border: tc.cardBorder, background: "transparent", color: tc.hintColor, fontSize: 12, cursor: "pointer" }}>Нет</button>
                </div>
              ) : editingId === p.id ? (
                <div style={{ display: "flex", gap: 8, padding: 12, borderRadius: 14, background: tc.cardBg, border: tc.cardBorder }}>
                  <input type="text" maxLength={100} value={editName}
                    onInput={(e) => setEditName((e.target as HTMLInputElement).value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleRename(p.id); }}
                    style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: `1px solid ${tc.accentBorderAlpha}`, background: "transparent", color: tc.textColor, fontSize: 14, outline: "none" }} />
                  <button onClick={() => handleRename(p.id)} style={{ padding: "8px 14px", borderRadius: 10, border: "none", background: accentColor, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>{"✓"}</button>
                  <button onClick={() => setEditingId(null)} style={{ padding: "8px 10px", borderRadius: 10, border: tc.cardBorder, background: "transparent", color: tc.hintColor, fontSize: 12, cursor: "pointer" }}><IconClose size={14} /></button>
                </div>
              ) : (
                <div onClick={() => { haptic("light"); setSelectedId(p.id); setSelectedName(p.name); }}
                  style={{ display: "flex", alignItems: "center", padding: "12px 14px", borderRadius: 14, cursor: "pointer", background: tc.cardBg, border: tc.cardBorder, backdropFilter: tc.isTequila ? "blur(12px)" : undefined }}>
                  {coverId ? (
                    <div style={{ marginRight: 12, flexShrink: 0 }}>
                      <CoverPreview coverId={coverId} size={42} />
                    </div>
                  ) : (
                    <div style={{ width: 42, height: 42, borderRadius: 12, marginRight: 12, flexShrink: 0, background: tc.activeBg, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <IconMusic size={20} color="#fff" />
                    </div>
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 500, color: tc.textColor }}>{p.name}</div>
                    <div style={{ fontSize: 12, color: tc.hintColor }}>{p.track_count} треков</div>
                  </div>
                  <div style={{ display: "flex", gap: 4 }}>
                    <button onClick={(e) => { e.stopPropagation(); haptic("light"); setEditingId(p.id); setEditName(p.name); }}
                      style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: tc.hintColor, fontSize: 14, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><IconEdit size={14} /></button>
                    <button onClick={(e) => { e.stopPropagation(); haptic("light"); setConfirmDeleteId(p.id); }}
                      style={{ width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: "#ef5350", fontSize: 14, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><IconClose size={14} /></button>
                  </div>
                </div>
              )}
            </div>
          );
        })
      )}

      {currentTrack && playlists.length > 0 && (
        <div style={{ marginTop: 16, padding: 12, borderRadius: 14, background: tc.coverPlaceholderBg, border: `1px solid ${tc.accentBorderAlpha}`, fontSize: 12, color: tc.hintColor, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
          Чтобы добавить трек в плейлист — нажми <IconPlus size={12} /> в плеере
        </div>
      )}
    </div>
  );
}
