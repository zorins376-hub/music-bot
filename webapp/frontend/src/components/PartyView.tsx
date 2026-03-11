import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchParty, addPartyTrack, removePartyTrack, skipPartyTrack, closeParty,
  createParty, fetchMyParties, searchTracks,
  type Party, type Track,
} from "../api";
import { IconMusic, IconSpinner, IconSearch, IconPlus } from "./Icons";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
  initialCode?: string | null;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function PartyView({ userId, onPlayTrack, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom", initialCode }: Props) {
  const warm = themeId === "tequila";
  const [party, setParty] = useState<Party | null>(null);
  const [myParties, setMyParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Track[]>([]);
  const [searching, setSearching] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hintColor = warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)";
  const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
  const cardBorder = warm ? "1px solid rgba(255, 213, 79, 0.12)" : "1px solid rgba(255,255,255,0.07)";
  const activeBg = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.42), rgba(255,193,7,0.24))"
    : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.34))`;
  const partyGradient = "linear-gradient(135deg, #ff6d00, #ff9100, #ffd600)";
  const shellBg = warm
    ? "linear-gradient(180deg, rgba(255,193,7,0.06), rgba(255,109,0,0.02) 26%, transparent 55%)"
    : `linear-gradient(180deg, ${accentColor}18, rgba(255,255,255,0.01) 26%, transparent 55%)`;
  const glassBg = warm
    ? "linear-gradient(135deg, rgba(56, 34, 18, 0.84), rgba(26, 16, 10, 0.70))"
    : "linear-gradient(135deg, rgba(36, 28, 58, 0.74), rgba(15, 18, 35, 0.72))";
  const softBg = warm
    ? "linear-gradient(135deg, rgba(70, 40, 22, 0.54), rgba(27, 18, 11, 0.44))"
    : "linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.025))";
  const panelShadow = warm
    ? "0 16px 40px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,224,178,0.06)"
    : "0 16px 40px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.08)";
  const glassCard = {
    background: glassBg,
    border: cardBorder,
    boxShadow: panelShadow,
    backdropFilter: "blur(16px) saturate(135%)",
    WebkitBackdropFilter: "blur(16px) saturate(135%)",
  } as const;
  const softCard = {
    background: softBg,
    border: cardBorder,
    backdropFilter: "blur(14px) saturate(130%)",
    WebkitBackdropFilter: "blur(14px) saturate(130%)",
  } as const;
  const sectionLabel = {
    fontSize: 11,
    fontWeight: 800,
    textTransform: "uppercase" as const,
    letterSpacing: 1.6,
    color: hintColor,
    marginBottom: 8,
  };

  const isDJ = party ? party.creator_id === userId : false;

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  const connectSSE = useCallback((code: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const initData = encodeURIComponent(window.Telegram?.WebApp?.initData || "");
    const es = new EventSource(`/api/party/${encodeURIComponent(code)}/events?token=${initData}`);
    eventSourceRef.current = es;

    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.event === "track_added") {
          showToast(`🎵 ${msg.data.added_by_name} добавил: ${msg.data.title}`);
          fetchParty(code).then(setParty).catch(() => {});
        } else if (msg.event === "track_removed" || msg.event === "next") {
          fetchParty(code).then(setParty).catch(() => {});
        } else if (msg.event === "member_joined" || msg.event === "member_left") {
          setParty(prev => prev ? { ...prev, member_count: msg.data.member_count ?? prev.member_count } : prev);
          if (msg.event === "member_joined" && msg.data.name) {
            showToast(`👋 ${msg.data.name} присоединился`);
          }
        } else if (msg.event === "closed") {
          showToast("🏁 Пати завершена!");
          setParty(null);
        }
      } catch {}
    };
  }, []);

  useEffect(() => {
    if (initialCode) {
      setLoading(true);
      fetchParty(initialCode)
        .then((p) => {
          setParty(p);
          connectSSE(initialCode);
        })
        .catch(() => showToast("❌ Пати не найдена"))
        .finally(() => setLoading(false));
    } else {
      setLoading(true);
      fetchMyParties()
        .then(setMyParties)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
    return () => {
      eventSourceRef.current?.close();
    };
  }, [initialCode, connectSSE]);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchTracks(searchQuery, 8);
        setSearchResults(results);
      } catch {}
      setSearching(false);
    }, 400);
  }, [searchQuery]);

  const handleCreate = async () => {
    const name = newName.trim() || "Party 🎉";
    haptic("medium");
    try {
      const p = await createParty(name);
      setParty(p);
      connectSSE(p.invite_code);
      setShowCreate(false);
      setNewName("");
    } catch {
      showToast("❌ Не удалось создать пати");
    }
  };

  const handleJoinParty = async (code: string) => {
    haptic("light");
    setLoading(true);
    try {
      const p = await fetchParty(code);
      setParty(p);
      connectSSE(code);
    } catch {
      showToast("❌ Пати не найдена");
    }
    setLoading(false);
  };

  const handleAddTrack = async (track: Track) => {
    if (!party) return;
    haptic("medium");
    try {
      const updated = await addPartyTrack(party.invite_code, track);
      setParty(updated);
      setShowSearch(false);
      setSearchQuery("");
      setSearchResults([]);
    } catch {
      showToast("❌ Ошибка при добавлении");
    }
  };

  const handleRemoveTrack = async (videoId: string) => {
    if (!party) return;
    haptic("heavy");
    try {
      await removePartyTrack(party.invite_code, videoId);
      setParty(prev => prev ? { ...prev, tracks: prev.tracks.filter(t => t.video_id !== videoId) } : prev);
    } catch {}
  };

  const handleSkip = async () => {
    if (!party) return;
    haptic("medium");
    try {
      const updated = await skipPartyTrack(party.invite_code);
      setParty(updated);
    } catch {
      showToast("❌ Ошибка");
    }
  };

  const handleClose = async () => {
    if (!party) return;
    haptic("heavy");
    try {
      await closeParty(party.invite_code);
      setParty(null);
      eventSourceRef.current?.close();
    } catch {
      showToast("❌ Только DJ может закрыть пати");
    }
  };

  const handleShare = () => {
    if (!party) return;
    haptic("light");
    const botUsername = window.Telegram?.WebApp?.initDataUnsafe?.user?.username || "musicbot";
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(`https://t.me/${botUsername}?startapp=party_${party.invite_code}`)}&text=${encodeURIComponent(`🎉 Заходи на пати «${party.name}»! Добавляй свои треки 🎶`)}`;
    window.open(shareUrl, "_blank");
  };

  const Toast = toast ? (
    <div style={{
      position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
      padding: "10px 20px", borderRadius: 14, fontSize: 13, fontWeight: 700,
      background: warm ? "rgba(40, 25, 15, 0.92)" : "rgba(0,0,0,0.88)",
      color: "#fff", zIndex: 99999, backdropFilter: "blur(12px)",
      border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(255,255,255,0.1)",
      boxShadow: "0 12px 28px rgba(0,0,0,0.24)",
    }}>
      {toast}
    </div>
  ) : null;

  if (loading && !party && !myParties.length) {
    return <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={hintColor} /></div>;
  }

  if (party) {
    const currentTrack = party.tracks.find(t => t.position === party.current_position);
    const upNext = party.tracks.filter(t => t.position > party.current_position).sort((a, b) => a.position - b.position);
    const played = party.tracks.filter(t => t.position < party.current_position).sort((a, b) => a.position - b.position);

    return (
      <div style={{ background: shellBg, borderRadius: 26, padding: 2 }}>
        {Toast}

        <div style={{
          padding: "18px 16px 16px", borderRadius: 22, marginBottom: 12,
          background: partyGradient, position: "relative", overflow: "hidden",
          boxShadow: "0 18px 40px rgba(255,145,0,0.22)",
        }}>
          <div style={{ position: "absolute", width: 120, height: 120, borderRadius: "50%", right: -28, top: -24, background: "rgba(255,255,255,0.18)", filter: "blur(10px)" }} />
          <div style={{ position: "absolute", width: 96, height: 96, borderRadius: "50%", left: -20, bottom: -34, background: "rgba(255,255,255,0.12)", filter: "blur(8px)" }} />
          <div style={{ position: "relative", zIndex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 999, marginBottom: 8, background: "rgba(0,0,0,0.16)", color: "rgba(255,255,255,0.92)", fontSize: 10, fontWeight: 800, letterSpacing: 1.1, textTransform: "uppercase" }}>Luxury Party</div>
                <div style={{ fontSize: 21, fontWeight: 800, color: "#180d00", lineHeight: 1.1 }}>{party.name}</div>
              </div>
              <div style={{
                padding: "6px 11px", borderRadius: 12, fontSize: 11, fontWeight: 800,
                background: "rgba(0,0,0,0.22)", color: "#fff", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.14)",
              }}>
                👥 {party.member_count} online
              </div>
            </div>
            <div style={{ fontSize: 12, color: "rgba(24,13,0,0.7)", marginTop: 6, lineHeight: 1.45 }}>
              {isDJ ? "🎧 Ты DJ — управляй очередью" : "Добавляй треки в общую очередь"}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.16)", color: "#fff", fontSize: 11, fontWeight: 700 }}>#{party.invite_code}</div>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.12)", color: "rgba(255,255,255,0.92)", fontSize: 11, fontWeight: 700 }}>🎶 {party.tracks.length} треков</div>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.12)", color: "rgba(255,255,255,0.92)", fontSize: 11, fontWeight: 700 }}>{isDJ ? "👑 DJ mode" : "✨ listener"}</div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button onClick={handleShare} style={{
                flex: 1, padding: "10px 0", borderRadius: 14, border: "1px solid rgba(255,255,255,0.14)",
                background: "rgba(0,0,0,0.22)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                boxShadow: "inset 0 1px 0 rgba(255,255,255,0.12)",
              }}>📤 Поделиться</button>
              {isDJ && (
                <button onClick={handleClose} style={{
                  padding: "10px 14px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.14)",
                  background: "rgba(229,57,53,0.82)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                }}>🏁 Закрыть</button>
              )}
            </div>
          </div>
        </div>

        {currentTrack && (
          <div style={{
            padding: "14px 14px", borderRadius: 18, marginBottom: 12,
            background: warm ? "rgba(255, 109, 0, 0.15)" : "rgba(124, 77, 255, 0.12)",
            border: warm ? "1px solid rgba(255,109,0,0.25)" : "1px solid rgba(124,77,255,0.2)",
            boxShadow: warm ? "0 14px 34px rgba(255,109,0,0.12)" : "0 14px 34px rgba(124,77,255,0.12)",
            backdropFilter: "blur(16px) saturate(135%)",
            WebkitBackdropFilter: "blur(16px) saturate(135%)",
          }}>
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <span>▶ Сейчас играет</span>
              <span style={{ color: warm ? "#ffd54f" : accentColor, fontSize: 10 }}>{isDJ ? "DJ control" : "Live sync"}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 62, height: 62, borderRadius: 16, overflow: "hidden", flexShrink: 0,
                background: warm ? "rgba(255,213,79,0.08)" : "rgba(124,77,255,0.08)",
                boxShadow: "0 10px 20px rgba(0,0,0,0.18)",
              }}>
                {currentTrack.cover_url ? <img src={currentTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusic size={24} color={hintColor} /></div>}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{currentTrack.title}</div>
                <div style={{ fontSize: 12, color: hintColor, marginTop: 2 }}>{currentTrack.artist} · {currentTrack.added_by_name || "?"}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 7, flexWrap: "wrap" }}>
                  <span style={{ padding: "4px 8px", borderRadius: 999, background: "rgba(255,255,255,0.06)", color: hintColor, fontSize: 10, fontWeight: 700 }}>{currentTrack.duration_fmt}</span>
                  <span style={{ padding: "4px 8px", borderRadius: 999, background: "rgba(255,255,255,0.06)", color: hintColor, fontSize: 10, fontWeight: 700 }}>{currentTrack.source || "music"}</span>
                </div>
              </div>
              <button onClick={() => { haptic("light"); onPlayTrack(currentTrack); }} style={{
                padding: "10px 14px", borderRadius: 14, border: "none",
                background: activeBg, color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                boxShadow: warm ? "0 10px 24px rgba(255,109,0,0.2)" : `0 10px 24px ${accentColor}33`,
              }}>▶</button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={handleSkip} style={{
                flex: 1, padding: "9px 0", borderRadius: 12, border: cardBorder,
                background: "rgba(255,255,255,0.03)", color: hintColor, fontSize: 12, cursor: "pointer", fontWeight: 700,
              }}>
                {isDJ ? "⏭ Пропустить" : `⏭ Vote Skip (${currentTrack.skip_votes}/3)`}
              </button>
            </div>
          </div>
        )}

        <button onClick={() => { haptic("light"); setShowSearch(true); }} style={{
          width: "100%", padding: "14px 0", borderRadius: 16, border: cardBorder,
          background: softBg, color: textColor, fontSize: 14, fontWeight: 700,
          cursor: "pointer", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
          backdropFilter: "blur(14px) saturate(130%)",
          WebkitBackdropFilter: "blur(14px) saturate(130%)",
          boxShadow: panelShadow,
        }}>
          <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} /> Добавить трек
        </button>

        {showSearch && (
          <div style={{ padding: 12, borderRadius: 16, marginBottom: 10, ...glassCard }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <input
                type="text" placeholder="Поиск треков..." value={searchQuery}
                onInput={(e: any) => setSearchQuery(e.target.value)}
                autoFocus
                style={{
                  flex: 1, padding: "10px 12px", borderRadius: 12,
                  border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)",
                  background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 14, outline: "none",
                }}
              />
              <button onClick={() => { setShowSearch(false); setSearchQuery(""); setSearchResults([]); }} style={{
                padding: "8px 12px", borderRadius: 10, border: cardBorder,
                background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer",
              }}>✕</button>
            </div>
            {searching && <div style={{ textAlign: "center", padding: 12 }}><IconSpinner size={18} color={hintColor} /></div>}
            {!searching && !searchResults.length && searchQuery.trim() && (
              <div style={{ textAlign: "center", padding: "14px 8px", color: hintColor, fontSize: 12 }}><IconSearch size={16} color={hintColor} /> <div style={{ marginTop: 6 }}>Ничего не найдено</div></div>
            )}
            {searchResults.map((t) => (
              <div key={t.video_id} onClick={() => handleAddTrack(t)} style={{
                display: "flex", alignItems: "center", padding: "10px 10px", borderRadius: 14, cursor: "pointer",
                marginBottom: 6, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={18} color={hintColor} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 600 }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: hintColor }}>{t.artist}</div>
                </div>
                <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} />
              </div>
            ))}
          </div>
        )}

        {upNext.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={sectionLabel}>Далее · {upNext.length} треков</div>
            {upNext.map((t, idx) => (
              <div key={t.video_id} style={{
                display: "flex", alignItems: "center", padding: "12px 12px", borderRadius: 16,
                ...softCard, marginBottom: 6, cursor: "pointer", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05)",
              }} onClick={() => { haptic("light"); onPlayTrack(t); }}>
                <div style={{ width: 28, flexShrink: 0, marginRight: 8, color: hintColor, fontSize: 11, fontWeight: 800, textAlign: "center" }}>{String(idx + 1).padStart(2, "0")}</div>
                <div style={{ width: 40, height: 40, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={18} color={hintColor} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 600 }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: hintColor }}>{t.artist} · {t.added_by_name || "?"}</div>
                </div>
                <div style={{ fontSize: 11, color: hintColor, flexShrink: 0, padding: "4px 8px", borderRadius: 999, background: "rgba(255,255,255,0.05)" }}>{t.duration_fmt}</div>
                {isDJ && (
                  <button onClick={(e: any) => { e.stopPropagation(); handleRemoveTrack(t.video_id); }} style={{
                    marginLeft: 8, width: 28, height: 28, borderRadius: 8, border: "none",
                    background: "transparent", color: "#ef5350", fontSize: 14, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>✕</button>
                )}
              </div>
            ))}
          </div>
        )}

        {played.length > 0 && (
          <div style={{ opacity: 0.58 }}>
            <div style={sectionLabel}>Уже играло · {played.length}</div>
            {played.map((t) => (
              <div key={t.video_id} style={{
                display: "flex", alignItems: "center", padding: "8px 10px", borderRadius: 12,
                marginBottom: 4, background: "rgba(255,255,255,0.02)",
              }}>
                <div style={{ width: 34, height: 34, borderRadius: 8, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.04)" : "rgba(124,77,255,0.04)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={16} color={hintColor} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: hintColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: hintColor }}>{t.artist}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {party.tracks.length === 0 && (
          <div style={{ ...glassCard, textAlign: "center", color: hintColor, padding: 32, fontSize: 14, borderRadius: 18 }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>🎵</div>
            <div style={{ color: textColor, fontWeight: 700, marginBottom: 4 }}>Очередь пока пустая</div>
            Очередь пуста — добавь первый трек!
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ background: shellBg, borderRadius: 26, padding: 2 }}>
      {Toast}

      <div style={{
        ...glassCard,
        borderRadius: 22,
        padding: "18px 16px",
        marginBottom: 12,
        position: "relative",
        overflow: "hidden",
      }}>
        <div style={{ position: "absolute", width: 120, height: 120, borderRadius: "50%", right: -34, top: -40, background: warm ? "rgba(255,193,7,0.08)" : `${accentColor}22`, filter: "blur(10px)" }} />
        <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, color: hintColor, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 8 }}>Party playlists</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: textColor, lineHeight: 1.1, marginBottom: 6 }}>Слушайте вместе. Выглядит дорого.</div>
            <div style={{ fontSize: 13, color: hintColor, lineHeight: 1.45, maxWidth: 260 }}>Общая очередь, live-sync, приглашения друзьям и контроль DJ в одном люксовом экране.</div>
          </div>
          <button onClick={() => { haptic("light"); setShowCreate(true); }} style={{
            padding: "9px 14px", borderRadius: 14, border: "none",
            background: partyGradient, color: "#000", fontSize: 12, fontWeight: 800, cursor: "pointer",
            boxShadow: "0 12px 24px rgba(255,145,0,0.18)", flexShrink: 0,
          }}>+ Создать</button>
        </div>
      </div>

      {showCreate && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12, padding: 12, borderRadius: 18, ...glassCard }}>
          <input type="text" placeholder="Название пати" maxLength={100} value={newName}
            onInput={(e: any) => setNewName(e.target.value)}
            onKeyDown={(e: any) => { if (e.key === "Enter") handleCreate(); }}
            style={{ flex: 1, padding: "10px 12px", borderRadius: 12, border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)", background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 14, outline: "none" }} />
          <button onClick={handleCreate} style={{ padding: "10px 16px", borderRadius: 12, border: "none", background: partyGradient, color: "#000", fontSize: 13, fontWeight: 800, cursor: "pointer" }}>🎉 Go</button>
          <button onClick={() => { setShowCreate(false); setNewName(""); }} style={{ padding: "10px 12px", borderRadius: 12, border: cardBorder, background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer" }}>✕</button>
        </div>
      )}

      {myParties.length === 0 && !showCreate ? (
        <div style={{ ...glassCard, textAlign: "center", padding: 32, borderRadius: 20 }}>
          <div style={{ width: 68, height: 68, borderRadius: 20, margin: "0 auto 14px", background: partyGradient, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 32, boxShadow: "0 14px 28px rgba(255,145,0,0.18)" }}>🎉</div>
          <div style={{ fontSize: 16, color: textColor, fontWeight: 700, marginBottom: 8 }}>У тебя пока нет пати</div>
          <div style={{ fontSize: 12, color: hintColor }}>Создай пати и слушай музыку вместе с друзьями!</div>
        </div>
      ) : (
        myParties.map((p) => (
          <div key={p.id} onClick={() => handleJoinParty(p.invite_code)} style={{
            display: "flex", alignItems: "center", padding: "14px 14px", borderRadius: 18, cursor: "pointer",
            ...softCard, marginBottom: 8, boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05)",
          }}>
            <div style={{
              width: 42, height: 42, borderRadius: 12, marginRight: 12, flexShrink: 0,
              background: partyGradient, display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 20, boxShadow: "0 10px 22px rgba(255,145,0,0.18)",
            }}>🎉</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: textColor }}>{p.name}</div>
              <div style={{ fontSize: 12, color: hintColor }}>
                {p.tracks.length} треков · 👥 {p.member_count} online
              </div>
            </div>
            <div style={{ fontSize: 12, color: hintColor }}>
              <code style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", padding: "2px 6px", borderRadius: 6 }}>{p.invite_code}</code>
            </div>
          </div>
        ))
      )}

      <div style={{ marginTop: 16, padding: 14, borderRadius: 16, ...softCard, fontSize: 12, color: hintColor, textAlign: "center" }}>
        Или присоединись по ссылке от друга — треки синхронизируются в реальном времени 🔄
      </div>
    </div>
  );
}
