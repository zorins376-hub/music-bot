import { useState, useEffect } from "preact/hooks";
import type { Track } from "../api";
import { fetchFavoritesList } from "../api";
import {
  IconCrown, IconFire, IconMusicNote, IconChart, IconPlaySmall,
  IconDiamond, IconSpinner, IconHeadphones, IconMusic, IconHeart,
} from "./Icons";

// ── Types ───────────────────────────────────────────────────────────────

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
  const warm = themeId === "tequila";

  const hintColor = warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)";
  const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
  const cardBg = warm ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)";
  const cardBorder = warm ? "1px solid rgba(255, 213, 79, 0.1)" : "1px solid rgba(255,255,255,0.06)";
  const activeBg = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))"
    : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.3))`;
  const accentGradient = warm
    ? "linear-gradient(135deg, #ff8f00, #ffd54f)"
    : `linear-gradient(135deg, ${accentColor}, #b388ff)`;
  const highlight = warm ? "#ffd54f" : accentColor;

  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [favorites, setFavorites] = useState<Track[]>([]);
  const [showAllFavs, setShowAllFavs] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(false);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000); // 10s timeout
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
      .then((data: UserStats) => setStats(data))
      .catch(() => setError(true))
      .finally(() => { clearTimeout(timer); setLoading(false); });
    fetchFavoritesList().then(setFavorites).catch(() => {});
    return () => { ctrl.abort(); clearTimeout(timer); };
  }, [userId]);

  // ── Loading / error states ──────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IconSpinner size={28} color={hintColor} />
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div style={{ textAlign: "center", padding: 64, color: hintColor, fontSize: 14 }}>
        Не удалось загрузить профиль
      </div>
    );
  }

  const maxArtistCount = stats.top_artists.length > 0
    ? Math.max(...stats.top_artists.map((a) => a.count))
    : 1;

  const xpForNext = stats.level * 100;
  const xpProgress = xpForNext > 0 ? Math.min(stats.xp / xpForNext, 1) : 0;

  const displayName = firstName || username || "User";
  const avatarLetter = displayName.charAt(0).toUpperCase();

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div style={{ paddingBottom: 24 }}>
      {/* ── Profile header ─────────────────────────────────────────── */}
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        padding: "24px 16px 20px", marginBottom: 16,
        borderRadius: 18, background: cardBg, border: cardBorder,
        backdropFilter: warm ? "blur(12px)" : undefined,
      }}>
        {/* Avatar */}
        <div style={{
          width: 72, height: 72, borderRadius: "50%",
          background: accentGradient,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 28, fontWeight: 700, color: "#fff",
          marginBottom: 12, flexShrink: 0,
          boxShadow: warm
            ? "0 4px 20px rgba(255, 143, 0, 0.3)"
            : "0 4px 20px rgba(124, 77, 255, 0.3)",
        }}>
          {avatarLetter}
        </div>

        {/* Name + username */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6, marginBottom: 2,
        }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: textColor }}>
            {displayName}
          </span>
          {isPremium && (
            <IconCrown size={16} color={warm ? "#ffd54f" : "#ffc107"} />
          )}
        </div>
        {username && (
          <div style={{ fontSize: 13, color: hintColor, marginBottom: 8 }}>
            @{username}
          </div>
        )}

        {/* Member since */}
        {stats.member_since && (
          <div style={{ fontSize: 12, color: hintColor, marginBottom: 12 }}>
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
            background: activeBg, border: cardBorder,
            fontSize: 11, fontWeight: 600, color: highlight,
            whiteSpace: "nowrap", flexShrink: 0,
          }}>
            <IconChart size={10} color={highlight} />{" "}
            Уровень {stats.level}
          </div>
          <div style={{ flex: 1, position: "relative" }}>
            <div style={{
              width: "100%", height: 6, borderRadius: 3,
              background: "rgba(255,255,255,0.08)",
            }}>
              <div style={{
                width: `${xpProgress * 100}%`, height: "100%", borderRadius: 3,
                background: accentGradient,
                transition: "width 0.4s ease",
              }} />
            </div>
            <div style={{
              position: "absolute", right: 0, top: 10,
              fontSize: 10, color: hintColor,
            }}>
              {stats.xp}/{xpForNext} XP
            </div>
          </div>
        </div>

        {/* Streak */}
        {stats.streak_days > 0 && (
          <div style={{
            display: "flex", alignItems: "center", gap: 4,
            marginTop: 12, fontSize: 13, fontWeight: 600,
            color: warm ? "#ffab40" : "#ff7043",
          }}>
            <IconFire size={16} color={warm ? "#ffab40" : "#ff7043"} />
            {stats.streak_days} дней подряд
          </div>
        )}
      </div>

      {/* ── Stats cards ────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {/* Total plays */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: cardBg, border: cardBorder,
          backdropFilter: warm ? "blur(12px)" : undefined,
          textAlign: "center",
        }}>
          <IconMusicNote size={18} color={highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: textColor, marginTop: 4 }}>
            {stats.total_plays.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: hintColor }}>треков</div>
        </div>

        {/* Listening time */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: cardBg, border: cardBorder,
          backdropFilter: warm ? "blur(12px)" : undefined,
          textAlign: "center",
        }}>
          <IconHeadphones size={18} color={highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: textColor, marginTop: 4 }}>
            {formatTime(stats.total_time)}
          </div>
          <div style={{ fontSize: 11, color: hintColor }}>прослушано</div>
        </div>

        {/* Favorites */}
        <div style={{
          flex: 1, padding: "14px 10px", borderRadius: 14,
          background: cardBg, border: cardBorder,
          backdropFilter: warm ? "blur(12px)" : undefined,
          textAlign: "center",
        }}>
          <IconDiamond size={18} color={highlight} />
          <div style={{ fontSize: 20, fontWeight: 700, color: textColor, marginTop: 4 }}>
            {stats.total_favorites.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: hintColor }}>избранных</div>
        </div>
      </div>

      {/* ── Top Artists ────────────────────────────────────────────── */}
      {stats.top_artists.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Топ исполнители
          </div>
          {stats.top_artists.map((artist, idx) => (
            <div key={artist.name} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 12px", borderRadius: 12, marginBottom: 6,
              background: cardBg, border: cardBorder,
              backdropFilter: warm ? "blur(12px)" : undefined,
            }}>
              <div style={{
                width: 22, fontSize: 12, fontWeight: 700, textAlign: "center",
                color: idx < 3 ? highlight : hintColor, flexShrink: 0,
              }}>
                {idx + 1}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 13, fontWeight: 500, color: textColor,
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
                    background: accentGradient,
                    transition: "width 0.3s ease",
                  }} />
                </div>
              </div>
              <div style={{ fontSize: 11, color: hintColor, flexShrink: 0 }}>
                {artist.count}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Top Genres ─────────────────────────────────────────────── */}
      {stats.top_genres.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Жанры
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {stats.top_genres.map((genre) => (
              <div key={genre.name} style={{
                padding: "5px 12px", borderRadius: 12,
                background: cardBg, border: cardBorder,
                backdropFilter: warm ? "blur(12px)" : undefined,
                fontSize: 12, color: textColor, fontWeight: 500,
                display: "flex", alignItems: "center", gap: 5,
              }}>
                {genre.name}
                <span style={{
                  fontSize: 10, color: hintColor,
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
      {stats.badges.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            Достижения
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8,
          }}>
            {stats.badges.map((badgeId) => {
              const def = BADGE_DEFS[badgeId];
              if (!def) return null;
              return (
                <div key={badgeId} style={{
                  padding: "12px 14px", borderRadius: 14,
                  background: cardBg, border: cardBorder,
                  backdropFilter: warm ? "blur(12px)" : undefined,
                }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 10,
                    background: activeBg,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    marginBottom: 8,
                  }}>
                    <IconCrown size={16} color={highlight} />
                  </div>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: textColor, marginBottom: 2,
                  }}>
                    {def.label}
                  </div>
                  <div style={{ fontSize: 11, color: hintColor }}>
                    {def.desc}
                  </div>
                </div>
              );
            })}
          </div>
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
              fontSize: 15, fontWeight: 600, color: textColor,
              letterSpacing: 0.4, display: "flex", alignItems: "center", gap: 6,
            }}>
              <IconHeart size={16} color={highlight} filled /> Избранное
            </div>
            {favorites.length > 5 && (
              <button onClick={() => setShowAllFavs(!showAllFavs)} style={{
                background: "none", border: "none", color: highlight,
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
                  background: cardBg, border: cardBorder,
                  flexShrink: 0,
                }}
              >
                <div style={{
                  width: "100%", aspectRatio: "1", overflow: "hidden",
                  background: warm ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {t.cover_url
                    ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    : <IconMusic size={28} color={hintColor} />
                  }
                </div>
                <div style={{ padding: "6px 8px" }}>
                  <div style={{
                    fontSize: 11, fontWeight: 600, color: textColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.title}</div>
                  <div style={{
                    fontSize: 10, color: hintColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.artist}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recent History ─────────────────────────────────────────── */}
      {stats.recent_tracks.length > 0 && (
        <div>
          <div style={{
            fontSize: 15, fontWeight: 600, color: textColor,
            letterSpacing: 0.4, marginBottom: 10,
          }}>
            История
          </div>
          {stats.recent_tracks.slice(0, 20).map((t, idx) => (
            <div
              key={`${t.video_id}-${idx}`}
              onClick={() => { haptic("light"); onPlayTrack(t); }}
              style={{
                display: "flex", alignItems: "center",
                padding: "8px 12px", borderRadius: 14, marginBottom: 6,
                background: cardBg, border: cardBorder,
                backdropFilter: warm ? "blur(12px)" : undefined,
                cursor: "pointer",
              }}
            >
              {/* Cover */}
              <div style={{
                width: 44, height: 44, borderRadius: 10, overflow: "hidden",
                flexShrink: 0, marginRight: 12,
                background: warm ? "rgba(255, 213, 79, 0.08)" : "rgba(124,77,255,0.08)",
                border: warm
                  ? "1px solid rgba(255, 213, 79, 0.14)"
                  : "1px solid rgba(255,255,255,0.06)",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {t.cover_url
                  ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : <IconMusic size={20} color={hintColor} />
                }
              </div>

              {/* Title + artist */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14, color: textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {t.title}
                </div>
                <div style={{ fontSize: 12, color: hintColor }}>
                  {t.artist}
                </div>
              </div>

              {/* Time ago */}
              {(t as any).played_at && (
                <div style={{
                  fontSize: 11, color: hintColor, flexShrink: 0, marginLeft: 8,
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
                <IconPlaySmall size={14} color={highlight} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
