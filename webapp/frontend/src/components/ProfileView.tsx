import { useState, useEffect, useRef } from "preact/hooks";
import { Component } from "preact";
import type { Track } from "../api";
import { fetchFavoritesList, fetchChallenges, type ChallengesData } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconCrown, IconFire, IconMusicNote, IconChart, IconPlaySmall,
  IconDiamond, IconSpinner, IconHeadphones, IconMusic, IconHeart,
  IconMoon, IconParty, IconRocket, IconDiscover, IconEdit,
} from "./Icons";

// ── ErrorBoundary for ProfileView ──────────────────────────────────────

class ProfileErrorBoundary extends Component<{ fallbackColor?: string }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(err: Error) { return { error: err.message || "render error" }; }
  componentDidCatch(err: Error) { console.error("[ProfileView] render crash:", err); }
  render() {
    if (this.state.error) {
      return (
        <div style={{ textAlign: "center", padding: 64, color: this.props.fallbackColor || "#aaa", fontSize: 14 }}>
          Не удалось отобразить профиль
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Types ───────────────────────────────────────────────────────────────

interface StreakMilestone {
  days: number;
  xp: number;
  remaining: number;
}

interface UserStats {
  total_plays: number;
  total_time: number; // seconds
  total_favorites: number;
  top_artists: Array<{ name: string; count: number }>;
  top_genres: Array<{ name: string; count: number }>;
  recent_tracks: Track[];
  xp: number;
  level: number;
  streak_days: number;
  badges: string[];
  member_since: string | null;
  next_streak_milestone?: StreakMilestone | null;
}

interface Props {
  userId: number;
  username?: string;
  firstName?: string;
  isPremium?: boolean;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

// ── Badge definitions ───────────────────────────────────────────────────

const BADGE_DEFS: Record<string, { label: string; desc: string }> = {
  meloman: { label: "Меломан", desc: "100+ треков" },
  night_owl: { label: "Ночной слушатель", desc: "Слушал после 2 ночи" },
  party_starter: { label: "Тусовщик", desc: "Создал 5+ пати" },
  streak_7: { label: "7 дней подряд", desc: "Неделя без пропуска" },
  streak_30: { label: "30 дней подряд", desc: "Месяц подряд!" },
  explorer: { label: "Исследователь", desc: "10+ жанров" },
  dj: { label: "DJ", desc: "50+ треков в очередь" },
  first_listen: { label: "Первый трек", desc: "Начало пути" },
};

const BADGE_ICONS: Record<string, (props: { size: number; color: string }) => any> = {
  first_listen: IconMusicNote,
  meloman: IconHeadphones,
  streak_7: IconFire,
  streak_30: IconFire,
  explorer: IconDiscover,
  dj: IconMusic,
  night_owl: IconMoon,
  party_starter: IconParty,
};

// ── Helpers ──────────────────────────────────────────────────────────────

function formatTime(seconds: number): string {
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    const h = hours % 24;
    return `${days}д ${h}ч`;
  }
  return `${hours}ч ${mins}м`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}м назад`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}ч назад`;
  const days = Math.floor(hours / 24);
  return `${days}д назад`;
}

function formatMemberSince(dateStr: string): string {
  const d = new Date(dateStr);
  const months = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
  ];
  return `с ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

// ── Premium border keyframes (injected once) ────────────────────────────

let premiumStyleInjected = false;
function ensurePremiumStyle() {
  if (premiumStyleInjected) return;
  premiumStyleInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    @keyframes profile-premium-border {
      0% { background-position: 0% 50%; }
      50% { background-position: 100% 50%; }
      100% { background-position: 0% 50%; }
    }
  `;
  document.head.appendChild(style);
}

// ── Component ───────────────────────────────────────────────────────────

export function ProfileView({
  userId,
  username,
  firstName,
  isPremium,
  onPlayTrack,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [favorites, setFavorites] = useState<Track[]>([]);
  const [showAllFavs, setShowAllFavs] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [challenges, setChallenges] = useState<ChallengesData | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load avatar from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`avatar_${userId}`);
      if (saved) setAvatarUrl(saved);
    } catch {}
  }, [userId]);

  // Inject premium animation style
  useEffect(() => {
    if (isPremium) ensurePremiumStyle();
  }, [isPremium]);

  useEffect(() => {
    // Guard: don't fetch if userId is 0 (WebApp not ready)
    if (!userId) {
      setLoading(false);
      setError(true);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(false);

    // Aggressive timeout: if ANYTHING takes >6s, just show what we have
    const hardTimeout = setTimeout(() => {
      if (!cancelled) {
        setLoading(false);
        if (!stats) setError(true);
      }
    }, 6000);

    // Fetch stats with its own timeout
    const ctrl = new AbortController();
    const fetchTimer = setTimeout(() => ctrl.abort(), 5000);

    fetch(`/api/stats/${userId}`, {
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": window.Telegram?.WebApp?.initData || "",
      },
      signal: ctrl.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: UserStats) => {
        if (!cancelled) setStats(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        clearTimeout(fetchTimer);
        if (!cancelled) setLoading(false);
      });

    // These are non-blocking — if they fail, profile still shows
    fetchFavoritesList().then((f) => { if (!cancelled) setFavorites(f); }).catch(() => {});
    fetchChallenges(userId).then((c) => { if (!cancelled) setChallenges(c); }).catch(() => {});

    return () => {
      cancelled = true;
      ctrl.abort();
      clearTimeout(fetchTimer);
      clearTimeout(hardTimeout);
    };
  }, [userId]);

  // ── Avatar upload handler ────────────────────────────────────────────

  const handleAvatarFile = (e: Event) => {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        // Center-crop and resize
        const srcSize = Math.min(img.width, img.height);
        const sx = (img.width - srcSize) / 2;
        const sy = (img.height - srcSize) / 2;
        ctx.drawImage(img, sx, sy, srcSize, srcSize, 0, 0, 256, 256);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        try { localStorage.setItem(`avatar_${userId}`, dataUrl); } catch {}
        setAvatarUrl(dataUrl);
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
    // Reset input so same file can be re-selected
    input.value = "";
  };

  // Retry handler
  const retry = () => {
    setError(false);
    setLoading(true);
    setStats(null);
    // Force re-run useEffect by toggling a dummy state
    setRetryCount((c) => c + 1);
  };

  // ── Loading / error states ──────────────────────────────────────────

  // Retry function
  const retryLoad = () => {
    setStats(null);
    setError(false);
    setLoading(true);
    // Re-trigger the effect by forcing a state cycle
    const ctrl = new AbortController();
    const fetchTimer = setTimeout(() => ctrl.abort(), 5000);
    fetch(`/api/stats/${userId}`, {
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": window.Telegram?.WebApp?.initData || "",
      },
      signal: ctrl.signal,
    })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data: UserStats) => setStats(data))
      .catch(() => setError(true))
      .finally(() => { clearTimeout(fetchTimer); setLoading(false); });
    fetchFavoritesList().then(setFavorites).catch(() => {});
    fetchChallenges(userId).then(setChallenges).catch(() => {});
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IconSpinner size={28} color={tc.hintColor} />
        <div style={{ fontSize: 12, color: tc.hintColor, marginTop: 12 }}>
          Загрузка профиля...
        </div>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div style={{ textAlign: "center", padding: 48 }}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>😕</div>
        <div style={{ fontSize: 14, color: tc.hintColor, marginBottom: 16 }}>
          Не удалось загрузить профиль
        </div>
        <button
          onClick={() => { haptic("light"); retryLoad(); }}
          style={{
            padding: "10px 28px", borderRadius: 12, border: tc.cardBorder,
            background: tc.cardBg, color: tc.highlight,
            fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}
        >
          Повторить
        </button>
      </div>
    );
  }

  // Defensive: normalize arrays that might be null from API
  const topArtists = stats.top_artists || [];
  const topGenres = stats.top_genres || [];
  const badges = stats.badges || [];
  const recentTracks = stats.recent_tracks || [];

  const maxArtistCount = topArtists.length > 0
    ? Math.max(...topArtists.map((a) => a.count))
    : 1;

  const xpForNext = (stats.level || 1) * 100;
  const xpProgress = xpForNext > 0 ? Math.min((stats.xp || 0) / xpForNext, 1) : 0;

  const displayName = firstName || username || "User";
  const avatarLetter = displayName.charAt(0).toUpperCase();

  const avatarGlow = tc.isTequila
    ? "0 0 30px rgba(255,167,38,0.4), 0 0 60px rgba(255,109,0,0.2)"
    : tc.glowShadow;

  // Premium animated gradient border wrapper style
  const premiumBorderStyle: Record<string, any> | undefined = isPremium
    ? {
        background: tc.isTequila
          ? "linear-gradient(135deg, #ff8f00, #ffd54f, #ff6d00, #ffab40)"
          : `linear-gradient(135deg, ${accentColor}, #b388ff, #e040fb, ${accentColor})`,
        backgroundSize: "300% 300%",
        animation: "profile-premium-border 4s ease infinite",
        borderRadius: 19,
        padding: 1.5,
      }
    : undefined;

  // ── Render ──────────────────────────────────────────────────────────

  const headerCard = (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      padding: "24px 16px 20px", marginBottom: isPremium ? 0 : 16,
      borderRadius: 18, background: tc.cardBg, border: isPremium ? "none" : tc.cardBorder,
      backdropFilter: "blur(16px)",
    }}>
      {/* Hidden file input for avatar upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={handleAvatarFile}
      />

      {/* Avatar with edit overlay */}
      <div
        onClick={() => { haptic("light"); fileInputRef.current?.click(); }}
        style={{
          width: 72, height: 72, borderRadius: "50%",
          position: "relative", cursor: "pointer",
          marginBottom: 12, flexShrink: 0,
        }}
      >
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt=""
            style={{
              width: 72, height: 72, borderRadius: "50%",
              objectFit: "cover",
              boxShadow: avatarGlow,
            }}
          />
        ) : (
          <div style={{
            width: 72, height: 72, borderRadius: "50%",
            background: tc.accentGradient,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 28, fontWeight: 700, color: "#fff",
            boxShadow: avatarGlow,
          }}>
            {avatarLetter}
          </div>
        )}
        {/* Edit overlay */}
        <div style={{
          position: "absolute", bottom: 0, right: 0,
          width: 22, height: 22, borderRadius: "50%",
          background: "rgba(0,0,0,0.55)",
          backdropFilter: "blur(4px)",
          display: "flex", alignItems: "center", justifyContent: "center",
          border: "1.5px solid rgba(255,255,255,0.2)",
        }}>
          <IconEdit size={11} color="#fff" />
        </div>
      </div>

      {/* Name + username */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginBottom: 2,
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: tc.textColor }}>
          {displayName}
        </span>
        {isPremium && (
          <IconCrown size={16} color={tc.isTequila ? "#ffd54f" : "#ffc107"} />
        )}
      </div>
      {username && (
        <div style={{ fontSize: 13, color: tc.hintColor, marginBottom: 8 }}>
          @{username}
        </div>
      )}

      {/* Member since */}
      {stats.member_since && (
        <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 12 }}>
          {formatMemberSince(stats.member_since)}
        </div>
      )}

      {/* Level + XP bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        width: "100%", maxWidth: 260, marginBottom: 8,
      }}>
        <div style={{
          padding: "3px 10px", borderRadius: 10,
          background: tc.activeBg, border: tc.cardBorder,
          fontSize: 11, fontWeight: 600, color: tc.highlight,
          whiteSpace: "nowrap", flexShrink: 0,
        }}>
          <IconChart size={10} color={tc.highlight} />{" "}
          Уровень {stats.level}
        </div>
        <div style={{ flex: 1, position: "relative" }}>
          <div style={{
            width: "100%", height: 6, borderRadius: 3,
            background: "rgba(255,255,255,0.08)",
          }}>
            <div style={{
              width: `${xpProgress * 100}%`, height: "100%", borderRadius: 3,
              background: tc.accentGradient,
              transition: "width 0.4s ease",
            }} />
          </div>
          <div style={{
            position: "absolute", right: 0, top: 10,
            fontSize: 10, color: tc.hintColor,
          }}>
            {stats.xp}/{xpForNext} XP
          </div>
        </div>
      </div>

      {/* Streak + next milestone */}
      {stats.streak_days > 0 && (
        <div style={{ marginTop: 12, textAlign: "center" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
            fontSize: 13, fontWeight: 600,
            color: tc.isTequila ? "#ffab40" : "#ff7043",
          }}>
            <IconFire size={16} color={tc.isTequila ? "#ffab40" : "#ff7043"} />
            {stats.streak_days} дней подряд
          </div>
          {stats.next_streak_milestone && (
            <div style={{
              fontSize: 11, color: tc.hintColor, marginTop: 4,
              display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
            }}>
              ещё {stats.next_streak_milestone.remaining}д до бонуса +{stats.next_streak_milestone.xp} XP
            </div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <ProfileErrorBoundary fallbackColor={tc.hintColor}>
    <div style={{ paddingBottom: 24 }}>
      {/* ── Profile header ─────────────────────────────────────────── */}
      {isPremium ? (
        <div style={{ ...premiumBorderStyle, marginBottom: 16 }}>
          {headerCard}
        </div>
      ) : (
        <div style={{ marginBottom: 16 }}>{headerCard}</div>
      )}

      {/* ── Stats cards ────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {/* Total plays */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: tc.cardBg, border: tc.cardBorder,
          backdropFilter: "blur(16px)",
          textAlign: "center",
          boxShadow: tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.3})`),
        }}>
          <IconMusicNote size={18} color={tc.highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: tc.textColor, marginTop: 4 }}>
            {(stats.total_plays || 0).toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor }}>треков</div>
        </div>

        {/* Listening time */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: tc.cardBg, border: tc.cardBorder,
          backdropFilter: "blur(16px)",
          textAlign: "center",
          boxShadow: tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.3})`),
        }}>
          <IconHeadphones size={18} color={tc.highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: tc.textColor, marginTop: 4 }}>
            {formatTime(stats.total_time || 0)}
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor }}>прослушано</div>
        </div>

        {/* Favorites */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: tc.cardBg, border: tc.cardBorder,
          backdropFilter: "blur(16px)",
          textAlign: "center",
          boxShadow: tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.3})`),
        }}>
          <IconDiamond size={18} color={tc.highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: tc.textColor, marginTop: 4 }}>
            {(stats.total_favorites || 0).toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor }}>избранных</div>
        </div>
      </div>

      {/* ── Top Artists ────────────────────────────────────────────── */}
      {topArtists.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Топ исполнители
          </div>
          {topArtists.map((artist, idx) => (
            <div key={artist.name} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 12px", borderRadius: 12, marginBottom: 6,
              background: tc.cardBg, border: tc.cardBorder,
              backdropFilter: "blur(16px)",
            }}>
              <div style={{
                width: 22, fontSize: 12, fontWeight: 700, textAlign: "center",
                color: idx < 3 ? tc.highlight : tc.hintColor, flexShrink: 0,
              }}>
                {idx + 1}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 13, fontWeight: 500, color: tc.textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  marginBottom: 4,
                }}>
                  {artist.name}
                </div>
                <div style={{
                  width: "100%", height: 4, borderRadius: 2,
                  background: "rgba(255,255,255,0.06)",
                }}>
                  <div style={{
                    width: `${(artist.count / maxArtistCount) * 100}%`,
                    height: "100%", borderRadius: 2,
                    background: tc.accentGradient,
                    transition: "width 0.3s ease",
                  }} />
                </div>
              </div>
              <div style={{ fontSize: 11, color: tc.hintColor, flexShrink: 0 }}>
                {artist.count}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Top Genres ─────────────────────────────────────────────── */}
      {topGenres.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Жанры
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {topGenres.map((genre) => (
              <div key={genre.name} style={{
                padding: "5px 12px", borderRadius: 12,
                background: tc.cardBg, border: tc.cardBorder,
                backdropFilter: "blur(16px)",
                fontSize: 12, color: tc.textColor, fontWeight: 500,
                display: "flex", alignItems: "center", gap: 5,
              }}>
                {genre.name}
                <span style={{
                  fontSize: 10, color: tc.hintColor,
                  padding: "1px 5px", borderRadius: 6,
                  background: "rgba(255,255,255,0.06)",
                }}>
                  {genre.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Achievements ───────────────────────────────────────────── */}
      {badges.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Достижения
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8,
          }}>
            {badges.map((badgeId) => {
              const def = BADGE_DEFS[badgeId];
              if (!def) return null;
              const BadgeIcon = BADGE_ICONS[badgeId] || IconCrown;
              return (
                <div key={badgeId} style={{
                  padding: "12px 14px", borderRadius: 14,
                  background: tc.cardBg, border: tc.cardBorder,
                  backdropFilter: "blur(16px)",
                }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 10,
                    background: tc.activeBg,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    marginBottom: 8,
                  }}>
                    <BadgeIcon size={16} color={tc.highlight} />
                  </div>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: tc.textColor, marginBottom: 2,
                  }}>
                    {def.label}
                  </div>
                  <div style={{ fontSize: 11, color: tc.hintColor }}>
                    {def.desc}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Weekly Challenges ──────────────────────────────────── */}
      {challenges && challenges.challenges.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 10,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <IconFire size={16} color={tc.isTequila ? "#ffab40" : "#ff7043"} /> Челленджи
          </div>
          {challenges.challenges.map((ch) => {
            const pct = ch.target > 0 ? Math.min(ch.progress / ch.target, 1) : 0;
            return (
              <div
                key={ch.id}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 12px", borderRadius: 12, marginBottom: 6,
                  background: ch.completed
                    ? (tc.isTequila ? "rgba(255,143,0,0.08)" : `${accentColor}08`)
                    : tc.cardBg,
                  border: tc.cardBorder,
                  backdropFilter: "blur(16px)",
                }}
              >
                <div style={{ fontSize: 20, flexShrink: 0, filter: ch.completed ? "none" : "grayscale(0.3)" }}>
                  {ch.icon}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 12, fontWeight: 600, color: tc.textColor, marginBottom: 4,
                  }}>
                    {ch.title.ru || ch.title.en}
                  </div>
                  <div style={{
                    width: "100%", height: 4, borderRadius: 2,
                    background: "rgba(255,255,255,0.06)",
                  }}>
                    <div style={{
                      width: `${pct * 100}%`, height: "100%", borderRadius: 2,
                      background: ch.completed ? tc.accentGradient : tc.accentGradient,
                      transition: "width 0.3s ease",
                    }} />
                  </div>
                </div>
                <div style={{
                  fontSize: 10, color: ch.completed ? tc.highlight : tc.hintColor,
                  flexShrink: 0, textAlign: "right",
                }}>
                  <div>{ch.progress}/{ch.target}</div>
                  <div>+{ch.xp_reward} XP</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Favorites ────────────────────────────────────────────── */}
      {favorites.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 10,
          }}>
            <div style={{
              fontSize: 15, fontWeight: 600, color: tc.textColor,
              letterSpacing: 0.4, display: "flex", alignItems: "center", gap: 6,
            }}>
              <IconHeart size={16} color={tc.highlight} filled /> Избранное
            </div>
            {favorites.length > 5 && (
              <button onClick={() => setShowAllFavs(!showAllFavs)} style={{
                background: "none", border: "none", color: tc.highlight,
                fontSize: 12, fontWeight: 600, cursor: "pointer",
              }}>
                {showAllFavs ? "Свернуть" : `Все (${favorites.length})`}
              </button>
            )}
          </div>
          <div style={{
            display: "flex", gap: 10, overflowX: showAllFavs ? undefined : "auto",
            flexWrap: showAllFavs ? "wrap" : undefined,
            scrollbarWidth: "none", WebkitOverflowScrolling: "touch",
            padding: "2px 0",
          }}>
            {(showAllFavs ? favorites : favorites.slice(0, 10)).map((t, idx) => (
              <div
                key={`fav-${t.video_id}-${idx}`}
                onClick={() => { haptic("light"); onPlayTrack(t); }}
                style={{
                  minWidth: showAllFavs ? "calc(50% - 5px)" : 110,
                  maxWidth: showAllFavs ? "calc(50% - 5px)" : 110,
                  cursor: "pointer", borderRadius: 14, overflow: "hidden",
                  background: tc.cardBg, border: tc.cardBorder,
                  flexShrink: 0,
                }}
              >
                <div style={{
                  width: "100%", aspectRatio: "1", overflow: "hidden",
                  background: tc.coverPlaceholderBg,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {t.cover_url
                    ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    : <IconMusic size={28} color={tc.hintColor} />
                  }
                </div>
                <div style={{ padding: "6px 8px" }}>
                  <div style={{
                    fontSize: 11, fontWeight: 600, color: tc.textColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.title}</div>
                  <div style={{
                    fontSize: 10, color: tc.hintColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.artist}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recent History ─────────────────────────────────────────── */}
      {recentTracks.length > 0 && (
        <div>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            История
          </div>
          {recentTracks.slice(0, 20).map((t, idx) => (
            <div
              key={`${t.video_id}-${idx}`}
              onClick={() => { haptic("light"); onPlayTrack(t); }}
              style={{
                display: "flex", alignItems: "center",
                padding: "8px 12px", borderRadius: 14, marginBottom: 6,
                background: tc.cardBg, border: tc.cardBorder,
                backdropFilter: "blur(16px)",
                cursor: "pointer",
              }}
            >
              {/* Cover */}
              <div style={{
                width: 44, height: 44, borderRadius: 10, overflow: "hidden",
                flexShrink: 0, marginRight: 12,
                background: tc.coverPlaceholderBg,
                border: `1px solid ${tc.accentBorderAlpha}`,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {t.cover_url
                  ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : <IconMusic size={20} color={tc.hintColor} />
                }
              </div>

              {/* Title + artist */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14, color: tc.textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {t.title}
                </div>
                <div style={{ fontSize: 12, color: tc.hintColor }}>
                  {t.artist}
                </div>
              </div>

              {/* Time ago */}
              {(t as any).played_at && (
                <div style={{
                  fontSize: 11, color: tc.hintColor, flexShrink: 0, marginLeft: 8,
                }}>
                  {timeAgo((t as any).played_at)}
                </div>
              )}

              {/* Play icon */}
              <div style={{
                width: 28, height: 28, borderRadius: 8,
                display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0, marginLeft: 4,
              }}>
                <IconPlaySmall size={14} color={tc.highlight} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
    </ProfileErrorBoundary>
  );
}
