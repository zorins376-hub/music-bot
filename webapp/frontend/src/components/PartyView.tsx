import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchParty, addPartyTrack, removePartyTrack, skipPartyTrack, closeParty,
  createParty, fetchMyParties, searchTracks,
  type Party, type PartyTrack, type Track,
} from "../api";
import { IconArrowLeft, IconMusic, IconSpinner, IconSearch, IconPlus } from "./Icons";

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
  const cardBg = warm ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)";
  const cardBorder = warm ? "1px solid rgba(255, 213, 79, 0.1)" : "1px solid rgba(255,255,255,0.06)";
  const activeBg = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))"
    : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.3))`;
  const partyGradient = "linear-gradient(135deg, #ff6d00, #ff9100, #ffd600)";

  const isDJ = party ? party.creator_id === userId : false;

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  // SSE connection for real-time updates
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

    es.onerror = () => {
      // Auto-reconnect handled by EventSource spec
    };
  }, []);

  // Load initial party or list
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

  // Search with debounce
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
    // Use Telegram's share functionality
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(`https://t.me/${botUsername}?startapp=party_${party.invite_code}`)}&text=${encodeURIComponent(`🎉 Заходи на пати «${party.name}»! Добавляй свои треки 🎶`)}`;
    window.open(shareUrl, "_blank");
  };

  // Toast notification
  const Toast = toast ? (
    <div style={{
      position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
      padding: "10px 20px", borderRadius: 14, fontSize: 13, fontWeight: 600,
      background: warm ? "rgba(40, 25, 15, 0.9)" : "rgba(0,0,0,0.85)",
      color: "#fff", zIndex: 99999, backdropFilter: "blur(12px)",
      border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(255,255,255,0.1)",
      animation: "fadeIn 0.3s ease",
    }}>
      {toast}
    </div>
  ) : null;

  if (loading && !party && !myParties.length) {
    return <div style={{ textAlign: "center", padding: 32 }}><IconSpinner size={24} color={hintColor} /></div>;
  }

  // ── Party Room ──
  if (party) {
    const currentTrack = party.tracks.find(t => t.position === party.current_position);
    const upNext = party.tracks.filter(t => t.position > party.current_position).sort((a, b) => a.position - b.position);
    const played = party.tracks.filter(t => t.position < party.current_position).sort((a, b) => a.position - b.position);

    return (
      <div>
        {Toast}

        {/* Party Header */}
        <div style={{
          padding: "14px 16px", borderRadius: 18, marginBottom: 12,
          background: partyGradient, position: "relative", overflow: "hidden",
        }}>
          <div style={{ position: "relative", zIndex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#000" }}>{party.name}</div>
              <div style={{
                padding: "4px 10px", borderRadius: 10, fontSize: 11, fontWeight: 700,
                background: "rgba(0,0,0,0.2)", color: "#fff",
              }}>
                👥 {party.member_count} online
              </div>
            </div>
            <div style={{ fontSize: 12, color: "rgba(0,0,0,0.6)", marginTop: 4 }}>
              {isDJ ? "🎧 Ты DJ — управляй очередью" : "Добавляй треки в общую очередь"}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button onClick={handleShare} style={{
                flex: 1, padding: "8px 0", borderRadius: 12, border: "none",
                background: "rgba(0,0,0,0.2)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
              }}>📤 Поделиться</button>
              {isDJ && (
                <button onClick={handleClose} style={{
                  padding: "8px 14px", borderRadius: 12, border: "none",
                  background: "rgba(229,57,53,0.8)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}>🏁 Закрыть</button>
              )}
            </div>
          </div>
        </div>

        {/* Now Playing */}
        {currentTrack && (
          <div style={{
            padding: "12px 14px", borderRadius: 16, marginBottom: 10,
            background: warm ? "rgba(255, 109, 0, 0.15)" : "rgba(124, 77, 255, 0.12)",
            border: warm ? "1px solid rgba(255,109,0,0.25)" : "1px solid rgba(124,77,255,0.2)",
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5, color: hintColor, marginBottom: 6 }}>▶ Сейчас играет</div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 50, height: 50, borderRadius: 12, overflow: "hidden", flexShrink: 0,
                background: warm ? "rgba(255,213,79,0.08)" : "rgba(124,77,255,0.08)",
              }}>
                {currentTrack.cover_url ? <img src={currentTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusic size={24} color={hintColor} /></div>}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{currentTrack.title}</div>
                <div style={{ fontSize: 12, color: hintColor }}>{currentTrack.artist} · {currentTrack.added_by_name || "?"}</div>
              </div>
              <button onClick={() => { haptic("light"); onPlayTrack(currentTrack); }} style={{
                padding: "8px 14px", borderRadius: 12, border: "none",
                background: activeBg, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
              }}>▶</button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={handleSkip} style={{
                flex: 1, padding: "7px 0", borderRadius: 10, border: cardBorder,
                background: "transparent", color: hintColor, fontSize: 12, cursor: "pointer",
              }}>
                {isDJ ? "⏭ Пропустить" : `⏭ Vote Skip (${currentTrack.skip_votes}/3)`}
              </button>
            </div>
          </div>
        )}

        {/* Add Track button */}
        <button onClick={() => { haptic("light"); setShowSearch(true); }} style={{
          width: "100%", padding: "12px 0", borderRadius: 14, border: cardBorder,
          background: cardBg, color: textColor, fontSize: 14, fontWeight: 600,
          cursor: "pointer", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
          backdropFilter: warm ? "blur(12px)" : undefined,
        }}>
          <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} /> Добавить трек
        </button>

        {/* Search overlay */}
        {showSearch && (
          <div style={{
            padding: 12, borderRadius: 16, marginBottom: 10,
            background: cardBg, border: cardBorder,
            backdropFilter: warm ? "blur(12px)" : undefined,
          }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <input
                type="text" placeholder="Поиск треков..." value={searchQuery}
                onInput={(e: any) => setSearchQuery(e.target.value)}
                autoFocus
                style={{
                  flex: 1, padding: "8px 12px", borderRadius: 10,
                  border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)",
                  background: "transparent", color: textColor, fontSize: 14, outline: "none",
                }}
              />
              <button onClick={() => { setShowSearch(false); setSearchQuery(""); setSearchResults([]); }} style={{
                padding: "8px 12px", borderRadius: 10, border: cardBorder,
                background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer",
              }}>✕</button>
            </div>
            {searching && <div style={{ textAlign: "center", padding: 12 }}><IconSpinner size={18} color={hintColor} /></div>}
            {searchResults.map((t) => (
              <div key={t.video_id} onClick={() => handleAddTrack(t)} style={{
                display: "flex", alignItems: "center", padding: "8px 10px", borderRadius: 12, cursor: "pointer",
                marginBottom: 4, background: "transparent",
              }}>
                <div style={{ width: 38, height: 38, borderRadius: 8, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)" }}>
                  {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <IconMusic size={18} color={hintColor} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: hintColor }}>{t.artist}</div>
                </div>
                <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} />
              </div>
            ))}
          </div>
        )}

        {/* Up Next */}
        {upNext.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5, color: hintColor, marginBottom: 6 }}>
              Далее · {upNext.length} треков
            </div>
            {upNext.map((t) => (
              <div key={t.video_id} style={{
                display: "flex", alignItems: "center", padding: "10px 12px", borderRadius: 14,
                background: cardBg, border: cardBorder, marginBottom: 4, cursor: "pointer",
                backdropFilter: warm ? "blur(12px)" : undefined,
              }} onClick={() => { haptic("light"); onPlayTrack(t); }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)" }}>
                  {t.cover_url ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusic size={18} color={hintColor} /></div>}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: hintColor }}>{t.artist} · {t.added_by_name || "?"}</div>
                </div>
                <div style={{ fontSize: 11, color: hintColor, flexShrink: 0 }}>{t.duration_fmt}</div>
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

        {/* Already played */}
        {played.length > 0 && (
          <div style={{ opacity: 0.5 }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5, color: hintColor, marginBottom: 6 }}>
              Уже играло · {played.length}
            </div>
            {played.map((t) => (
              <div key={t.video_id} style={{
                display: "flex", alignItems: "center", padding: "8px 10px", borderRadius: 12,
                marginBottom: 4,
              }}>
                <div style={{ width: 34, height: 34, borderRadius: 8, overflow: "hidden", flexShrink: 0, marginRight: 10, background: warm ? "rgba(255,213,79,0.04)" : "rgba(124,77,255,0.04)" }}>
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
          <div style={{ textAlign: "center", color: hintColor, padding: 32, fontSize: 14 }}>
            Очередь пуста — добавь первый трек! 🎵
          </div>
        )}
      </div>
    );
  }

  // ── Party List (no active party) ──
  return (
    <div>
      {Toast}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: textColor, letterSpacing: 0.4 }}>🎉 Party Playlists</div>
        <button onClick={() => { haptic("light"); setShowCreate(true); }} style={{
          padding: "6px 14px", borderRadius: 14, border: "none",
          background: partyGradient, color: "#000", fontSize: 12, fontWeight: 700, cursor: "pointer",
        }}>+ Создать</button>
      </div>

      {showCreate && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12, padding: 12, borderRadius: 16, background: cardBg, border: cardBorder }}>
          <input type="text" placeholder="Название пати" maxLength={100} value={newName}
            onInput={(e: any) => setNewName(e.target.value)}
            onKeyDown={(e: any) => { if (e.key === "Enter") handleCreate(); }}
            style={{ flex: 1, padding: "8px 12px", borderRadius: 10, border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)", background: "transparent", color: textColor, fontSize: 14, outline: "none" }} />
          <button onClick={handleCreate} style={{ padding: "8px 16px", borderRadius: 10, border: "none", background: partyGradient, color: "#000", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>🎉 Go</button>
          <button onClick={() => { setShowCreate(false); setNewName(""); }} style={{ padding: "8px 12px", borderRadius: 10, border: cardBorder, background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer" }}>✕</button>
        </div>
      )}

      {myParties.length === 0 && !showCreate ? (
        <div style={{ textAlign: "center", padding: 32 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🎉</div>
          <div style={{ fontSize: 14, color: hintColor, marginBottom: 8 }}>У тебя пока нет пати</div>
          <div style={{ fontSize: 12, color: hintColor }}>Создай пати и слушай музыку вместе с друзьями!</div>
        </div>
      ) : (
        myParties.map((p) => (
          <div key={p.id} onClick={() => handleJoinParty(p.invite_code)} style={{
            display: "flex", alignItems: "center", padding: "12px 14px", borderRadius: 14, cursor: "pointer",
            background: cardBg, border: cardBorder, marginBottom: 6,
            backdropFilter: warm ? "blur(12px)" : undefined,
          }}>
            <div style={{
              width: 42, height: 42, borderRadius: 12, marginRight: 12, flexShrink: 0,
              background: partyGradient, display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 20,
            }}>🎉</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 500, color: textColor }}>{p.name}</div>
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

      <div style={{ marginTop: 16, padding: 12, borderRadius: 14, background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)", border: warm ? "1px solid rgba(255,213,79,0.12)" : "1px solid rgba(124,77,255,0.1)", fontSize: 12, color: hintColor, textAlign: "center" }}>
        Или присоединись по ссылке от друга — треки синхронизируются в реальном времени 🔄
      </div>
    </div>
  );
}
