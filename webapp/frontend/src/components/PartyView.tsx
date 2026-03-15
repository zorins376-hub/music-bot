import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import {
  fetchParty, addPartyTrack, removePartyTrack, skipPartyTrack, closeParty,
  clearPartyChat, createParty, deletePartyChatMessage, fetchLyrics, fetchMyParties, fetchPartyRecap, playNextPartyTrack, reactToPartyTrack, reorderPartyTrack, runPartyAutoDj, savePartyAsPlaylist, searchTracks, sendPartyChat, syncPartyPlayback, updatePartyMemberRole,
  type Party, type PartyRecap, type Track,
} from "../api";
import { IconMusic, IconSpinner, IconSearch, IconPlus, IconUsers, IconTV, IconHeadphones, IconUpload, IconSparkles, IconRobot, IconSave, IconFlag, IconTrophy, IconFire, IconHeartFilled, IconBolt, IconDisco, IconPicture, IconClipboard, IconClock, IconClose, IconParty, IconSync } from "./Icons";
import { showToast as globalToast } from "./Toast";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  onPlaybackAction?: (action: "play" | "pause" | "seek", track?: Track, position?: number) => void | Promise<void>;
  accentColor?: string;
  themeId?: string;
  initialCode?: string | null;
  readOnlyMode?: boolean;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function PartyView({ userId, onPlayTrack, onPlaybackAction, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom", initialCode, readOnlyMode = false }: Props) {
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
  const [recap, setRecap] = useState<PartyRecap | null>(null);
  const [reactionBursts, setReactionBursts] = useState<Array<{ id: number; emoji: string; left: number }>>([]);
  const [livePosition, setLivePosition] = useState(0);
  const [showStageMode, setShowStageMode] = useState(false);
  const [showTvMode, setShowTvMode] = useState(false);
  const [chatMessage, setChatMessage] = useState("");
  const [lyrics, setLyrics] = useState<string[]>([]);
  const [lyricsLoading, setLyricsLoading] = useState(false);
  const [transitionFx, setTransitionFx] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [showConfirmClose, setShowConfirmClose] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement | null>(null);
  const [moreMenuPos, setMoreMenuPos] = useState<{ top: number; right: number } | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const syncIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reactionBurstIdRef = useRef(0);
  const lastTrackIdRef = useRef<string | null>(null);
  const onPlaybackActionRef = useRef(onPlaybackAction);
  onPlaybackActionRef.current = onPlaybackAction;

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

  const isDJ = !readOnlyMode && party ? party.viewer_role === "dj" : false;
  const canControl = !readOnlyMode && party ? ["dj", "cohost"].includes(party.viewer_role) : false;

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  const formatDuration = (totalSeconds: number) => {
    const safeSeconds = Math.max(0, Math.floor(totalSeconds || 0));
    const minutes = Math.floor(safeSeconds / 60);
    const seconds = safeSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
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
        if (msg.event === "closed") {
          showToast("Пати завершена!");
          setParty(null);
          return;
        }

        if (msg.event === "member_joined" && msg.data.name) {
          showToast(`${msg.data.name} присоединился`);
        }
        if (msg.event === "track_added") {
          showToast(`${msg.data.added_by_name} добавил: ${msg.data.title}`);
        }
        if (msg.event === "reaction" && msg.data?.emoji) {
          const burstId = reactionBurstIdRef.current + 1;
          reactionBurstIdRef.current = burstId;
          setReactionBursts((prev) => [...prev, { id: burstId, emoji: String(msg.data.emoji), left: 18 + Math.random() * 64 }]);
          setTimeout(() => {
            setReactionBursts((prev) => prev.filter((burst) => burst.id !== burstId));
          }, 900);
        }

        fetchParty(code).then((updatedParty) => {
          setParty(updatedParty);
          if (msg.event === "playback_sync") {
            const action = msg.data?.action as "play" | "pause" | "seek" | undefined;
            const seekPosition = Number(msg.data?.seek_position || 0);
            const syncedTrack = updatedParty.tracks.find((t) => t.position === Number(msg.data?.track_position ?? updatedParty.current_position));
            if (action === "play" && syncedTrack) {
              void onPlaybackActionRef.current?.("play", syncedTrack, seekPosition);
            } else if (action === "pause") {
              void onPlaybackActionRef.current?.("pause", undefined, seekPosition);
            } else if (action === "seek") {
              void onPlaybackActionRef.current?.("seek", undefined, seekPosition);
            }
          }
        }).catch(() => {});
      } catch {}
    };

    es.onerror = () => {
      // Reconnect on error after 2s delay
      es.close();
      setTimeout(() => {
        if (eventSourceRef.current === es) {
          connectSSE(code);
        }
      }, 2000);
    };
  }, []);

  const handleSyncPlayback = async (action: "play" | "pause" | "seek", trackPosition: number, seekPosition = 0, track?: Track) => {
    if (!party) return;
    try {
      const updated = await syncPartyPlayback(party.invite_code, action, trackPosition, seekPosition);
      setParty(updated);
      if (action === "play" && track) {
        await onPlaybackAction?.("play", track, seekPosition);
      } else if (action === "pause") {
        await onPlaybackAction?.("pause", undefined, seekPosition);
      } else if (action === "seek") {
        await onPlaybackAction?.("seek", undefined, seekPosition);
      }
    } catch {
      showToast("Не удалось синхронизировать playback");
    }
  };

  const handleRoleToggle = async (memberUserId: number, currentRole: string) => {
    if (!party) return;
    try {
      const updated = await updatePartyMemberRole(party.invite_code, memberUserId, currentRole === "cohost" ? "listener" : "cohost");
      setParty(updated);
    } catch {
      showToast("Не удалось обновить роль");
    }
  };

  const handleMoveTrack = async (fromPosition: number, toPosition: number) => {
    if (!party) return;
    try {
      const updated = await reorderPartyTrack(party.invite_code, fromPosition, toPosition);
      setParty(updated);
    } catch {
      showToast("Не удалось изменить порядок");
    }
  };

  const handlePlayNext = async (videoId: string) => {
    if (!party) return;
    try {
      const updated = await playNextPartyTrack(party.invite_code, videoId);
      setParty(updated);
    } catch {
      showToast("Не удалось перенести трек наверх");
    }
  };

  const handleSavePlaylist = async () => {
    if (!party) return;
    try {
      const playlist = await savePartyAsPlaylist(party.invite_code);
      showToast(`Сохранено в плейлист: ${playlist.name}`);
    } catch {
      showToast("Не удалось сохранить пати");
    }
  };

  const handleReaction = async (emoji: string) => {
    if (!party) return;
    const burstId = reactionBurstIdRef.current + 1;
    reactionBurstIdRef.current = burstId;
    setReactionBursts((prev) => [...prev, { id: burstId, emoji, left: 18 + Math.random() * 64 }]);
    setTimeout(() => {
      setReactionBursts((prev) => prev.filter((burst) => burst.id !== burstId));
    }, 900);
    try {
      const updated = await reactToPartyTrack(party.invite_code, emoji);
      setParty(updated);
    } catch {
      showToast("Не удалось отправить реакцию");
    }
  };

  const handleAutoDj = async () => {
    if (!party) return;
    try {
      const updated = await runPartyAutoDj(party.invite_code, 5);
      setParty(updated);
      showToast("Auto-DJ добавил новые треки");
    } catch {
      showToast("Auto-DJ не смог подобрать треки");
    }
  };

  const handleSendChat = async () => {
    if (!party || !chatMessage.trim()) return;
    try {
      const updated = await sendPartyChat(party.invite_code, chatMessage.trim());
      setParty(updated);
      setChatMessage("");
    } catch {
      showToast("Не удалось отправить сообщение");
    }
  };

  const handleDeleteChatMessage = async (messageId: number) => {
    if (!party) return;
    try {
      const updated = await deletePartyChatMessage(party.invite_code, messageId);
      setParty(updated);
      showToast("Сообщение удалено");
    } catch {
      showToast("Не удалось удалить сообщение");
    }
  };

  const handleClearChat = async () => {
    if (!party) return;
    try {
      const updated = await clearPartyChat(party.invite_code);
      setParty(updated);
      showToast("Чат очищен");
    } catch {
      showToast("Не удалось очистить чат");
    }
  };

  useEffect(() => {
    if (!party) {
      setRecap(null);
      return;
    }
    fetchPartyRecap(party.invite_code).then(setRecap).catch(() => {});
  }, [party?.invite_code, party?.tracks.length, party?.events.length, party?.member_count]);

  useEffect(() => {
    const currentTrack = party?.tracks.find((t) => t.position === party.current_position);
    if (!party || !currentTrack) {
      setLivePosition(0);
      return;
    }
    if (party.playback.track_position === currentTrack.position) {
      setLivePosition(Math.min(currentTrack.duration || 0, party.playback.seek_position || 0));
    } else {
      setLivePosition(0);
    }
  }, [party?.current_position, party?.playback.track_position, party?.playback.seek_position, party?.tracks]);

  useEffect(() => {
    const currentTrack = party?.tracks.find((t) => t.position === party.current_position);
    if (!party || !currentTrack || party.playback.action !== "play") {
      return;
    }
    const timer = setInterval(() => {
      setLivePosition((prev) => Math.min(currentTrack.duration || 0, prev + 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [party?.current_position, party?.playback.action, party?.tracks]);

  useEffect(() => {
    const currentTrack = party?.tracks.find((t) => t.position === party.current_position);
    if (!currentTrack?.video_id) {
      setLyrics([]);
      setLyricsLoading(false);
      return;
    }
    setLyricsLoading(true);
    fetchLyrics(currentTrack.video_id)
      .then((text) => {
        const lines = (text || "")
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean)
          .slice(0, 24);
        setLyrics(lines);
      })
      .catch(() => setLyrics([]))
      .finally(() => setLyricsLoading(false));
  }, [party?.current_position, party?.tracks]);

  useEffect(() => {
    const currentTrack = party?.tracks.find((t) => t.position === party.current_position);
    const trackId = currentTrack?.video_id || null;
    if (!trackId) {
      lastTrackIdRef.current = null;
      return;
    }
    if (lastTrackIdRef.current && lastTrackIdRef.current !== trackId) {
      setTransitionFx(true);
      setTimeout(() => setTransitionFx(false), 850);
    }
    lastTrackIdRef.current = trackId;
  }, [party?.current_position, party?.tracks]);

  useEffect(() => {
    if (!showStageMode && !showTvMode) {
      document.body.style.overflow = "";
      return;
    }
    document.body.style.overflow = "hidden";
    try { window.Telegram?.WebApp?.expand?.(); } catch {}
    return () => {
      document.body.style.overflow = "";
    };
  }, [showStageMode, showTvMode]);

  useEffect(() => {
    if (initialCode) {
      setLoading(true);
      fetchParty(initialCode)
        .then((p) => {
          setParty(p);
          connectSSE(initialCode);
        })
        .catch(() => showToast("Пати не найдена"))
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
      if (syncIntervalRef.current) clearInterval(syncIntervalRef.current);
    };
  }, [initialCode, connectSSE]);

  // Periodic playback re-sync: refresh party state every 15s to catch drift
  useEffect(() => {
    if (!party) {
      if (syncIntervalRef.current) { clearInterval(syncIntervalRef.current); syncIntervalRef.current = null; }
      return;
    }
    syncIntervalRef.current = setInterval(() => {
      fetchParty(party.invite_code).then(setParty).catch(() => {});
    }, 15000);
    return () => { if (syncIntervalRef.current) clearInterval(syncIntervalRef.current); };
  }, [party?.invite_code]);

  // Track transition animation — detect track change
  useEffect(() => {
    if (!party) return;
    const ct = party.tracks.find(t => t.position === party.current_position);
    const newId = ct?.video_id || null;
    if (lastTrackIdRef.current && newId && newId !== lastTrackIdRef.current) {
      setTransitionFx(true);
      setTimeout(() => setTransitionFx(false), 600);
    }
    lastTrackIdRef.current = newId;
  }, [party?.current_position]);

  // Mark offline on tab close
  useEffect(() => {
    const onBeforeUnload = () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

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
    const name = newName.trim() || "Party";
    haptic("medium");
    try {
      const p = await createParty(name);
      setParty(p);
      connectSSE(p.invite_code);
      setShowCreate(false);
      setNewName("");
    } catch {
      showToast("Не удалось создать пати");
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
      showToast("Пати не найдена");
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
    } catch (err: any) {
      const detail = err?.message || "";
      if (detail.includes("409") || detail.includes("already")) {
        showToast("Этот трек уже в очереди");
      } else {
        showToast("Ошибка при добавлении");
      }
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
      showToast("Ошибка");
    }
  };

  const handleClose = async () => {
    if (!party) return;
    if (!showConfirmClose) {
      setShowConfirmClose(true);
      return;
    }
    haptic("heavy");
    setShowConfirmClose(false);
    try {
      await closeParty(party.invite_code);
      setParty(null);
      eventSourceRef.current?.close();
    } catch {
      showToast("Только DJ может закрыть пати");
    }
  };

  const handleShare = () => {
    if (!party) return;
    haptic("light");
    const botUsername = window.Telegram?.WebApp?.initDataUnsafe?.user?.username || "musicbot";
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(`https://t.me/${botUsername}?startapp=party_${party.invite_code}`)}&text=${encodeURIComponent(`🎉 Заходи на пати «${party.name}»! Добавляй свои треки 🎶`)}`;
    window.open(shareUrl, "_blank");
  };

  const handleShareTv = () => {
    if (!party) return;
    haptic("light");
    const botUsername = window.Telegram?.WebApp?.initDataUnsafe?.user?.username || "musicbot";
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(`https://t.me/${botUsername}?startapp=partytv_${party.invite_code}`)}&text=${encodeURIComponent(`📺 Смотри Party TV «${party.name}» в live-режиме`)}`;
    window.open(shareUrl, "_blank");
  };

  const handleShareRecap = async () => {
    if (!party || !recap) return;
    haptic("light");
    const summary = [
      `Recap пати «${party.name}»`,
      `Треков: ${recap.total_tracks}`,
      `Участников: ${recap.total_members}`,
      `Длительность: ${formatDuration(recap.total_duration)}`,
      `Skip votes: ${recap.total_skip_votes}`,
      recap.top_artists[0] ? `Топ артист: ${recap.top_artists[0].label}` : null,
      `#${party.invite_code}`,
    ].filter(Boolean).join("\n");
    const botUsername = window.Telegram?.WebApp?.initDataUnsafe?.user?.username || "musicbot";
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(`https://t.me/${botUsername}?startapp=party_${party.invite_code}`)}&text=${encodeURIComponent(summary)}`;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(summary);
        showToast("Recap скопирован");
      }
    } catch {}
    window.open(shareUrl, "_blank");
  };

  const handleDownloadRecapPoster = () => {
    if (!party || !recap) return;
    const escapeXml = (value: string) => value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&apos;");
    const topArtist = recap.top_artists[0]?.label || "Party vibe";
    const topContributor = recap.top_contributors[0]?.label || "Your crew";
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1600" viewBox="0 0 1200 1600">
        <defs>
          <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#7c4dff"/>
            <stop offset="55%" stop-color="#311b92"/>
            <stop offset="100%" stop-color="#ff9100"/>
          </linearGradient>
        </defs>
        <rect width="1200" height="1600" rx="56" fill="url(#bg)"/>
        <circle cx="980" cy="180" r="180" fill="rgba(255,255,255,0.10)"/>
        <circle cx="180" cy="1320" r="220" fill="rgba(255,255,255,0.08)"/>
        <text x="100" y="140" fill="#ffffff" font-size="42" font-family="Arial, sans-serif" font-weight="700">Party recap</text>
        <text x="100" y="220" fill="#ffffff" font-size="84" font-family="Arial, sans-serif" font-weight="800">${escapeXml(party.name)}</text>
        <text x="100" y="290" fill="rgba(255,255,255,0.84)" font-size="30" font-family="Arial, sans-serif">#${escapeXml(party.invite_code)}</text>
        <rect x="100" y="380" width="480" height="180" rx="36" fill="rgba(255,255,255,0.12)"/>
        <rect x="620" y="380" width="480" height="180" rx="36" fill="rgba(255,255,255,0.12)"/>
        <rect x="100" y="600" width="480" height="180" rx="36" fill="rgba(255,255,255,0.12)"/>
        <rect x="620" y="600" width="480" height="180" rx="36" fill="rgba(255,255,255,0.12)"/>
        <text x="140" y="450" fill="rgba(255,255,255,0.72)" font-size="28" font-family="Arial, sans-serif">Tracks</text>
        <text x="140" y="530" fill="#ffffff" font-size="74" font-family="Arial, sans-serif" font-weight="800">${recap.total_tracks}</text>
        <text x="660" y="450" fill="rgba(255,255,255,0.72)" font-size="28" font-family="Arial, sans-serif">Members</text>
        <text x="660" y="530" fill="#ffffff" font-size="74" font-family="Arial, sans-serif" font-weight="800">${recap.total_members}</text>
        <text x="140" y="670" fill="rgba(255,255,255,0.72)" font-size="28" font-family="Arial, sans-serif">Duration</text>
        <text x="140" y="750" fill="#ffffff" font-size="74" font-family="Arial, sans-serif" font-weight="800">${formatDuration(recap.total_duration)}</text>
        <text x="660" y="670" fill="rgba(255,255,255,0.72)" font-size="28" font-family="Arial, sans-serif">Events</text>
        <text x="660" y="750" fill="#ffffff" font-size="74" font-family="Arial, sans-serif" font-weight="800">${recap.events_count}</text>
        <text x="100" y="930" fill="#ffffff" font-size="34" font-family="Arial, sans-serif" font-weight="700">Top artist</text>
        <text x="100" y="995" fill="rgba(255,255,255,0.88)" font-size="54" font-family="Arial, sans-serif" font-weight="800">${escapeXml(topArtist)}</text>
        <text x="100" y="1110" fill="#ffffff" font-size="34" font-family="Arial, sans-serif" font-weight="700">Top contributor</text>
        <text x="100" y="1175" fill="rgba(255,255,255,0.88)" font-size="54" font-family="Arial, sans-serif" font-weight="800">${escapeXml(topContributor)}</text>
        <text x="100" y="1360" fill="rgba(255,255,255,0.78)" font-size="34" font-family="Arial, sans-serif">Made in Music Party</text>
      </svg>
    `.trim();
    const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `party-recap-${party.invite_code}.svg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast("Poster downloaded");
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
    const progressPercent = currentTrack?.duration ? Math.min(100, (livePosition / currentTrack.duration) * 100) : 0;
    const orbitMembers = party.members.slice(0, 6);
    const recentReactionEvents = party.events.filter((event) => event.event_type === "reaction").slice(-5).reverse();
    const chatMessages = party.chat_messages.slice(-12);
    const activeLyricIndex = currentTrack && lyrics.length > 0 && currentTrack.duration > 0
      ? Math.min(lyrics.length - 1, Math.floor((livePosition / currentTrack.duration) * lyrics.length))
      : -1;

    return (
      <div style={{ background: shellBg, borderRadius: 26, padding: 2 }}>
        {Toast}

        {/* More menu — rendered as fixed overlay to escape overflow:hidden parents */}
        {showMoreMenu && moreMenuPos && (
          <>
            <div onClick={() => setShowMoreMenu(false)} style={{ position: "fixed", inset: 0, zIndex: 9998 }} />
            <div style={{
              position: "fixed", top: moreMenuPos.top, right: moreMenuPos.right, zIndex: 9999,
              background: warm ? "rgba(40, 24, 14, 0.96)" : "rgba(20, 18, 35, 0.96)",
              border: cardBorder, borderRadius: 16, padding: 6, minWidth: 170,
              boxShadow: "0 16px 40px rgba(0,0,0,0.4)",
              backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)",
            }}>
              <button onClick={() => { handleShareTv(); setShowMoreMenu(false); }} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconTV size={14} /> Share TV</button>
              {currentTrack && <button onClick={() => { setShowStageMode(true); setShowMoreMenu(false); }} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconSparkles size={14} /> Stage mode</button>}
              {currentTrack && <button onClick={() => { setShowTvMode(true); setShowMoreMenu(false); }} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconTV size={14} /> TV mode</button>}
              {!readOnlyMode && <button onClick={() => { handleSavePlaylist(); setShowMoreMenu(false); }} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconSave size={14} /> Сохранить плейлист</button>}
              {isDJ && <div style={{ height: 1, background: "rgba(255,255,255,0.08)", margin: "4px 0" }} />}
              {isDJ && (
                showConfirmClose
                  ? <button onClick={() => { handleClose(); setShowMoreMenu(false); }} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "rgba(229,57,53,0.3)", color: "#ff5252", fontSize: 12, fontWeight: 800, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconFlag size={14} /> Точно закрыть?</button>
                  : <button onClick={handleClose} style={{ width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#ff5252", fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 8 }}><IconFlag size={14} /> Закрыть пати</button>
              )}
            </div>
          </>
        )}

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
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><IconUsers size={13} /> {party.member_count} online</span>
              </div>
            </div>
            <div style={{ fontSize: 12, color: "rgba(24,13,0,0.7)", marginTop: 6, lineHeight: 1.45 }}>
<span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>{readOnlyMode ? <><IconTV size={13} /> Режим витрины — только просмотр live room</> : (isDJ ? <><IconHeadphones size={13} /> Ты DJ — управляй очередью</> : "Добавляй треки в общую очередь")}</span>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.16)", color: "#fff", fontSize: 11, fontWeight: 700 }}>#{party.invite_code}</div>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.12)", color: "rgba(255,255,255,0.92)", fontSize: 11, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconMusic size={13} /> {party.tracks.length} треков</div>
              <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.12)", color: "rgba(255,255,255,0.92)", fontSize: 11, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}>{readOnlyMode ? <><IconTV size={12} /> read-only</> : (isDJ ? <><IconTrophy size={12} /> DJ mode</> : <><IconSparkles size={12} /> listener</>)}</div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button onClick={handleShare} style={{
                flex: 1, padding: "10px 0", borderRadius: 14, border: "1px solid rgba(255,255,255,0.14)",
                background: "rgba(0,0,0,0.22)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                boxShadow: "inset 0 1px 0 rgba(255,255,255,0.12)", display: "flex", alignItems: "center", justifyContent: "center", gap: 6
              }}><IconUpload size={14} /> Поделиться</button>
              {canControl && (
                <button onClick={handleAutoDj} style={{
                  padding: "10px 12px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.14)",
                  background: "rgba(0,0,0,0.18)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: 5
                }}><IconRobot size={14} /> Auto-DJ</button>
              )}
              <button ref={moreButtonRef} onClick={() => {
                if (!showMoreMenu && moreButtonRef.current) {
                  const rect = moreButtonRef.current.getBoundingClientRect();
                  setMoreMenuPos({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
                }
                setShowMoreMenu(!showMoreMenu);
              }} style={{
                padding: "10px 14px", borderRadius: 14, border: "1px solid rgba(255,255,255,0.14)",
                background: showMoreMenu ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.06)", color: "#fff", fontSize: 14, fontWeight: 800, cursor: "pointer",
              }}>⋯</button>
            </div>
          </div>
        </div>

        {party.members.length > 0 && (
          <div style={{ ...glassCard, padding: 12, borderRadius: 18, marginBottom: 12 }}>
            <div style={{ ...sectionLabel, marginBottom: 10 }}>Участники · {party.member_count} online</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {party.members.map((member) => (
                <div key={member.user_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}>
                  <div style={{ width: 30, height: 30, borderRadius: 999, background: member.is_online ? activeBg : "rgba(255,255,255,0.08)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, flexShrink: 0 }}>
                    {(member.display_name || "U").slice(0, 1).toUpperCase()}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: textColor, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{member.display_name || `User ${member.user_id}`}</div>
                    <div style={{ fontSize: 11, color: hintColor }}>{member.role}{member.is_online ? " · online" : " · offline"}</div>
                  </div>
                  {isDJ && member.user_id !== userId && member.role !== "dj" && (
                    <button onClick={() => handleRoleToggle(member.user_id, member.role)} style={{ padding: "6px 10px", borderRadius: 10, border: cardBorder, background: "transparent", color: warm ? "#ffd54f" : accentColor, fontSize: 11, fontWeight: 700, cursor: "pointer" }}>
                      {member.role === "cohost" ? "Снять host" : "+ Host"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {currentTrack && (
          <div style={{
            padding: "14px 14px", borderRadius: 18, marginBottom: 12,
            background: warm ? "rgba(255, 109, 0, 0.15)" : "rgba(124, 77, 255, 0.12)",
            border: warm ? "1px solid rgba(255,109,0,0.25)" : "1px solid rgba(124,77,255,0.2)",
            boxShadow: warm ? "0 14px 34px rgba(255,109,0,0.12)" : "0 14px 34px rgba(124,77,255,0.12)",
            backdropFilter: "blur(16px) saturate(135%)",
            transition: "transform 0.3s ease, opacity 0.3s ease",
            transform: transitionFx ? "scale(0.97)" : "scale(1)",
            opacity: transitionFx ? 0.7 : 1,
            WebkitBackdropFilter: "blur(16px) saturate(135%)",
            position: "relative",
            overflow: "hidden",
          }}>
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <span>▶ Сейчас играет</span>
              <span style={{ color: warm ? "#ffd54f" : accentColor, fontSize: 10 }}>{party.playback.action === "pause" ? "Paused room" : (isDJ ? "DJ control" : "Live sync")}</span>
            </div>
            {reactionBursts.map((burst) => (
              <div key={burst.id} style={{
                position: "absolute",
                left: `${burst.left}%`,
                bottom: 18,
                fontSize: 22,
                pointerEvents: "none",
                animation: "partyReactionFloat 0.9s ease-out forwards",
                filter: "drop-shadow(0 10px 14px rgba(0,0,0,0.18))",
              }}>
                {burst.emoji}
              </div>
            ))}
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
                <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 18, marginTop: 10 }}>
                  {[0, 1, 2, 3, 4, 5].map((bar) => (
                    <span key={bar} style={{
                      width: 4,
                      height: party.playback.action === "play" ? 8 + ((bar % 3) * 4) : 8,
                      borderRadius: 999,
                      background: warm ? "linear-gradient(180deg, #ffd54f, #ff8f00)" : activeBg,
                      animation: party.playback.action === "play" ? `partyEqualizer 1s ${bar * 0.12}s ease-in-out infinite` : "none",
                      transformOrigin: "bottom center",
                    }} />
                  ))}
                </div>
              </div>
              <button onClick={() => { haptic("light"); onPlayTrack(currentTrack); }} style={{
                padding: "10px 14px", borderRadius: 14, border: "none",
                background: activeBg, color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                boxShadow: warm ? "0 10px 24px rgba(255,109,0,0.2)" : `0 10px 24px ${accentColor}33`,
              }}>▶</button>
            </div>
            <div style={{ marginTop: 10 }}>
              <div style={{ height: 7, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                <div style={{
                  width: `${progressPercent}%`,
                  height: "100%",
                  borderRadius: 999,
                  background: activeBg,
                  boxShadow: warm ? "0 0 18px rgba(255,193,7,0.24)" : `0 0 18px ${accentColor}55`,
                  transition: "width 0.9s linear",
                }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6, fontSize: 11, color: hintColor }}>
                <span>{formatDuration(livePosition)}</span>
                <span>{currentTrack.duration_fmt}</span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <button onClick={handleSkip} style={{
                flex: 1, padding: "9px 0", borderRadius: 12, border: cardBorder,
                background: "rgba(255,255,255,0.03)", color: hintColor, fontSize: 12, cursor: "pointer", fontWeight: 700,
                position: "relative", overflow: "hidden",
              }}>
                {!canControl && currentTrack.skip_votes > 0 && (
                  <div style={{
                    position: "absolute", left: 0, top: 0, bottom: 0,
                    width: `${Math.min(100, (currentTrack.skip_votes / party.skip_threshold) * 100)}%`,
                    background: warm ? "rgba(255,109,0,0.15)" : "rgba(124,77,255,0.15)",
                    transition: "width 0.3s ease",
                  }} />
                )}
                <span style={{ position: "relative", zIndex: 1 }}>
                  {canControl ? "⏭ Пропустить" : `⏭ Skip ${currentTrack.skip_votes}/${party.skip_threshold}`}
                </span>
              </button>
              {canControl && (
                <>
                  <button onClick={() => handleSyncPlayback("play", currentTrack.position, 0, currentTrack)} style={{ padding: "9px 12px", borderRadius: 12, border: cardBorder, background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>▶ Всем</button>
                  <button onClick={() => handleSyncPlayback("pause", currentTrack.position, 0)} style={{ padding: "9px 12px", borderRadius: 12, border: cardBorder, background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>⏸ Пауза</button>
                </>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
              {(["🔥", "❤️", "⚡", "🪩"] as const).map((emoji) => (
                <button key={emoji} onClick={() => handleReaction(emoji)} style={{ padding: "7px 10px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                  {emoji} {party.current_reactions?.[emoji] || 0}
                </button>
              ))}
            </div>
            {recentReactionEvents.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", gap: 8, overflowX: "auto", paddingBottom: 2 }}>
                {recentReactionEvents.map((event) => (
                  <div key={event.id} style={{ whiteSpace: "nowrap", padding: "7px 10px", borderRadius: 999, background: "rgba(255,255,255,0.05)", color: hintColor, fontSize: 11, fontWeight: 700 }}>
                    {String(event.payload?.emoji || "🔥")} {event.actor_name || "Guest"}
                  </div>
                ))}
              </div>
            )}
            {party.members.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {party.members.slice(0, 5).map((member, index) => (
                  <div key={`pulse-${member.user_id}`} style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 9px",
                    borderRadius: 999,
                    background: "rgba(255,255,255,0.04)",
                    color: textColor,
                    fontSize: 11,
                    fontWeight: 700,
                  }}>
                    <span style={{
                      width: 8,
                      height: 8,
                      borderRadius: 999,
                      background: member.is_online ? (warm ? "#ffd54f" : accentColor) : "rgba(255,255,255,0.24)",
                      boxShadow: member.is_online ? (warm ? "0 0 12px rgba(255,213,79,0.42)" : `0 0 12px ${accentColor}66`) : "none",
                      animation: member.is_online && party.playback.action === "play" ? `partyCrowdPulse 1.4s ${index * 0.1}s ease-in-out infinite` : "none",
                    }} />
                    {member.display_name || `User ${member.user_id}`}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {(lyricsLoading || lyrics.length > 0) && currentTrack && (
          <div style={{ ...glassCard, padding: 12, borderRadius: 18, marginBottom: 12 }}>
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Lyrics wall</span>
              <span style={{ fontSize: 10, color: hintColor }}>{lyricsLoading ? "loading" : `${lyrics.length} lines`}</span>
            </div>
            {lyricsLoading ? (
              <div style={{ textAlign: "center", padding: 16 }}><IconSpinner size={18} color={hintColor} /></div>
            ) : lyrics.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto", paddingRight: 4 }}>
                {lyrics.map((line, index) => (
                  <div key={`${index}-${line}`} style={{
                    padding: "8px 10px",
                    borderRadius: 12,
                    background: index === activeLyricIndex ? (warm ? "rgba(255,193,7,0.12)" : `${accentColor}22`) : "rgba(255,255,255,0.03)",
                    color: index === activeLyricIndex ? textColor : hintColor,
                    fontSize: index === activeLyricIndex ? 13 : 12,
                    fontWeight: index === activeLyricIndex ? 700 : 500,
                    transform: index === activeLyricIndex ? "scale(1.01)" : "scale(1)",
                    transition: "all 180ms ease",
                  }}>
                    {line}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: hintColor, fontSize: 12, padding: "8px 2px" }}>Для этого трека текст пока не найден.</div>
            )}
          </div>
        )}

        <div style={{ ...glassCard, padding: 12, borderRadius: 18, marginBottom: 12 }}>
          <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>Live chat</span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 10, color: hintColor }}>{chatMessages.length} msgs</span>
              {canControl && !readOnlyMode && chatMessages.length > 0 && (
                <button onClick={handleClearChat} style={{ padding: "5px 8px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>Clear</button>
              )}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 180, overflowY: "auto", marginBottom: 10 }}>
            {chatMessages.length > 0 ? chatMessages.map((message) => (
              <div key={message.id} style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.03)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <div style={{ fontSize: 11, color: textColor, fontWeight: 700 }}>{message.display_name || "Guest"}</div>
                  {!readOnlyMode && (canControl || message.user_id === userId) && (
                    <button onClick={() => handleDeleteChatMessage(message.id)} style={{ padding: "4px 7px", borderRadius: 999, border: "none", background: "rgba(239,83,80,0.16)", color: "#ff8a80", fontSize: 10, fontWeight: 700, cursor: "pointer" }}>×</button>
                  )}
                </div>
                <div style={{ fontSize: 12, color: hintColor, marginTop: 2 }}>{message.message}</div>
              </div>
            )) : <div style={{ color: hintColor, fontSize: 12 }}>{readOnlyMode ? "Read-only screen. Сообщения только для просмотра." : "Чат пока тихий. Напиши первым."}</div>}
          </div>
          {!readOnlyMode && <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              placeholder="Написать в чат..."
              value={chatMessage}
              onInput={(e: any) => setChatMessage(e.target.value)}
              onKeyDown={(e: any) => { if (e.key === "Enter") handleSendChat(); }}
              style={{ flex: 1, padding: "10px 12px", borderRadius: 12, border: cardBorder, background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 13, outline: "none" }}
            />
            <button onClick={handleSendChat} style={{ padding: "10px 12px", borderRadius: 12, border: "none", background: activeBg, color: "#fff", fontSize: 12, fontWeight: 800, cursor: "pointer" }}>Send</button>
          </div>}
        </div>

        {!readOnlyMode && <button onClick={() => { haptic("light"); setShowSearch(true); }} style={{
          width: "100%", padding: "14px 0", borderRadius: 16, border: cardBorder,
          background: softBg, color: textColor, fontSize: 14, fontWeight: 700,
          cursor: "pointer", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
          backdropFilter: "blur(14px) saturate(130%)",
          WebkitBackdropFilter: "blur(14px) saturate(130%)",
          boxShadow: panelShadow,
        }}>
          <IconPlus size={16} color={warm ? "#ffd54f" : accentColor} /> Добавить трек
        </button>}

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
              }}><IconClose size={16} /></button>
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
                {canControl && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 8 }}>
                    <button onClick={(e: any) => { e.stopPropagation(); handlePlayNext(t.video_id); }} style={{ padding: "5px 8px", borderRadius: 8, border: cardBorder, background: "transparent", color: warm ? "#ffd54f" : accentColor, fontSize: 11, cursor: "pointer" }}>⏭</button>
                    {idx > 0 && (
                      <button onClick={(e: any) => { e.stopPropagation(); handleMoveTrack(t.position, upNext[idx - 1].position); }} style={{ padding: "5px 8px", borderRadius: 8, border: cardBorder, background: "transparent", color: textColor, fontSize: 11, cursor: "pointer" }}>↑</button>
                    )}
                    {idx < upNext.length - 1 && (
                      <button onClick={(e: any) => { e.stopPropagation(); handleMoveTrack(t.position, upNext[idx + 1].position); }} style={{ padding: "5px 8px", borderRadius: 8, border: cardBorder, background: "transparent", color: textColor, fontSize: 11, cursor: "pointer" }}>↓</button>
                    )}
                    <button onClick={(e: any) => { e.stopPropagation(); handleRemoveTrack(t.video_id); }} style={{
                      width: 28, height: 28, borderRadius: 8, border: "none",
                      background: "transparent", color: "#ef5350", fontSize: 14, cursor: "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}><IconClose size={14} /></button>
                  </div>
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
            <div style={{ display: "flex", justifyContent: "center", marginBottom: 10 }}><IconMusic size={32} /></div>
            <div style={{ color: textColor, fontWeight: 700, marginBottom: 4 }}>Очередь пока пустая</div>
            Очередь пуста — добавь первый трек!
          </div>
        )}

        {party.events.length > 0 && (
          <div style={{ ...glassCard, padding: 12, borderRadius: 18, marginTop: 12 }}>
            <div style={sectionLabel}>Live feed</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {party.events.slice(-6).reverse().map((event) => (
                <div key={event.id} style={{ padding: "9px 10px", borderRadius: 12, background: "rgba(255,255,255,0.03)" }}>
                  <div style={{ fontSize: 12, color: textColor, fontWeight: 600 }}>{event.message}</div>
                  <div style={{ fontSize: 10, color: hintColor, marginTop: 3 }}>{event.event_type}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {recap && (
          <div style={{ ...glassCard, padding: 12, borderRadius: 18, marginTop: 12 }}>
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Party recap</span>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <button onClick={handleDownloadRecapPoster} style={{ padding: "6px 10px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 11, fontWeight: 700, cursor: "pointer" , display: "flex", alignItems: "center", gap: 4 }}><IconPicture size={12} /> Poster</button>
                <button onClick={handleShareRecap} style={{ padding: "6px 10px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 11, fontWeight: 700, cursor: "pointer" , display: "flex", alignItems: "center", gap: 4 }}><IconUpload size={12} /> Share recap</button>
              </div>
            </div>
            <div style={{
              position: "relative",
              overflow: "hidden",
              marginBottom: 10,
              padding: "16px 14px",
              borderRadius: 18,
              background: warm ? "linear-gradient(135deg, rgba(255,171,64,0.22), rgba(255,109,0,0.10), rgba(255,224,178,0.10))" : `linear-gradient(135deg, ${accentColor}33, rgba(123,97,255,0.10), rgba(255,255,255,0.06))`,
              border: warm ? "1px solid rgba(255,193,7,0.16)" : `1px solid ${accentColor}22`,
              boxShadow: warm ? "0 16px 34px rgba(255,145,0,0.14)" : `0 16px 34px ${accentColor}20`,
            }}>
              <div style={{ position: "absolute", width: 120, height: 120, right: -26, top: -40, borderRadius: "50%", background: "rgba(255,255,255,0.08)", filter: "blur(12px)" }} />
              <div style={{ position: "relative", zIndex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 1.4, textTransform: "uppercase", color: hintColor, marginBottom: 6 }}>Poster card</div>
                    <div style={{ color: textColor, fontSize: 18, fontWeight: 800, lineHeight: 1.1 }}>Party recap · {party.name}</div>
                  </div>
                  <div style={{ padding: "7px 10px", borderRadius: 12, background: "rgba(0,0,0,0.18)", color: "#fff", fontSize: 11, fontWeight: 800 }}>#{party.invite_code}</div>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                  <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.08)", color: textColor, fontSize: 12, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconMusic size={14} /> {recap.total_tracks} tracks</div>
                  <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.08)", color: textColor, fontSize: 12, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconUsers size={14} /> {recap.total_members} members</div>
                  <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.08)", color: textColor, fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", gap: 4 }}><IconClock size={14} /> {formatDuration(recap.total_duration)}</div>
                </div>
                <div style={{ color: hintColor, fontSize: 12, lineHeight: 1.5 }}>
                  {recap.top_artists[0] ? <>Главный вайб вечера — <span style={{ color: textColor, fontWeight: 700 }}>{recap.top_artists[0].label}</span>.</> : "Вечеринка собрала свой особый вайб."} {recap.top_contributors[0] ? <>Главный куратор — <span style={{ color: textColor, fontWeight: 700 }}>{recap.top_contributors[0].label}</span>.</> : null}
                </div>
              </div>
            </div>
            <div style={{ marginBottom: 10, padding: "12px 12px", borderRadius: 16, background: warm ? "linear-gradient(135deg, rgba(255,193,7,0.12), rgba(255,109,0,0.08))" : `linear-gradient(135deg, ${accentColor}22, rgba(255,255,255,0.04))`, border: warm ? "1px solid rgba(255,193,7,0.14)" : `1px solid ${accentColor}22` }}>
              <div style={{ color: textColor, fontSize: 16, fontWeight: 800, marginBottom: 4 }}>Ночь получилась громкой</div>
              <div style={{ color: hintColor, fontSize: 12, lineHeight: 1.45 }}>В комнате было {recap.total_members} участников, прозвучало {recap.total_tracks} треков и музыка играла {formatDuration(recap.total_duration)}.</div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {recap.top_artists[0] && (
                <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 11, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconTrophy size={12} /> {recap.top_artists[0].label}</div>
              )}
              {recap.top_contributors[0] && (
                <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 11, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconTrophy size={12} /> {recap.top_contributors[0].label}</div>
              )}
              <div style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(255,255,255,0.04)", color: textColor, fontSize: 11, fontWeight: 700 , display: "flex", alignItems: "center", gap: 4 }}><IconFire size={12} /> {recap.events_count} событий</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginBottom: 10 }}>
              <div style={{ padding: "10px 12px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}><div style={{ fontSize: 10, color: hintColor }}>Tracks</div><div style={{ color: textColor, fontSize: 18, fontWeight: 800 }}>{recap.total_tracks}</div></div>
              <div style={{ padding: "10px 12px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}><div style={{ fontSize: 10, color: hintColor }}>Members</div><div style={{ color: textColor, fontSize: 18, fontWeight: 800 }}>{recap.total_members}</div></div>
              <div style={{ padding: "10px 12px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}><div style={{ fontSize: 10, color: hintColor }}>Skips</div><div style={{ color: textColor, fontSize: 18, fontWeight: 800 }}>{recap.total_skip_votes}</div></div>
              <div style={{ padding: "10px 12px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}><div style={{ fontSize: 10, color: hintColor }}>Duration</div><div style={{ color: textColor, fontSize: 18, fontWeight: 800 }}>{formatDuration(recap.total_duration)}</div></div>
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 150 }}>
                <div style={{ fontSize: 11, color: hintColor, marginBottom: 6 }}>Top contributors</div>
                {recap.top_contributors.map((item) => <div key={item.label} style={{ fontSize: 12, color: textColor, marginBottom: 4 }}>{item.label} · {item.value}</div>)}
              </div>
              <div style={{ flex: 1, minWidth: 150 }}>
                <div style={{ fontSize: 11, color: hintColor, marginBottom: 6 }}>Top artists</div>
                {recap.top_artists.map((item) => <div key={item.label} style={{ fontSize: 12, color: textColor, marginBottom: 4 }}>{item.label} · {item.value}</div>)}
              </div>
            </div>
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.06)", fontSize: 11, color: hintColor }}>
              Events logged: {recap.events_count} · Online peak right now: {recap.online_members}
            </div>
          </div>
        )}

        {showStageMode && currentTrack && (
          <div style={{
            position: "fixed",
            inset: 0,
            zIndex: 99998,
            background: warm ? "linear-gradient(180deg, rgba(36,20,8,0.96), rgba(13,8,4,0.98))" : "linear-gradient(180deg, rgba(10,12,25,0.96), rgba(4,6,14,0.98))",
            backdropFilter: "blur(18px) saturate(145%)",
            WebkitBackdropFilter: "blur(18px) saturate(145%)",
            overflow: "auto",
          }}>
            {transitionFx && (
              <div style={{
                position: "absolute",
                inset: 0,
                background: warm ? "radial-gradient(circle at center, rgba(255,193,7,0.26), rgba(255,109,0,0.12), transparent 68%)" : `radial-gradient(circle at center, ${accentColor}55, rgba(124,77,255,0.12), transparent 68%)`,
                animation: "partyTransitionFlash 0.85s ease-out forwards",
                pointerEvents: "none",
                zIndex: 2,
              }} />
            )}
            {[0, 1, 2, 3, 4, 5].map((particle) => (
              <div key={`particle-${particle}`} style={{
                position: "absolute",
                width: 120 + (particle % 3) * 30,
                height: 120 + (particle % 3) * 30,
                borderRadius: "50%",
                left: `${8 + particle * 14}%`,
                top: `${10 + (particle % 3) * 22}%`,
                background: warm ? "rgba(255,193,7,0.08)" : `${accentColor}22`,
                filter: "blur(18px)",
                animation: `partyParticleFloat ${4.5 + particle * 0.4}s ease-in-out infinite`,
              }} />
            ))}
            <div style={{
              position: "absolute",
              inset: 0,
              backgroundImage: currentTrack.cover_url ? `url(${currentTrack.cover_url})` : "none",
              backgroundSize: "cover",
              backgroundPosition: "center",
              opacity: 0.14,
              filter: "blur(28px)",
              transform: "scale(1.12)",
            }} />
            <div style={{ position: "relative", zIndex: 1, minHeight: "100vh", padding: "18px 16px 28px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                <div style={{ color: hintColor, fontSize: 11, fontWeight: 800, letterSpacing: 1.5, textTransform: "uppercase" }}>Party Stage</div>
                <button onClick={() => setShowStageMode(false)} style={{ padding: "9px 12px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.06)", color: textColor, fontSize: 12, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}><IconClose size={14} /> Close</button>
              </div>

              <div>
                <div style={{ position: "relative", width: "min(72vw, 320px)", margin: "0 auto" }}>
                  <div style={{ width: "100%", aspectRatio: "1 / 1", borderRadius: 28, overflow: "hidden", boxShadow: warm ? "0 24px 70px rgba(255,145,0,0.24)" : `0 24px 70px ${accentColor}33`, background: "rgba(255,255,255,0.06)" }}>
                    {currentTrack.cover_url ? <img src={currentTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusic size={46} color={textColor} /></div>}
                  </div>
                  {orbitMembers.map((member, index) => {
                    const positions = [
                      { top: -12, left: "50%", marginLeft: -21 },
                      { top: 28, right: -10 },
                      { bottom: 34, right: -14 },
                      { bottom: -12, left: "50%", marginLeft: -21 },
                      { bottom: 34, left: -14 },
                      { top: 28, left: -10 },
                    ] as const;
                    const position = positions[index] || positions[0];
                    return (
                      <div key={`orbit-${member.user_id}`} style={{
                        position: "absolute",
                        width: 42,
                        height: 42,
                        borderRadius: 999,
                        background: member.is_online ? activeBg : "rgba(255,255,255,0.1)",
                        color: "#fff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 13,
                        fontWeight: 800,
                        boxShadow: "0 12px 24px rgba(0,0,0,0.2)",
                        animation: `partyOrbitPulse 2.2s ${index * 0.18}s ease-in-out infinite`,
                        ...position,
                      }}>
                        {(member.display_name || "U").slice(0, 1).toUpperCase()}
                      </div>
                    );
                  })}
                </div>

                <div style={{ textAlign: "center", marginTop: 18 }}>
                  <div style={{ color: textColor, fontSize: 28, fontWeight: 800, lineHeight: 1.1 }}>{currentTrack.title}</div>
                  <div style={{ color: hintColor, fontSize: 14, marginTop: 8 }}>{currentTrack.artist} · {party.name}</div>
                </div>

                <div style={{ display: "flex", justifyContent: "center", alignItems: "flex-end", gap: 6, height: 40, marginTop: 18 }}>
                  {[0, 1, 2, 3, 4, 5, 6, 7].map((bar) => (
                    <span key={bar} style={{
                      width: 8,
                      height: party.playback.action === "play" ? 18 + ((bar % 4) * 5) : 16,
                      borderRadius: 999,
                      background: warm ? "linear-gradient(180deg, #ffe082, #ff8f00)" : activeBg,
                      animation: party.playback.action === "play" ? `partyEqualizer 0.95s ${bar * 0.08}s ease-in-out infinite` : "none",
                      transformOrigin: "bottom center",
                      boxShadow: warm ? "0 0 14px rgba(255,193,7,0.2)" : `0 0 14px ${accentColor}44`,
                    }} />
                  ))}
                </div>

                <div style={{ marginTop: 18 }}>
                  <div style={{ height: 8, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div style={{ width: `${progressPercent}%`, height: "100%", borderRadius: 999, background: activeBg, transition: "width 0.9s linear" }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, color: hintColor, fontSize: 12 }}>
                    <span>{formatDuration(livePosition)}</span>
                    <span>{currentTrack.duration_fmt}</span>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap", marginTop: 18 }}>
                  {(["🔥", "❤️", "⚡", "🪩"] as const).map((emoji) => (
                    <button key={`stage-${emoji}`} onClick={() => handleReaction(emoji)} style={{ padding: "10px 14px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.07)", color: textColor, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>{emoji} {party.current_reactions?.[emoji] || 0}</button>
                  ))}
                </div>

                {lyrics.length > 0 && (
                  <div style={{ marginTop: 20, padding: "14px 14px", borderRadius: 18, background: "rgba(255,255,255,0.05)", border: cardBorder, maxHeight: 220, overflowY: "auto" }}>
                    <div style={{ fontSize: 10, color: hintColor, fontWeight: 800, letterSpacing: 1.4, textTransform: "uppercase", marginBottom: 10 }}>Synced lyrics</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {lyrics.map((line, index) => (
                        <div key={`stage-lyric-${index}`} style={{ color: index === activeLyricIndex ? textColor : hintColor, fontSize: index === activeLyricIndex ? 15 : 13, fontWeight: index === activeLyricIndex ? 700 : 500, transition: "all 160ms ease" }}>{line}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div style={{ marginTop: 22, display: "flex", gap: 10 }}>
                <button onClick={() => { haptic("light"); onPlayTrack(currentTrack); }} style={{ flex: 1, padding: "14px 0", borderRadius: 18, border: "none", background: activeBg, color: "#fff", fontSize: 14, fontWeight: 800, cursor: "pointer" }}>▶ Play local</button>
                {canControl && (
                  <button onClick={() => handleSyncPlayback(party.playback.action === "pause" ? "play" : "pause", currentTrack.position, livePosition, currentTrack)} style={{ padding: "14px 16px", borderRadius: 18, border: cardBorder, background: "rgba(255,255,255,0.07)", color: textColor, fontSize: 14, fontWeight: 800, cursor: "pointer" }}>{party.playback.action === "pause" ? "▶ Room" : "⏸ Room"}</button>
                )}
              </div>
            </div>
          </div>
        )}

        {showTvMode && currentTrack && (
          <div style={{
            position: "fixed",
            inset: 0,
            zIndex: 99997,
            background: warm ? "linear-gradient(180deg, rgba(25,14,6,0.98), rgba(10,7,3,1))" : "linear-gradient(180deg, rgba(5,7,14,0.99), rgba(2,3,8,1))",
            overflow: "auto",
          }}>
            <div style={{ minHeight: "100vh", padding: "24px 22px 36px", display: "flex", flexDirection: "column", gap: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ color: hintColor, fontSize: 11, fontWeight: 800, letterSpacing: 1.6, textTransform: "uppercase" }}>Party TV</div>
                  <div style={{ color: textColor, fontSize: 24, fontWeight: 800 }}>{party.name}</div>
                </div>
                <button onClick={() => setShowTvMode(false)} style={{ padding: "10px 14px", borderRadius: 999, border: cardBorder, background: "rgba(255,255,255,0.06)", color: textColor, fontSize: 12, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}><IconClose size={14} /> Close</button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(320px, 0.8fr)", gap: 24 }}>
                <div style={{ ...glassCard, borderRadius: 28, padding: 20 }}>
                  <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
                    <div style={{ width: 220, height: 220, borderRadius: 26, overflow: "hidden", background: "rgba(255,255,255,0.06)", flexShrink: 0 }}>
                      {currentTrack.cover_url ? <img src={currentTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusic size={48} color={textColor} /></div>}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ color: textColor, fontSize: 34, fontWeight: 800, lineHeight: 1.08 }}>{currentTrack.title}</div>
                      <div style={{ color: hintColor, fontSize: 18, marginTop: 8 }}>{currentTrack.artist}</div>
                      <div style={{ marginTop: 16, height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}><div style={{ width: `${progressPercent}%`, height: "100%", background: activeBg }} /></div>
                      <div style={{ display: "flex", justifyContent: "space-between", color: hintColor, fontSize: 13, marginTop: 8 }}><span>{formatDuration(livePosition)}</span><span>{currentTrack.duration_fmt}</span></div>
                    </div>
                  </div>
                </div>
                <div style={{ ...glassCard, borderRadius: 28, padding: 20 }}>
                  <div style={{ ...sectionLabel, marginBottom: 12 }}>Queue</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {upNext.slice(0, 6).map((track, index) => (
                      <div key={`tv-${track.video_id}`} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "10px 12px", borderRadius: 14, background: "rgba(255,255,255,0.03)" }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ color: textColor, fontSize: 14, fontWeight: 700 }}>{index + 1}. {track.title}</div>
                          <div style={{ color: hintColor, fontSize: 12 }}>{track.artist}</div>
                        </div>
                        <div style={{ color: hintColor, fontSize: 12 }}>{track.duration_fmt}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        <style>{`@keyframes partyReactionFloat { 0% { transform: translate3d(0, 0, 0) scale(0.82); opacity: 0; } 15% { opacity: 1; } 100% { transform: translate3d(0, -88px, 0) scale(1.16); opacity: 0; } } @keyframes partyEqualizer { 0%, 100% { transform: scaleY(0.45); opacity: 0.65; } 50% { transform: scaleY(1.1); opacity: 1; } } @keyframes partyOrbitPulse { 0%, 100% { transform: scale(0.96); opacity: 0.82; } 50% { transform: scale(1.06); opacity: 1; } } @keyframes partyParticleFloat { 0%, 100% { transform: translate3d(0, 0, 0) scale(1); opacity: 0.4; } 50% { transform: translate3d(0, -18px, 0) scale(1.08); opacity: 0.75; } } @keyframes partyTransitionFlash { 0% { opacity: 0; } 20% { opacity: 1; } 100% { opacity: 0; } } @keyframes partyCrowdPulse { 0%, 100% { transform: scale(0.9); opacity: 0.72; } 50% { transform: scale(1.18); opacity: 1; } }`}</style>
      </div>
    );
  }

  return (
    <div style={{ background: shellBg, borderRadius: 26, padding: 2 }}>
      {Toast}

      {initialCode && !showCreate && (
        <div style={{
          ...glassCard,
          borderRadius: 22,
          padding: "16px 14px",
          marginBottom: 12,
          position: "relative",
          overflow: "hidden",
          background: warm ? "linear-gradient(135deg, rgba(255,171,64,0.16), rgba(56,34,18,0.84))" : `linear-gradient(135deg, ${accentColor}22, rgba(15,18,35,0.82))`,
        }}>
          <div style={{ position: "absolute", right: -20, top: -18, width: 110, height: 110, borderRadius: "50%", background: "rgba(255,255,255,0.08)", filter: "blur(10px)" }} />
          <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 1.4, textTransform: "uppercase", color: hintColor, marginBottom: 6 }}>Invite landing</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: textColor, lineHeight: 1.1, marginBottom: 6 }}>Тебя позвали в Party room</div>
              <div style={{ fontSize: 12, color: hintColor, lineHeight: 1.45 }}>Код комнаты: <span style={{ color: textColor, fontWeight: 700 }}>#{initialCode}</span>. Зайди и подключись к общему вайбу.</div>
            </div>
            <button onClick={() => handleJoinParty(initialCode)} style={{ padding: "11px 14px", borderRadius: 14, border: "none", background: partyGradient, color: "#000", fontSize: 12, fontWeight: 800, cursor: "pointer", flexShrink: 0 }}>Join</button>
          </div>
        </div>
      )}

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
          <button onClick={handleCreate} style={{ padding: "10px 16px", borderRadius: 12, border: "none", background: partyGradient, color: "#000", fontSize: 13, fontWeight: 800, cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}><IconParty size={14} /> Go</button>
          <button onClick={() => { setShowCreate(false); setNewName(""); }} style={{ padding: "10px 12px", borderRadius: 12, border: cardBorder, background: "transparent", color: hintColor, fontSize: 13, cursor: "pointer" }}><IconClose size={14} /></button>
        </div>
      )}

      {myParties.length === 0 && !showCreate ? (
        <div style={{ ...glassCard, textAlign: "center", padding: 32, borderRadius: 20 }}>
          <div style={{ width: 68, height: 68, borderRadius: 20, margin: "0 auto 14px", background: partyGradient, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 14px 28px rgba(255,145,0,0.18)" }}><IconParty size={32} color="#000" /></div>
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
              boxShadow: "0 10px 22px rgba(255,145,0,0.18)",
            }}><IconParty size={20} color="#000" /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: textColor }}>{p.name}</div>
              <div style={{ fontSize: 12, color: hintColor, display: "flex", alignItems: "center", gap: 4 }}>
                {p.track_count ?? p.tracks.length} треков · <IconUsers size={12} /> {p.member_count} online
              </div>
            </div>
            <div style={{ fontSize: 12, color: hintColor }}>
              <code style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", padding: "2px 6px", borderRadius: 6 }}>{p.invite_code}</code>
            </div>
          </div>
        ))
      )}

      <div style={{ marginTop: 12, padding: 14, borderRadius: 16, ...softCard }}>
        <div style={{ ...sectionLabel, marginBottom: 10, fontSize: 10 }}>Присоединиться по коду</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" placeholder="Вставь код пати" maxLength={16} value={joinCode}
            onInput={(e: any) => setJoinCode(e.target.value.trim())}
            onKeyDown={(e: any) => { if (e.key === "Enter" && joinCode) handleJoinParty(joinCode); }}
            style={{ flex: 1, padding: "10px 12px", borderRadius: 12, border: warm ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)", background: "rgba(255,255,255,0.03)", color: textColor, fontSize: 14, outline: "none", fontFamily: "monospace" }} />
          <button onClick={() => { if (joinCode) handleJoinParty(joinCode); }} disabled={!joinCode} style={{
            padding: "10px 16px", borderRadius: 12, border: "none",
            background: joinCode ? partyGradient : "rgba(255,255,255,0.06)",
            color: joinCode ? "#000" : hintColor,
            fontSize: 13, fontWeight: 800, cursor: joinCode ? "pointer" : "default",
            opacity: joinCode ? 1 : 0.5,
          }}>Join</button>
        </div>
      </div>
    </div>
  );
}
