import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import type { JSX } from "preact";
import { fetchWave, fetchTrending, fetchSimilar, generateAiPlaylist, fetchTrackOfDay, fetchSmartPlaylists, type Track, type SmartPlaylist } from "../api";
import { getThemeById, themeColors } from "../themes";
import { IconWave, IconTrending, IconSimilar, IconSpinner, IconRocket, IconFire, IconPlaySmall, IconMusicNote, IconPlus, IconStar, IconHeart, IconMoon, IconDiscover, IconChart } from "./Icons";

type ThemeColors = ReturnType<typeof themeColors>;

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

function SectionHeading({ icon, title, tc }: { icon: JSX.Element; title: string; tc: ThemeColors }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      {icon}
      <span style={{
        fontSize: 11, fontWeight: 700, color: tc.hintColor,
        textTransform: "uppercase", letterSpacing: 2,
      }}>{title}</span>
    </div>
  );
}

function HorizontalCards({
  tracks,
  loading,
  error,
  tc,
  onTrackClick,
}: {
  tracks: Track[];
  loading: boolean;
  error: boolean;
  tc: ThemeColors;
  onTrackClick: (track: Track) => void;
}) {
  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 24 }}>
        <IconSpinner size={22} color={tc.hintColor} />
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ textAlign: "center", color: tc.hintColor, padding: 20, fontSize: 12 }}>
        Не удалось загрузить
      </div>
    );
  }
  if (tracks.length === 0) {
    return (
      <div style={{ textAlign: "center", color: tc.hintColor, padding: 20, fontSize: 12 }}>
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
        <div key={t.video_id} onClick={() => onTrackClick(t)} style={{
          minWidth: 130, maxWidth: 130, cursor: "pointer",
          borderRadius: 16, overflow: "hidden",
          background: tc.cardBg,
          border: tc.cardBorder,
          transition: "transform 0.15s ease",
        }}>
          <div style={{
            width: 130, height: 130, overflow: "hidden",
            background: tc.coverPlaceholderBg,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {t.cover_url
              ? <img src={t.cover_url} alt="" style={{ width: 130, height: 130, objectFit: "cover", display: "block" }} />
              : <IconMusicNote size={32} color={tc.hintColor} />
            }
          </div>
          <div style={{ padding: "8px 10px" }}>
            <div style={{
              fontSize: 12, fontWeight: 600, color: tc.textColor,
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
  );
}

export function ForYouView({
  userId,
  currentTrack,
  onPlayTrack,
  onPlayAll,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

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

  // --- Smart Playlists ---
  const [smartPlaylists, setSmartPlaylists] = useState<SmartPlaylist[]>([]);
  const [smartExpanded, setSmartExpanded] = useState<string | null>(null);

  // --- Pull-to-refresh ---
  const [refreshing, setRefreshing] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const pullStartY = useRef(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const refreshAll = useCallback(async () => {
    setRefreshing(true);
    haptic("medium");
    try {
      const [w, t, tod] = await Promise.allSettled([
        fetchWave(userId, 10),
        fetchTrending(24, 15),
        fetchTrackOfDay(),
      ]);
      if (w.status === "fulfilled") setWaveTracks(w.value);
      if (t.status === "fulfilled") setTrendingTracks(t.value);
      if (tod.status === "fulfilled") setTodTrack(tod.value);
      if (currentTrack?.video_id) {
        try { const s = await fetchSimilar(currentTrack.video_id, 8); setSimilarTracks(s); } catch {}
      }
    } catch {}
    setRefreshing(false);
  }, [userId, currentTrack?.video_id]);

  const handlePullStart = useCallback((e: TouchEvent) => {
    const el = containerRef.current;
    if (el && el.scrollTop <= 0) {
      pullStartY.current = e.touches[0].clientY;
    } else {
      pullStartY.current = 0;
    }
  }, []);

  const handlePullMove = useCallback((e: TouchEvent) => {
    if (!pullStartY.current) return;
    const dy = e.touches[0].clientY - pullStartY.current;
    if (dy > 0) {
      setPullDistance(Math.min(80, dy * 0.4));
    }
  }, []);

  const handlePullEnd = useCallback(() => {
    if (pullDistance > 50 && !refreshing) {
      refreshAll();
    }
    setPullDistance(0);
    pullStartY.current = 0;
  }, [pullDistance, refreshing, refreshAll]);

  // --- AI Playlist state ---
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiTracks, setAiTracks] = useState<Track[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(false);

  // --- Fetch Track of Day + Smart Playlists ---
  useEffect(() => {
    fetchTrackOfDay().then(setTodTrack).catch(() => {});
    fetchSmartPlaylists().then(setSmartPlaylists).catch(() => {});
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

  return (
    <div
      ref={containerRef}
      onTouchStart={handlePullStart}
      onTouchMove={handlePullMove}
      onTouchEnd={handlePullEnd}
      style={{ paddingBottom: 24, touchAction: "pan-y" }}
    >
      {/* Pull-to-refresh indicator */}
      {(pullDistance > 0 || refreshing) && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: refreshing ? 40 : pullDistance,
          overflow: "hidden",
          transition: refreshing ? "height 0.3s ease" : "none",
          marginBottom: 8,
        }}>
          <div style={{
            opacity: refreshing ? 1 : Math.min(1, pullDistance / 50),
            transform: `rotate(${refreshing ? 0 : pullDistance * 4}deg)`,
            animation: refreshing ? "spinRefresh 0.8s linear infinite" : "none",
          }}>
            <IconSpinner size={20} color={tc.highlight} />
          </div>
          <style>{`@keyframes spinRefresh { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* ===== Page Header ===== */}
      <div style={{ marginBottom: 24 }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{
              fontSize: 22, fontWeight: 700, color: tc.textColor,
              letterSpacing: 0.3, marginBottom: 4,
            }}>
              Для тебя
            </div>
            <div style={{ fontSize: 13, color: tc.hintColor }}>
              Персональные рекомендации
            </div>
          </div>
          <button
            onClick={() => { if (!refreshing) refreshAll(); }}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              opacity: refreshing ? 0.5 : 0.7,
              padding: 8,
              color: tc.hintColor,
              fontSize: 18,
              animation: refreshing ? "spinRefresh 0.8s linear infinite" : "none",
            }}
            title="Обновить"
          >
            ↻
          </button>
        </div>
      </div>

      {/* ===== Track of the Day ===== */}
      {todTrack && (
        <div
          onClick={() => handlePlayTrack(todTrack)}
          style={{
            marginBottom: 20, padding: 16, borderRadius: 22,
            background: tc.activeBg,
            border: `1px solid ${tc.accentBorderAlpha}`,
            backdropFilter: "blur(16px)",
            cursor: "pointer",
            display: "flex", alignItems: "center", gap: 14,
            boxShadow: tc.glowShadow,
          }}
        >
          <div style={{
            width: 72, height: 72, borderRadius: 16, overflow: "hidden", flexShrink: 0,
            background: tc.coverPlaceholderBg,
            border: `1px solid ${tc.accentBorderAlpha}`,
          }}>
            {todTrack.cover_url
              ? <img src={todTrack.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><IconMusicNote size={28} color={tc.highlight} /></div>
            }
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 5, marginBottom: 4,
            }}>
              <IconStar size={14} color={tc.highlight} filled />
              <span style={{ fontSize: 10, fontWeight: 700, color: tc.highlight, textTransform: "uppercase", letterSpacing: 1.5 }}>
                Трек дня
              </span>
            </div>
            <div style={{
              fontSize: 15, fontWeight: 600, color: tc.textColor,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{todTrack.title}</div>
            <div style={{
              fontSize: 12, color: tc.hintColor,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{todTrack.artist}</div>
          </div>
          <div style={{
            width: 40, height: 40, borderRadius: 12,
            background: tc.accentGradient,
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
            boxShadow: tc.glowShadow,
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
        background: tc.cardBg, border: tc.cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <SectionHeading icon={<IconWave size={16} color={tc.highlight} />} title="Волна" tc={tc} />
          {waveTracks.length > 0 && (
            <button onClick={() => handlePlayAll(waveTracks)} style={{
              padding: "5px 12px", borderRadius: 12, border: "none",
              background: tc.accentGradient,
              color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 4,
            }}>
              <IconPlaySmall size={12} color="#fff" />
              Слушать все
            </button>
          )}
        </div>
        <HorizontalCards tracks={waveTracks} loading={waveLoading} error={waveError} tc={tc} onTrackClick={handlePlayTrack} />
      </div>

      {/* ===== Trending Section ===== */}
      <div style={{
        marginBottom: 28, padding: 16, borderRadius: 22,
        background: tc.cardBg, border: tc.cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <SectionHeading icon={<IconTrending size={16} color={tc.highlight} />} title="В тренде" tc={tc} />

        {trendingLoading ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <IconSpinner size={22} color={tc.hintColor} />
          </div>
        ) : trendingError ? (
          <div style={{ textAlign: "center", color: tc.hintColor, padding: 20, fontSize: 12 }}>
            Не удалось загрузить
          </div>
        ) : trendingTracks.length === 0 ? (
          <div style={{ textAlign: "center", color: tc.hintColor, padding: 20, fontSize: 12 }}>
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
                color: idx < 3 ? tc.highlight : tc.hintColor,
                display: "flex", alignItems: "center", justifyContent: "center", gap: 2,
              }}>
                {idx < 3 && <IconFire size={12} color={tc.highlight} />}
                {idx + 1}
              </div>
              <div style={{
                width: 48, height: 48, borderRadius: 10, overflow: "hidden", flexShrink: 0, marginRight: 12,
                background: tc.coverPlaceholderBg,
                border: `1px solid ${tc.accentBorderAlpha}`,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {t.cover_url
                  ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : <IconMusicNote size={20} color={tc.hintColor} />
                }
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 14, fontWeight: 500, color: tc.textColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{t.title}</div>
                <div style={{
                  fontSize: 12, color: tc.hintColor,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{t.artist}</div>
              </div>
              <div style={{
                width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <IconPlaySmall size={16} color={tc.hintColor} />
              </div>
            </div>
          ))
        )}
      </div>

      {/* ===== Similar Section (only if current track) ===== */}
      {currentTrack && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          backdropFilter: "blur(16px)",
        }}>
          <SectionHeading icon={<IconSimilar size={16} color={tc.highlight} />} title="Похожее" tc={tc} />
          <div style={{
            fontSize: 13, color: tc.textColor, marginBottom: 10, marginTop: -4,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            Похожее на <span style={{ fontWeight: 600, color: tc.highlight }}>{currentTrack.title}</span>
          </div>
          <HorizontalCards tracks={similarTracks} loading={similarLoading} error={similarError} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== AI Playlist Generator ===== */}
      <div style={{
        padding: 16, borderRadius: 22,
        background: tc.cardBg, border: tc.cardBorder,
        backdropFilter: "blur(16px)",
      }}>
        <SectionHeading icon={<IconRocket size={16} color={tc.highlight} />} title="AI Плейлист" tc={tc} />

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
              border: `1px solid ${tc.accentBorderAlpha}`,
              background: tc.isTequila ? "rgba(30, 18, 10, 0.6)" : "rgba(255,255,255,0.05)",
              color: tc.textColor, outline: "none", boxSizing: "border-box",
              opacity: aiLoading ? 0.5 : 1,
            }}
          />
          <button
            onClick={handleGenerateAi}
            disabled={aiLoading || !aiPrompt.trim()}
            style={{
              padding: "10px 16px", borderRadius: 14, border: "none",
              background: tc.accentGradient,
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
                background: tc.accentGradient,
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
                  background: tc.coverPlaceholderBg,
                  border: `1px solid ${tc.accentBorderAlpha}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {t.cover_url
                    ? <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    : <IconMusicNote size={20} color={tc.hintColor} />
                  }
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 14, fontWeight: 500, color: tc.textColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.title}</div>
                  <div style={{
                    fontSize: 12, color: tc.hintColor,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{t.artist}</div>
                </div>
                <div style={{
                  width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <IconPlaySmall size={16} color={tc.hintColor} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ===== Smart Playlists Section ===== */}
      {smartPlaylists.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <SectionHeading icon={<IconRocket size={16} color={tc.highlight} />} title="Smart Playlists" tc={tc} />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {smartPlaylists.map((sp) => {
              const isExpanded = smartExpanded === sp.id;
              const iconMap: Record<string, any> = {
                fire: <IconFire size={18} color="#fff" />,
                heart: <IconHeart size={18} color="#fff" filled />,
                discover: <IconDiscover size={18} color="#fff" />,
                moon: <IconMoon size={18} color="#fff" />,
              };
              const gradientMap: Record<string, string> = {
                fire: "linear-gradient(135deg, #ff4444, #ff8800)",
                heart: "linear-gradient(135deg, #ee2244, #ff66aa)",
                discover: "linear-gradient(135deg, #22cc66, #00cccc)",
                moon: "linear-gradient(135deg, #1a1a5e, #6633aa)",
              };
              return (
                <div key={sp.id} style={{
                  borderRadius: 16, border: tc.cardBorder,
                  background: tc.cardBg, overflow: "hidden",
                  backdropFilter: "blur(16px)",
                }}>
                  <div
                    onClick={() => {
                      haptic("light");
                      setSmartExpanded(isExpanded ? null : sp.id);
                    }}
                    style={{
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "12px 14px", cursor: "pointer",
                    }}
                  >
                    <div style={{
                      width: 42, height: 42, borderRadius: 12, flexShrink: 0,
                      background: gradientMap[sp.icon] || tc.accentGradient,
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      {iconMap[sp.icon] || <IconMusicNote size={18} color="#fff" />}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: tc.textColor }}>{sp.name}</div>
                      <div style={{ fontSize: 12, color: tc.hintColor }}>{sp.description} &middot; {sp.tracks.length} tracks</div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        haptic("medium");
                        handlePlayAll(sp.tracks);
                      }}
                      style={{
                        width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                        background: tc.activeBg, border: "none",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        cursor: "pointer",
                      }}
                    >
                      <IconPlaySmall size={14} color={tc.highlight} />
                    </button>
                  </div>
                  {isExpanded && (
                    <div style={{ padding: "0 8px 8px" }}>
                      {sp.tracks.slice(0, 10).map((t, i) => (
                        <div
                          key={t.video_id}
                          onClick={() => handlePlayTrack(t)}
                          style={{
                            display: "flex", alignItems: "center", gap: 10,
                            padding: "8px 8px", borderRadius: 10,
                            cursor: "pointer",
                          }}
                        >
                          <span style={{ fontSize: 12, fontWeight: 700, color: tc.hintColor, width: 20, textAlign: "center" }}>{i + 1}</span>
                          <div style={{
                            width: 36, height: 36, borderRadius: 8, overflow: "hidden", flexShrink: 0,
                            background: tc.coverPlaceholderBg,
                          }}>
                            {t.cover_url ? (
                              <img src={t.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                            ) : (
                              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <IconMusicNote size={14} color={tc.hintColor} />
                              </div>
                            )}
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 13, fontWeight: 500, color: tc.textColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</div>
                            <div style={{ fontSize: 11, color: tc.hintColor }}>{t.artist}</div>
                          </div>
                          <IconPlaySmall size={12} color={tc.hintColor} />
                        </div>
                      ))}
                      {sp.tracks.length > 10 && (
                        <div style={{ textAlign: "center", padding: "6px 0", fontSize: 12, color: tc.hintColor }}>
                          +{sp.tracks.length - 10} more
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
