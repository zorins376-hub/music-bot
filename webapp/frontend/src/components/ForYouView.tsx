import { useState, useEffect, useCallback } from "preact/hooks";
import { fetchWave, fetchTrending, fetchSimilar, generateAiPlaylist, fetchTrackOfDay, type Track } from "../api";
import { IconWave, IconTrending, IconSimilar, IconSpinner, IconRocket, IconFire, IconPlaySmall, IconMusicNote, IconPlus, IconStar } from "./Icons";

interface Props {
  userId: number;
  currentTrack?: Track | null;
  onPlayTrack: (track: Track) => void;
  onPlayAll?: (tracks: Track[]) => void;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

export function ForYouView({
  userId,
  currentTrack,
  onPlayTrack,
  onPlayAll,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const isTequila = themeId === "tequila";

  // --- Theme tokens ---
  const textColor = isTequila ? "#fef0e0" : "#eee";
  const hintColor = isTequila ? "#c8a882" : "rgba(255,255,255,0.5)";
  const accent = isTequila ? "#ffd54f" : accentColor;
  const cardBg = isTequila ? "rgba(40, 25, 15, 0.55)" : "rgba(20, 20, 30, 0.6)";
  const cardBorder = isTequila ? "1px solid rgba(255, 213, 79, 0.15)" : "1px solid rgba(124, 77, 255, 0.15)";
  const sectionBg = isTequila ? "rgba(40, 25, 15, 0.6)" : "rgba(30, 25, 50, 0.5)";

  // --- Wave state ---
  const [waveTracks, setWaveTracks] = useState<Track[]>([]);
  const [waveLoading, setWaveLoading] = useState(true);
  const [waveError, setWaveError] = useState(false);

  // --- Trending state ---
  const [trendingTracks, setTrendingTracks] = useState<Track[]>([]);
  const [trendingLoading, setTrendingLoading] = useState(true);
  const [trendingError, setTrendingError] = useState(false);

  // --- Similar state ---
  const [similarTracks, setSimilarTracks] = useState<Track[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState(false);

  // --- Track of the Day ---
  const [todTrack, setTodTrack] = useState<Track | null>(null);

  // --- AI Playlist state ---
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiTracks, setAiTracks] = useState<Track[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(false);

  // --- Fetch Track of Day ---
  useEffect(() => {
    fetchTrackOfDay().then(setTodTrack).catch(() => {});
  }, []);

  // --- Fetch wave ---
  useEffect(() => {
    setWaveLoading(true);
    setWaveError(false);
    fetchWave(userId, 10)
      .then(setWaveTracks)
      .catch(() => { setWaveTracks([]); setWaveError(true); })
      .finally(() => setWaveLoading(false));
  }, [userId]);

  // --- Fetch trending ---
  useEffect(() => {
    setTrendingLoading(true);
    setTrendingError(false);
    fetchTrending(24, 15)
      .then(setTrendingTracks)
      .catch(() => { setTrendingTracks([]); setTrendingError(true); })
      .finally(() => setTrendingLoading(false));
  }, []);

  // --- Fetch similar ---
  useEffect(() => {
    if (!currentTrack?.video_id) {
      setSimilarTracks([]);
      return;
    }
    setSimilarLoading(true);
    setSimilarError(false);
    fetchSimilar(currentTrack.video_id, 8)
      .then(setSimilarTracks)
      .catch(() => { setSimilarTracks([]); setSimilarError(true); })
      .finally(() => setSimilarLoading(false));
  }, [currentTrack?.video_id]);

  // --- AI Playlist ---
  const handleGenerateAi = useCallback(async () => {
    const prompt = aiPrompt.trim();
    if (!prompt || aiLoading) return;
    haptic("medium");
    setAiLoading(true);
    setAiError(false);
    setAiTracks([]);
    try {
      const tracks = await generateAiPlaylist(prompt, 10);
      setAiTracks(tracks);
    } catch {
      setAiError(true);
    }
    setAiLoading(false);
  }, [aiPrompt, aiLoading]);

  const handlePlayTrack = useCallback((t: Track) => {
    haptic("light");
    onPlayTrack(t);
  }, [onPlayTrack]);

  const handlePlayAll = useCallback((tracks: Track[]) => {
    if (tracks.length === 0) return;
    haptic("medium");
    if (onPlayAll) {
      onPlayAll(tracks);
    } else {
      onPlayTrack(tracks[0]);
    }
  }, [onPlayAll, onPlayTrack]);

  // --- Section heading ---
  const SectionHeading = ({ icon, title }: { icon: preact.ComponentChild; title: string }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      {icon}
      <span style={{
        fontSize: 11, fontWeight: 700, color: hintColor,
        textTransform: "uppercase", letterSpacing: 2,
      }}>{title}</span>
    </div>
  );

  // --- Horizontal card scroller ---
  const HorizontalCards = ({ tracks, loading, error }: { tracks: Track[]; loading: boolean; error: boolean }) => {
    if (loading) {
      return (
        <div style={{ textAlign: "center", padding: 24 }}>
          <IconSpinner size={22} color={hintColor} />
        </div>
      );
    }
    if (error) {
      return (
        <div style={{ textAlign: "center", color: hintColor, padding: 20, fontSize: 12 }}>
          Не удалось загрузить
        </div>
      );
    }
    if (tracks.length === 0) {
      return (
        <div style={{ textAlign: "center", color: hintColor, padding: 20, fontSize: 12 }}>
          Нет данных
        </div>
      );
    }
    return (
      <div style={{
        display: "flex", gap: 12, overflowX: "auto",
        padding: "8px 0", scrollbarWidth: "none",
        WebkitOverflowScrolling: "touch",
      }}>
        {tracks.map(t => (
          <div key={t.video_id} onClick={() => handlePlayTrack(t)} style={{
            minWidth: 130, maxWidth: 130, cursor: "pointer",
            borderRadius: 16, overflow: "hidden",
            background: sectionBg,
            border: cardBorder,
            transition: "transform 0.15s ease",
          }}>
            <div style={{
              width: 130, height: 130, overflow: "hidden",
              background: isTequila ? "rgba(255,213,79,0.06)" : "rgba(124,77,255,0.06)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              {t.cover_url
                ? <img src={t.cover_url} alt="" style={{ width: 130, height: 130, objectFit: "cover", display: "block" }} />
                : <IconMusicNote size={32} color={hintColor} />
              }
            </div>
            <div style={{ padding: "8px 10px" }}>
              <div style={{
                fontSize: 12, fontWeight: 600, color: textColor,
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
    );
  };

  return (
    <div style={{ paddingBottom: 24 }}>
      {/* ===== Page Header ===== */}
      <div style={{ marginBottom: 24 }}>
        <div style={{
          fontSize: 22, fontWeight: 700, color: textColor,
          letterSpacing: 0.3, marginBottom: 4,
        }}>
          Для тебя
        </div>
        <div style={{ fontSize: 13, color: hintColor }}>
          Персональные рекомендации
        </div>
      </div>

      {/* ===== Track of the Day ===== */}
      {todTrack && (
        <div
          onClick={() => handlePlayTrack(todTrack)}
          style={{
            marginBottom: 20, padding: 16, borderRadius: 22,
            background: isTequila
              ? "linear-gradient(135deg, rgba(255,109,0,0.22), rgba(255,213,79,0.10))"
              : `linear-gradient(135deg, ${accentColor}33, rgba(124,77,255,0.08))`,
            border: isTequila
              ? "1px solid rgba(255,213,79,0.25)"
              : `1px solid ${accentColor}44`,
            backdropFilter: "blur(16px)",
            cursor: "pointer",
            display: "flex", alignItems: "center", gap: 14,
            boxShadow: isTequila
              ? "0 8px 28px rgba(255,109,0,0.15)"
              : `0 8px 28px ${accentColor}22`,
          }}
        >
          <div style={{
            width: 72, height: 72, borderRadius: 16, overflow: "hidden", flexShrink: 0,
            background: isTequila ? "rgba(255,213,79,0.1)" : "rgba(124,77,255,0.1)",
            border: isTequila ? "1px solid rgba(255,213,79,0.2)" : `1px solid ${accentColor}33`,
          }}>
            {todTrack.cover_url
              ? <img src={todTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusicNote size={28} color={accent} /></div>
            }
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 5, marginBottom: 4,
            }}>
              <IconStar size={14} color={accent} filled />
              <span style={{ fontSize: 10, fontWeight: 700, color: accent, textTransform: "uppercase", letterSpacing: 1.5 }}>
                Трек дня
              </span>
            </div>
            <div style={{
              fontSize: 15, fontWeight: 600, color: textColor,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{todTrack.title}</div>
            <div style={{
              fontSize: 12, color: hintColor,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{todTrack.artist}</div>
          </div>
          <div style={{
            width: 40, height: 40, borderRadius: 12,
            background: isTequila
              ? "linear-gradient(135deg, #ff8f00, #ffb300)"
              : `linear-gradient(135deg, ${accentColor}, rgba(124,77,255,0.8))`,
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
            boxShadow: isTequila
              ? "0 4px 16px rgba(255,143,0,0.35)"
              : `0 4px 16px ${accentColor}55`,
          }}>
            <IconPlaySmall size={20} color="#fff" />
          </div>
        </div>
      )}

      {/* ===== Quick Mood Buttons ===== */}
      <div style={{
        display: "flex", gap: 8, marginBottom: 20, overflowX: "auto",
        scrollbarWidth: "none", WebkitOverflowScrolling: "touch",
        padding: "2px 0",
      }}>
        {[
          { mood: "chill", label: "Chill", gradient: "linear-gradient(135deg, #00bcd4, #26c6da)" },
          { mood: "energy", label: "Энергия", gradient: "linear-gradient(135deg, #ff5722, #ff9800)" },
          { mood: "focus", label: "Фокус", gradient: "linear-gradient(135deg, #7c4dff, #b388ff)" },
          { mood: "romance", label: "Романтика", gradient: "linear-gradient(135deg, #e91e63, #f48fb1)" },
          { mood: "party", label: "Party", gradient: "linear-gradient(135deg, #ffc107, #ff6d00)" },
          { mood: "melancholy", label: "Грусть", gradient: "linear-gradient(135deg, #546e7a, #90a4ae)" },
        ].map(({ mood, label, gradient }) => (
          <button
            key={mood}
            onClick={() => {
              haptic("medium");
              fetchWave(userId, 10, mood).then((tracks) => {
                if (tracks.length > 0 && onPlayAll) onPlayAll(tracks);
                else if (tracks.length > 0) onPlayTrack(tracks[0]);
              }).catch(() => {});
            }}
            style={{
              padding: "10px 18px", borderRadius: 16, border: "none",
              background: gradient, color: "#fff",
              fontSize: 12, fontWeight: 700, cursor: "pointer",
              whiteSpace: "nowrap", flexShrink: 0,
              boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
              transition: "transform 0.15s ease",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ===== Wave Section ===== */}
      <div style={{
        marginBottom: 28, padding: 16, borderRadius: 22,
        background: cardBg, border: cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <SectionHeading icon={<IconWave size={16} color={accent} />} title="Волна" />
          {waveTracks.length > 0 && (
            <button onClick={() => handlePlayAll(waveTracks)} style={{
              padding: "5px 12px", borderRadius: 12, border: "none",
              background: isTequila
                ? "linear-gradient(135deg, #ff8f00, #ffb300)"
                : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.6))`,
              color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 4,
            }}>
              <IconPlaySmall size={12} color="#fff" />
              Слушать все
            </button>
          )}
        </div>
        <HorizontalCards tracks={waveTracks} loading={waveLoading} error={waveError} />
      </div>

      {/* ===== Trending Section ===== */}
      <div style={{
        marginBottom: 28, padding: 16, borderRadius: 22,
        background: cardBg, border: cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <SectionHeading icon={<IconTrending size={16} color={accent} />} title="В тренде" />

        {trendingLoading ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <IconSpinner size={22} color={hintColor} />
          </div>
        ) : trendingError ? (
          <div style={{ textAlign: "center", color: hintColor, padding: 20, fontSize: 12 }}>
            Не удалось загрузить
          </div>
        ) : trendingTracks.length === 0 ? (
          <div style={{ textAlign: "center", color: hintColor, padding: 20, fontSize: 12 }}>
            Нет данных
          </div>
        ) : (
          trendingTracks.map((t, idx) => (
            <div key={`${t.video_id}-${idx}`} onClick={() => handlePlayTrack(t)} style={{
              display: "flex", alignItems: "center", padding: "8px 10px",
              borderRadius: 14, marginBottom: 4, cursor: "pointer",
              background: "transparent",
              transition: "background 0.15s ease",
            }}>
              <div style={{
                width: 24, fontSize: 13, fontWeight: 700, marginRight: 10, textAlign: "center", flexShrink: 0,
                color: idx < 3 ? accent : hintColor,
                display: "flex", alignItems: "center", justifyContent: "center", gap: 2,
              }}>
                {idx < 3 && <IconFire size={12} color={accent} />}
                {idx + 1}
              </div>
              <div style={{
                width: 48, height: 48, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12,
                background: isTequila ? "rgba(255,213,79,0.08)" : "rgba(124,77,255,0.08)",
                border: isTequila ? "1px solid rgba(255,213,79,0.14)" : "1px solid rgba(255,255,255,0.06)",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {t.cover_url
                  ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : <IconMusicNote size={20} color={hintColor} />
                }
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14, fontWeight: 500, color: textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{t.title}</div>
                <div style={{
                  fontSize: 12, color: hintColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{t.artist}</div>
              </div>
              <div style={{
                width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <IconPlaySmall size={16} color={hintColor} />
              </div>
            </div>
          ))
        )}
      </div>

      {/* ===== Similar Section (only if current track) ===== */}
      {currentTrack && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: cardBg, border: cardBorder,
          backdropFilter: "blur(16px)",
        }}>
          <SectionHeading icon={<IconSimilar size={16} color={accent} />} title="Похожее" />
          <div style={{
            fontSize: 13, color: textColor, marginBottom: 10, marginTop: -4,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            Похожее на <span style={{ fontWeight: 600, color: accent }}>{currentTrack.title}</span>
          </div>
          <HorizontalCards tracks={similarTracks} loading={similarLoading} error={similarError} />
        </div>
      )}

      {/* ===== AI Playlist Generator ===== */}
      <div style={{
        padding: 16, borderRadius: 22,
        background: cardBg, border: cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <SectionHeading icon={<IconRocket size={16} color={accent} />} title="AI Плейлист" />

        <div style={{ display: "flex", gap: 8, marginBottom: aiTracks.length > 0 || aiError ? 14 : 0 }}>
          <input
            type="text"
            value={aiPrompt}
            onInput={(e) => setAiPrompt((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleGenerateAi(); }}
            placeholder="Опиши настроение или жанр..."
            disabled={aiLoading}
            style={{
              flex: 1, padding: "10px 14px", borderRadius: 14, fontSize: 13,
              border: isTequila ? "1px solid rgba(255,213,79,0.2)" : "1px solid rgba(124,77,255,0.2)",
              background: isTequila ? "rgba(30, 18, 10, 0.6)" : "rgba(255,255,255,0.05)",
              color: textColor, outline: "none", boxSizing: "border-box",
              opacity: aiLoading ? 0.5 : 1,
            }}
          />
          <button
            onClick={handleGenerateAi}
            disabled={aiLoading || !aiPrompt.trim()}
            style={{
              padding: "10px 16px", borderRadius: 14, border: "none",
              background: isTequila
                ? "linear-gradient(135deg, #ff8f00, #ffb300)"
                : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.6))`,
              color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
              opacity: aiLoading || !aiPrompt.trim() ? 0.5 : 1,
              whiteSpace: "nowrap",
              display: "flex", alignItems: "center", gap: 6,
              flexShrink: 0,
            }}
          >
            {aiLoading ? <IconSpinner size={14} color="#fff" /> : <IconRocket size={14} color="#fff" />}
            Создать
          </button>
        </div>

        {aiError && (
          <div style={{ textAlign: "center", color: "#ef5350", padding: 12, fontSize: 12 }}>
            Ошибка генерации. Попробуйте ещё раз.
          </div>
        )}

        {aiTracks.length > 0 && (
          <div>
            {onPlayAll && (
              <button onClick={() => handlePlayAll(aiTracks)} style={{
                padding: "6px 14px", borderRadius: 12, border: "none",
                background: isTequila
                  ? "linear-gradient(135deg, #ff8f00, #ffb300)"
                  : `linear-gradient(135deg, ${accentColor}, rgba(124, 77, 255, 0.6))`,
                color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4, marginBottom: 10,
              }}>
                <IconPlaySmall size={12} color="#fff" />
                Слушать все
              </button>
            )}
            {aiTracks.map((t, idx) => (
              <div key={`${t.video_id}-${idx}`} onClick={() => handlePlayTrack(t)} style={{
                display: "flex", alignItems: "center", padding: "8px 10px",
                borderRadius: 14, marginBottom: 4, cursor: "pointer",
              }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12,
                  background: isTequila ? "rgba(255,213,79,0.08)" : "rgba(124,77,255,0.08)",
                  border: isTequila ? "1px solid rgba(255,213,79,0.14)" : "1px solid rgba(255,255,255,0.06)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {t.cover_url
                    ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    : <IconMusicNote size={20} color={hintColor} />
                  }
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 14, fontWeight: 500, color: textColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.title}</div>
                  <div style={{
                    fontSize: 12, color: hintColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.artist}</div>
                </div>
                <div style={{
                  width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <IconPlaySmall size={16} color={hintColor} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
