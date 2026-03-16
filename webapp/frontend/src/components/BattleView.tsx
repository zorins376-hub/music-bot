import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { startBattle, submitBattleScore, getStreamUrl, type BattleData, type BattleRound } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconSpinner, IconRocket, IconFire, IconMusicNote, IconPlaySmall, IconCrown,
} from "./Icons";

interface Props {
  userId: number;
  accentColor?: string;
  themeId?: string;
}

type Phase = "menu" | "loading" | "playing" | "result";

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function BattleView({
  userId,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [phase, setPhase] = useState<Phase>("menu");
  const [battle, setBattle] = useState<BattleData | null>(null);
  const [currentRound, setCurrentRound] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [score, setScore] = useState(0);
  const scoreRef = useRef(0);
  const [xpEarned, setXpEarned] = useState(0);
  const [timer, setTimer] = useState(15);
  const [showCorrect, setShowCorrect] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
      }
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startGame = useCallback(async () => {
    setPhase("loading");
    haptic("medium");
    try {
      const data = await startBattle();
      if (data.rounds.length === 0) {
        setPhase("menu");
        return;
      }
      setBattle(data);
      setCurrentRound(0);
      setScore(0);
      scoreRef.current = 0;
      setSelected(null);
      setShowCorrect(false);
      setPhase("playing");
      playRound(data.rounds[0]);
    } catch {
      setPhase("menu");
    }
  }, []);

  const playRound = useCallback((round: BattleRound) => {
    setSelected(null);
    setShowCorrect(false);
    setTimer(15);

    // Play audio snippet
    if (audioRef.current) {
      audioRef.current.pause();
    }
    const audio = new Audio(getStreamUrl(round.stream_id));
    audio.volume = 0.7;
    // Start from a random position (5-30s in)
    audio.addEventListener("loadedmetadata", () => {
      const maxStart = Math.max(0, audio.duration - 15);
      audio.currentTime = Math.min(5 + Math.random() * 25, maxStart);
      audio.play().catch(() => {});
    }, { once: true });
    audio.play().catch(() => {});
    audioRef.current = audio;

    // Start countdown
    if (timerRef.current) clearInterval(timerRef.current);
    const interval = setInterval(() => {
      setTimer((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          handleTimeout();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    timerRef.current = interval;
  }, []);

  const handleTimeout = useCallback(() => {
    if (showCorrect) return;
    setShowCorrect(true);
    haptic("heavy");
    if (audioRef.current) audioRef.current.pause();
    setTimeout(() => advanceRound(false), 2000);
  }, [showCorrect]);

  const handleAnswer = useCallback((idx: number) => {
    if (selected !== null || !battle) return;
    haptic("light");
    setSelected(idx);
    setShowCorrect(true);
    if (timerRef.current) clearInterval(timerRef.current);
    if (audioRef.current) audioRef.current.pause();

    const round = battle.rounds[currentRound];
    const correct = idx === round.correct_idx;
    if (correct) {
      haptic("medium");
      scoreRef.current += 1;
      setScore(scoreRef.current);
    } else {
      haptic("heavy");
    }

    setTimeout(() => advanceRound(correct), 1800);
  }, [selected, battle, currentRound]);

  const advanceRound = useCallback((wasCorrect: boolean) => {
    if (!battle) return;
    const next = currentRound + 1;
    if (next >= battle.rounds.length) {
      // Game over
      const finalScore = scoreRef.current;
      setPhase("result");
      // Submit score
      submitBattleScore(finalScore, battle.total)
        .then((res) => setXpEarned(res.xp_earned))
        .catch(() => {});
    } else {
      setCurrentRound(next);
      playRound(battle.rounds[next]);
    }
  }, [battle, currentRound, score]);

  // ── Menu ──────────────────────────────────────────────────────────────
  // Inject pulse animation once
  useEffect(() => {
    if (document.getElementById("battle-pulse-style")) return;
    const style = document.createElement("style");
    style.id = "battle-pulse-style";
    style.textContent = `
      @keyframes battle-pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.08); opacity: 0.85; }
      }
    `;
    document.head.appendChild(style);
  }, []);

  // ── Menu ──────────────────────────────────────────────────────────────
  if (phase === "menu") {
    return (
      <div style={{ textAlign: "center", padding: "40px 16px" }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>⚔️</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: tc.textColor, marginBottom: 8 }}>
          Музыкальный Батл
        </div>
        <div style={{ fontSize: 14, color: tc.hintColor, marginBottom: 32, lineHeight: 1.5 }}>
          Угадай трек по короткому отрывку!<br />
          5 раундов · 15 секунд на ответ
        </div>
        <button
          onClick={startGame}
          style={{
            padding: "14px 40px", borderRadius: 16, border: "none",
            background: tc.accentGradient, color: "#fff",
            fontSize: 16, fontWeight: 700, cursor: "pointer",
            boxShadow: tc.glowShadow,
            display: "inline-flex", alignItems: "center", gap: 8,
          }}
        >
          <IconRocket size={18} color="#fff" /> Начать батл
        </button>
      </div>
    );
  }

  // ── Loading ───────────────────────────────────────────────────────────
  if (phase === "loading") {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IconSpinner size={28} color={tc.hintColor} />
        <div style={{ fontSize: 14, color: tc.hintColor, marginTop: 12 }}>Подбираем треки...</div>
      </div>
    );
  }

  // ── Result ────────────────────────────────────────────────────────────
  if (phase === "result" && battle) {
    const pct = battle.total > 0 ? Math.round((score / battle.total) * 100) : 0;
    const emoji = pct === 100 ? "🏆" : pct >= 60 ? "🔥" : pct >= 40 ? "🎵" : "😅";
    return (
      <div style={{ textAlign: "center", padding: "40px 16px" }}>
        <div style={{ fontSize: 56, marginBottom: 12 }}>{emoji}</div>
        <div style={{ fontSize: 24, fontWeight: 700, color: tc.textColor, marginBottom: 6 }}>
          {score} / {battle.total}
        </div>
        <div style={{ fontSize: 14, color: tc.hintColor, marginBottom: 8 }}>
          {pct === 100 ? "Идеально!" : pct >= 60 ? "Отлично!" : pct >= 40 ? "Неплохо!" : "Попробуй ещё!"}
        </div>
        {xpEarned > 0 && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "8px 18px", borderRadius: 12,
            background: tc.activeBg, border: tc.cardBorder,
            fontSize: 14, fontWeight: 600, color: tc.highlight,
            marginBottom: 24,
          }}>
            <IconCrown size={14} color={tc.highlight} /> +{xpEarned} XP
          </div>
        )}
        <div>
          <button
            onClick={startGame}
            style={{
              padding: "14px 40px", borderRadius: 16, border: "none",
              background: tc.accentGradient, color: "#fff",
              fontSize: 15, fontWeight: 700, cursor: "pointer",
              boxShadow: tc.glowShadow,
              display: "inline-flex", alignItems: "center", gap: 8,
            }}
          >
            <IconRocket size={16} color="#fff" /> Ещё раз
          </button>
        </div>
      </div>
    );
  }

  // ── Playing ───────────────────────────────────────────────────────────
  if (!battle) return null;
  const round = battle.rounds[currentRound];

  return (
    <div style={{ padding: "16px 0" }}>
      {/* Header: round + timer + score */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 20, padding: "0 4px",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: tc.hintColor }}>
          Раунд {round.round}/{battle.total}
        </div>
        <div style={{
          fontSize: 20, fontWeight: 700,
          color: timer <= 5 ? "#ff5252" : tc.textColor,
          minWidth: 32, textAlign: "center",
          transition: "color 0.3s",
        }}>
          {timer}
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 4,
          fontSize: 13, fontWeight: 600, color: tc.highlight,
        }}>
          <IconFire size={14} color={tc.highlight} /> {score}
        </div>
      </div>

      {/* Timer bar */}
      <div style={{
        width: "100%", height: 4, borderRadius: 2, marginBottom: 24,
        background: "rgba(255,255,255,0.08)",
      }}>
        <div style={{
          width: `${(timer / 15) * 100}%`, height: "100%", borderRadius: 2,
          background: timer <= 5
            ? "linear-gradient(90deg, #ff5252, #ff1744)"
            : tc.accentGradient,
          transition: "width 1s linear",
        }} />
      </div>

      {/* "What's playing?" card */}
      <div style={{
        textAlign: "center", padding: "32px 16px", marginBottom: 20,
        borderRadius: 18, background: tc.cardBg, border: tc.cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <div style={{
          width: 80, height: 80, borderRadius: 20, margin: "0 auto 16px",
          background: tc.activeBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: tc.glowShadow,
          animation: "battle-pulse 1.5s ease-in-out infinite",
        }}>
          <IconMusicNote size={32} color={tc.highlight} />
        </div>
        <div style={{ fontSize: 16, fontWeight: 600, color: tc.textColor }}>
          🎧 Что за трек?
        </div>
        <div style={{ fontSize: 12, color: tc.hintColor, marginTop: 4 }}>
          Слушай и выбери правильный ответ
        </div>
      </div>

      {/* Answer options */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {round.options.map((opt, idx) => {
          const isCorrect = idx === round.correct_idx;
          const isSelected = selected === idx;
          let bg = tc.cardBg;
          let border = tc.cardBorder;
          let textColor = tc.textColor;

          if (showCorrect) {
            if (isCorrect) {
              bg = tc.isTequila ? "rgba(76,175,80,0.15)" : "rgba(76,175,80,0.12)";
              border = "1px solid rgba(76,175,80,0.4)";
              textColor = "#4caf50";
            } else if (isSelected && !isCorrect) {
              bg = "rgba(244,67,54,0.12)";
              border = "1px solid rgba(244,67,54,0.3)";
              textColor = "#f44336";
            }
          }

          return (
            <button
              key={idx}
              onClick={() => handleAnswer(idx)}
              disabled={selected !== null}
              style={{
                padding: "14px 16px", borderRadius: 14,
                background: bg, border,
                backdropFilter: "blur(16px)",
                cursor: selected !== null ? "default" : "pointer",
                textAlign: "left",
                transition: "all 0.2s ease",
                opacity: showCorrect && !isCorrect && !isSelected ? 0.5 : 1,
              }}
            >
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  background: showCorrect && isCorrect ? "rgba(76,175,80,0.2)" : tc.activeBg,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 700, color: textColor, flexShrink: 0,
                }}>
                  {showCorrect && isCorrect ? "✓" : showCorrect && isSelected ? "✗" : String.fromCharCode(65 + idx)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 14, fontWeight: 600, color: textColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>
                    {opt.title}
                  </div>
                  <div style={{
                    fontSize: 12, color: showCorrect && isCorrect ? "#81c784" : tc.hintColor,
                  }}>
                    {opt.artist}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
