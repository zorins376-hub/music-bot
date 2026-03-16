import { useState, useEffect } from "preact/hooks";
import { fetchLeaderboard, fetchChallenges, type LeaderboardData, type ChallengesData } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconCrown, IconFire, IconChart, IconSpinner, IconDiamond,
  IconRocket, IconHeadphones,
} from "./Icons";

interface Props {
  userId: number;
  accentColor?: string;
  themeId?: string;
}

const MEDALS = ["🥇", "🥈", "🥉"];

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function LeaderboardView({
  userId,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [period, setPeriod] = useState<"weekly" | "alltime">("weekly");
  const [lb, setLb] = useState<LeaderboardData | null>(null);
  const [challenges, setChallenges] = useState<ChallengesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(false);
    fetchLeaderboard(period)
      .then(setLb)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [period]);

  useEffect(() => {
    fetchChallenges(userId).then(setChallenges).catch(() => {});
  }, [userId]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IconSpinner size={28} color={tc.hintColor} />
      </div>
    );
  }

  if (error || !lb) {
    return (
      <div style={{ textAlign: "center", padding: 64, color: tc.hintColor, fontSize: 14 }}>
        Не удалось загрузить рейтинг
      </div>
    );
  }

  const weekEndLabel = challenges?.week_end
    ? new Date(challenges.week_end).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    : null;

  return (
    <div style={{ paddingBottom: 24 }}>
      {/* ── Period toggle ──────────────────────────────────────────── */}
      <div style={{
        display: "flex", gap: 8, marginBottom: 16,
        padding: "4px", borderRadius: 14,
        background: tc.cardBg, border: tc.cardBorder,
      }}>
        {(["weekly", "alltime"] as const).map((p) => {
          const active = period === p;
          return (
            <button
              key={p}
              onClick={() => { haptic("light"); setPeriod(p); }}
              style={{
                flex: 1, padding: "10px 0", borderRadius: 11,
                border: "none", cursor: "pointer",
                background: active ? tc.activeBg : "transparent",
                color: active ? tc.highlight : tc.hintColor,
                fontSize: 13, fontWeight: active ? 700 : 500,
                transition: "all 0.2s ease",
                boxShadow: active ? tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.3})`) : "none",
              }}
            >
              {p === "weekly" ? "Неделя" : "Всё время"}
            </button>
          );
        })}
      </div>

      {/* ── My rank card ───────────────────────────────────────────── */}
      <div style={{
        padding: "16px", borderRadius: 16, marginBottom: 16,
        background: tc.cardBg, border: tc.cardBorder,
        backdropFilter: "blur(16px)",
        display: "flex", alignItems: "center", gap: 14,
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 14,
          background: tc.activeBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.4})`),
        }}>
          <IconCrown size={22} color={tc.highlight} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: tc.hintColor, marginBottom: 2 }}>Твой рейтинг</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: tc.textColor }}>
            {lb.my_rank ? `#${lb.my_rank}` : "—"}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: tc.highlight }}>{lb.my_xp} XP</div>
          <div style={{
            fontSize: 11, color: tc.hintColor,
            display: "flex", alignItems: "center", gap: 3, justifyContent: "flex-end",
          }}>
            <IconChart size={10} color={tc.hintColor} /> Ур. {lb.my_level}
          </div>
        </div>
      </div>

      {/* ── Top list ───────────────────────────────────────────────── */}
      <div style={{
        fontSize: 15, fontWeight: 600, color: tc.textColor,
        letterSpacing: 0.4, marginBottom: 10,
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <IconRocket size={16} color={tc.highlight} /> Топ-20
      </div>

      {lb.entries.length === 0 ? (
        <div style={{
          textAlign: "center", padding: 32, color: tc.hintColor, fontSize: 13,
          borderRadius: 14, background: tc.cardBg, border: tc.cardBorder,
        }}>
          Пока нет данных
        </div>
      ) : (
        lb.entries.slice(0, 20).map((entry, idx) => {
          const rank = idx + 1;
          const isMe = entry.user_id === userId;
          return (
            <div
              key={entry.user_id}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 12px", borderRadius: 14, marginBottom: 6,
                background: isMe
                  ? (tc.isTequila ? "rgba(255,143,0,0.12)" : `${accentColor}15`)
                  : tc.cardBg,
                border: isMe
                  ? `1px solid ${tc.isTequila ? "rgba(255,213,79,0.25)" : `${accentColor}30`}`
                  : tc.cardBorder,
                backdropFilter: "blur(16px)",
                transition: "all 0.2s ease",
              }}
            >
              {/* Rank */}
              <div style={{
                width: 28, textAlign: "center", flexShrink: 0,
                fontSize: rank <= 3 ? 18 : 13,
                fontWeight: 700,
                color: rank <= 3 ? tc.highlight : tc.hintColor,
              }}>
                {rank <= 3 ? MEDALS[rank - 1] : rank}
              </div>

              {/* Name */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14, fontWeight: isMe ? 700 : 500, color: tc.textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {entry.name}{isMe ? " ◄" : ""}
                </div>
                <div style={{ fontSize: 11, color: tc.hintColor }}>
                  Ур. {entry.level}
                </div>
              </div>

              {/* Score */}
              <div style={{
                fontSize: 14, fontWeight: 700, flexShrink: 0,
                color: rank <= 3 ? tc.highlight : tc.textColor,
              }}>
                {entry.score.toLocaleString()} XP
              </div>
            </div>
          );
        })
      )}

      {/* ── Weekly Challenges ──────────────────────────────────────── */}
      {challenges && challenges.challenges.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, color: tc.textColor,
            letterSpacing: 0.4, marginBottom: 4,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <IconFire size={16} color={tc.isTequila ? "#ffab40" : "#ff7043"} /> Челленджи недели
          </div>
          {weekEndLabel && (
            <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 10 }}>
              до {weekEndLabel}
            </div>
          )}

          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8,
          }}>
            {challenges.challenges.map((ch) => {
              const pct = ch.target > 0 ? Math.min(ch.progress / ch.target, 1) : 0;
              return (
                <div
                  key={ch.id}
                  style={{
                    padding: "14px", borderRadius: 14,
                    background: ch.completed
                      ? (tc.isTequila ? "rgba(255,143,0,0.1)" : `${accentColor}10`)
                      : tc.cardBg,
                    border: ch.completed
                      ? `1px solid ${tc.isTequila ? "rgba(255,213,79,0.2)" : `${accentColor}25`}`
                      : tc.cardBorder,
                    backdropFilter: "blur(16px)",
                    opacity: ch.completed ? 0.85 : 1,
                  }}
                >
                  <div style={{
                    fontSize: 20, marginBottom: 6,
                    filter: ch.completed ? "none" : "grayscale(0.3)",
                  }}>
                    {ch.icon}
                  </div>
                  <div style={{
                    fontSize: 12, fontWeight: 600, color: tc.textColor,
                    marginBottom: 6, lineHeight: 1.3,
                  }}>
                    {ch.title.ru || ch.title.en}
                  </div>

                  {/* Progress bar */}
                  <div style={{
                    width: "100%", height: 5, borderRadius: 3,
                    background: "rgba(255,255,255,0.08)", marginBottom: 4,
                  }}>
                    <div style={{
                      width: `${pct * 100}%`, height: "100%", borderRadius: 3,
                      background: ch.completed
                        ? (tc.isTequila ? "linear-gradient(90deg, #ff8f00, #ffd54f)" : tc.accentGradient)
                        : tc.accentGradient,
                      transition: "width 0.4s ease",
                    }} />
                  </div>

                  <div style={{
                    display: "flex", justifyContent: "space-between",
                    fontSize: 10, color: tc.hintColor,
                  }}>
                    <span>{ch.progress}/{ch.target}</span>
                    <span style={{ color: ch.completed ? tc.highlight : tc.hintColor }}>
                      {ch.completed ? "✓" : ""} +{ch.xp_reward} XP
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
