import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import { memo } from "preact/compat";
import type { JSX } from "preact";
import { fetchWave, fetchTrending, fetchSimilar, generateAiPlaylist, fetchTrackOfDay, fetchSmartPlaylists, fetchLastfmTagTop, fetchLastfmGeoTop, fetchLastfmChart, fetchLastfmNewReleases, fetchLastfmArtistMix, fetchLastfmArtistInfo, fetchLastfmPersonalMix, fetchLastfmWeeklyDiscovery, type Track, type SmartPlaylist, type LastfmArtistInfo } from "../api";
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

export const ForYouView = memo(function ForYouView({
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

  // --- Last.fm Chart ---
  const [chartTracks, setChartTracks] = useState<Track[]>([]);
  const [chartLoading, setChartLoading] = useState(true);

  // --- Last.fm Geo Top ---
  const [geoTracks, setGeoTracks] = useState<Track[]>([]);
  const [geoLoading, setGeoLoading] = useState(true);
  const [geoCountry, setGeoCountry] = useState("Russian Federation");

  // --- Last.fm Genre/Tag ---
  const [tagTracks, setTagTracks] = useState<Track[]>([]);
  const [tagLoading, setTagLoading] = useState(false);
  const [activeTag, setActiveTag] = useState("");

  // --- Last.fm New Releases (from favorites) ---
  const [newRelTracks, setNewRelTracks] = useState<Track[]>([]);
  const [newRelArtists, setNewRelArtists] = useState<string[]>([]);
  const [newRelLoading, setNewRelLoading] = useState(true);

  // --- Last.fm Artist Discovery ---
  const [artistMixTracks, setArtistMixTracks] = useState<Track[]>([]);
  const [artistMixLoading, setArtistMixLoading] = useState(false);
  const [artistMixName, setArtistMixName] = useState("");

  // --- Last.fm Artist Info ---
  const [artistInfo, setArtistInfo] = useState<LastfmArtistInfo | null>(null);

  // --- Personal Mix (from Last.fm) ---
  const [personalMixTracks, setPersonalMixTracks] = useState<Track[]>([]);
  const [personalMixArtists, setPersonalMixArtists] = useState<string[]>([]);
  const [personalMixLoading, setPersonalMixLoading] = useState(true);

  // --- Weekly Discovery ---
  const [weeklyTracks, setWeeklyTracks] = useState<Track[]>([]);
  const [weeklyLoading, setWeeklyLoading] = useState(true);

  // --- Bio expand ---
  const [bioExpanded, setBioExpanded] = useState(false);

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

  // --- Fetch all data (batched) ---
  useEffect(() => {
    let cancelled = false;
    setWaveLoading(true);
    setTrendingLoading(true);
    setChartLoading(true);
    setGeoLoading(true);
    setNewRelLoading(true);
    setPersonalMixLoading(true);
    setWeeklyLoading(true);
    if (currentTrack?.video_id) setSimilarLoading(true);

    Promise.allSettled([
      fetchWave(userId, 10),
      fetchTrending(24, 15),
      fetchTrackOfDay(),
      fetchSmartPlaylists(),
      currentTrack?.video_id ? fetchSimilar(currentTrack.video_id, 8) : Promise.resolve([] as Track[]),
      fetchLastfmChart(15),
      fetchLastfmGeoTop(geoCountry, 15),
      fetchLastfmNewReleases(15),
      fetchLastfmPersonalMix(15),
      fetchLastfmWeeklyDiscovery(15),
    ]).then(([wave, trending, tod, smart, similar, chart, geo, newRel, personalMix, weekly]) => {
      if (cancelled) return;
      setWaveTracks(wave.status === "fulfilled" ? wave.value : []);
      setWaveError(wave.status === "rejected");
      setWaveLoading(false);
      setTrendingTracks(trending.status === "fulfilled" ? trending.value : []);
      setTrendingError(trending.status === "rejected");
      setTrendingLoading(false);
      if (tod.status === "fulfilled") setTodTrack(tod.value);
      if (smart.status === "fulfilled") setSmartPlaylists(smart.value);
      setSimilarTracks(similar.status === "fulfilled" ? similar.value : []);
      setSimilarError(similar.status === "rejected" && !!currentTrack?.video_id);
      setSimilarLoading(false);
      setChartTracks(chart.status === "fulfilled" ? chart.value : []);
      setChartLoading(false);
      setGeoTracks(geo.status === "fulfilled" ? geo.value : []);
      setGeoLoading(false);
      if (newRel.status === "fulfilled") {
        setNewRelTracks(newRel.value.tracks);
        setNewRelArtists(newRel.value.artists);
      }
      setNewRelLoading(false);
      if (personalMix.status === "fulfilled") {
        setPersonalMixTracks(personalMix.value.tracks);
        setPersonalMixArtists(personalMix.value.seedArtists);
      }
      setPersonalMixLoading(false);
      setWeeklyTracks(weekly.status === "fulfilled" ? weekly.value : []);
      setWeeklyLoading(false);
    });

    // Load artist info + artist mix if current track is playing
    if (currentTrack?.artist) {
      fetchLastfmArtistInfo(currentTrack.artist).then(info => {
        if (!cancelled && info) setArtistInfo(info);
      }).catch(() => {});
      setArtistMixLoading(true);
      setArtistMixName(currentTrack.artist);
      fetchLastfmArtistMix(currentTrack.artist, 10).then(tracks => {
        if (!cancelled) { setArtistMixTracks(tracks); setArtistMixLoading(false); }
      }).catch(() => { if (!cancelled) setArtistMixLoading(false); });
    }

    return () => { cancelled = true; };
  }, [userId, currentTrack?.video_id]);

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
            transform: "translateZ(0)",
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
        transform: "translateZ(0)",
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

      {/* ===== Personal Mix (Last.fm deep discovery) ===== */}
      {(personalMixTracks.length > 0 || personalMixLoading) && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: `linear-gradient(135deg, ${tc.highlight}15, ${tc.highlight}05)`,
          border: `1px solid ${tc.highlight}25`,
          transform: "translateZ(0)",
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <SectionHeading icon={<IconStar size={16} color={tc.highlight} filled />} title="Твой микс" tc={tc} />
            {personalMixTracks.length > 0 && (
              <button onClick={() => handlePlayAll(personalMixTracks)} style={{
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
          {personalMixArtists.length > 0 && (
            <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 8, marginTop: -4 }}>
              На основе: {personalMixArtists.join(", ")}
            </div>
          )}
          <HorizontalCards tracks={personalMixTracks} loading={personalMixLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== Trending Section ===== */}
      <div style={{
        marginBottom: 28, padding: 16, borderRadius: 22,
        background: tc.cardBg, border: tc.cardBorder,
        transform: "translateZ(0)",
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
          transform: "translateZ(0)",
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

      {/* ===== Weekly Discovery ===== */}
      {(weeklyTracks.length > 0 || weeklyLoading) && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          transform: "translateZ(0)",
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <SectionHeading icon={<IconDiscover size={16} color={tc.highlight} />} title="Открытия недели" tc={tc} />
            {weeklyTracks.length > 0 && (
              <button onClick={() => handlePlayAll(weeklyTracks)} style={{
                padding: "5px 12px", borderRadius: 12, border: "none",
                background: tc.accentGradient,
                color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}>
                <IconPlaySmall size={12} color="#fff" />
                Слушать
              </button>
            )}
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 8, marginTop: -4 }}>
            Микс из чартов, трендов и жанров
          </div>
          <HorizontalCards tracks={weeklyTracks} loading={weeklyLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== Artist Info Card (if playing) ===== */}
      {artistInfo && currentTrack && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          transform: "translateZ(0)",
        }}>
          <SectionHeading icon={<IconStar size={16} color={tc.highlight} filled />} title="Об артисте" tc={tc} />
          <div style={{ marginBottom: 10 }}>
            {/* Artist header with photo */}
            <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 12 }}>
              {artistInfo.image ? (
                <img src={artistInfo.image} alt={artistInfo.name} style={{
                  width: 72, height: 72, borderRadius: 18, objectFit: "cover",
                  border: `2px solid ${tc.highlight}40`,
                  flexShrink: 0,
                }} />
              ) : (
                <div style={{
                  width: 72, height: 72, borderRadius: 18, flexShrink: 0,
                  background: `linear-gradient(135deg, ${tc.highlight}30, ${tc.highlight}10)`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  border: `2px solid ${tc.highlight}40`,
                }}>
                  <IconMusicNote size={28} color={tc.highlight} />
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: tc.textColor, marginBottom: 6 }}>
                  {artistInfo.name}
                </div>
                <div style={{ display: "flex", gap: 16 }}>
                  <div style={{ fontSize: 11, color: tc.hintColor }}>
                    <span style={{ fontWeight: 700, color: tc.textColor, fontSize: 14 }}>
                      {artistInfo.listeners > 1000000 ? `${(artistInfo.listeners / 1000000).toFixed(1)}M` : artistInfo.listeners > 1000 ? `${(artistInfo.listeners / 1000).toFixed(0)}K` : artistInfo.listeners}
                    </span> слушателей
                  </div>
                  <div style={{ fontSize: 11, color: tc.hintColor }}>
                    <span style={{ fontWeight: 700, color: tc.textColor, fontSize: 14 }}>
                      {artistInfo.playcount > 1000000 ? `${(artistInfo.playcount / 1000000).toFixed(0)}M` : artistInfo.playcount > 1000 ? `${(artistInfo.playcount / 1000).toFixed(0)}K` : artistInfo.playcount}
                    </span> прослушиваний
                  </div>
                </div>
              </div>
            </div>
            {/* Bio — expandable */}
            {artistInfo.bio && (
              <div style={{ marginBottom: 12 }}>
                <div
                  onClick={() => setBioExpanded(!bioExpanded)}
                  style={{
                    fontSize: 12, color: tc.hintColor, lineHeight: 1.6,
                    maxHeight: bioExpanded ? "none" : 54,
                    overflow: "hidden",
                    cursor: "pointer",
                    position: "relative",
                  }}
                >
                  {artistInfo.bio}
                  {!bioExpanded && artistInfo.bio.length > 120 && (
                    <div style={{
                      position: "absolute", bottom: 0, left: 0, right: 0, height: 28,
                      background: `linear-gradient(transparent, ${tc.cardBgSolid || "rgba(30,30,30,1)"})`,
                    }} />
                  )}
                </div>
                {artistInfo.bio.length > 120 && (
                  <button onClick={() => setBioExpanded(!bioExpanded)} style={{
                    background: "none", border: "none", padding: "4px 0", cursor: "pointer",
                    fontSize: 11, fontWeight: 600, color: tc.highlight,
                  }}>
                    {bioExpanded ? "Свернуть ▲" : "Читать далее ▼"}
                  </button>
                )}
              </div>
            )}
            {artistInfo.tags.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: tc.hintColor, marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>Жанры</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {artistInfo.tags.slice(0, 5).map(tag => (
                    <span key={tag} onClick={() => {
                      haptic("light");
                      setActiveTag(tag);
                      setTagLoading(true);
                      fetchLastfmTagTop(tag, 15).then(t => { setTagTracks(t); setTagLoading(false); }).catch(() => setTagLoading(false));
                    }} style={{
                      padding: "4px 10px", borderRadius: 10, fontSize: 11, cursor: "pointer",
                      background: `${tc.highlight}20`, color: tc.highlight, border: `1px solid ${tc.highlight}30`,
                    }}>
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {artistInfo.similar && artistInfo.similar.length > 0 && (
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: tc.hintColor, marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>Похожие артисты</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {artistInfo.similar.map(name => (
                    <span key={name} onClick={() => {
                      haptic("medium");
                      setArtistMixName(name);
                      setArtistMixLoading(true);
                      fetchLastfmArtistMix(name, 10).then(tracks => {
                        setArtistMixTracks(tracks);
                        setArtistMixLoading(false);
                      }).catch(() => setArtistMixLoading(false));
                      fetchLastfmArtistInfo(name).then(info => {
                        if (info) setArtistInfo(info);
                      }).catch(() => {});
                    }} style={{
                      padding: "5px 12px", borderRadius: 12, fontSize: 12, fontWeight: 600,
                      cursor: "pointer",
                      background: tc.activeBg,
                      color: tc.textColor,
                      border: `1px solid ${tc.accentBorderAlpha}`,
                      transition: "all 0.15s ease",
                    }}>
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===== Artist Discovery (similar artists' tracks) ===== */}
      {artistMixName && (artistMixTracks.length > 0 || artistMixLoading) && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          transform: "translateZ(0)",
        }}>
          <SectionHeading icon={<IconDiscover size={16} color={tc.highlight} />} title="Откройте для себя" tc={tc} />
          <div style={{
            fontSize: 13, color: tc.textColor, marginBottom: 10, marginTop: -4,
          }}>
            Если вам нравится <span style={{ fontWeight: 600, color: tc.highlight }}>{artistMixName}</span>
          </div>
          <HorizontalCards tracks={artistMixTracks} loading={artistMixLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== New from Favorites ===== */}
      {(newRelTracks.length > 0 || newRelLoading) && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          transform: "translateZ(0)",
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <SectionHeading icon={<IconHeart size={16} color={tc.highlight} filled />} title="От любимых" tc={tc} />
            {newRelTracks.length > 0 && (
              <button onClick={() => handlePlayAll(newRelTracks)} style={{
                padding: "5px 12px", borderRadius: 12, border: "none",
                background: tc.accentGradient,
                color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}>
                <IconPlaySmall size={12} color="#fff" />
                Слушать
              </button>
            )}
          </div>
          {newRelArtists.length > 0 && (
            <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 8, marginTop: -4 }}>
              {newRelArtists.slice(0, 3).join(", ")}{newRelArtists.length > 3 ? ` и ещё ${newRelArtists.length - 3}` : ""}
            </div>
          )}
          <HorizontalCards tracks={newRelTracks} loading={newRelLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== Last.fm Global Chart ===== */}
      {(chartTracks.length > 0 || chartLoading) && (
        <div style={{
          marginBottom: 28, padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
          transform: "translateZ(0)",
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <SectionHeading icon={<IconChart size={16} color={tc.highlight} />} title="Мировой чарт" tc={tc} />
            {chartTracks.length > 0 && (
              <button onClick={() => handlePlayAll(chartTracks)} style={{
                padding: "5px 12px", borderRadius: 12, border: "none",
                background: tc.accentGradient,
                color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}>
                <IconPlaySmall size={12} color="#fff" />
                Слушать
              </button>
            )}
          </div>
          <div style={{ fontSize: 11, color: tc.hintColor, marginBottom: 8, marginTop: -4 }}>
            На основе 20+ лет данных Last.fm
          </div>
          <HorizontalCards tracks={chartTracks} loading={chartLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      )}

      {/* ===== Geo Trending — Modern Flag Cards ===== */}
      <div style={{
        marginBottom: 28,
        transform: "translateZ(0)",
      }}>
        <div style={{ padding: "0 0 10px 0" }}>
          <SectionHeading icon={<IconTrending size={16} color={tc.highlight} />} title="Популярное в мире" tc={tc} />
        </div>
        {/* Horizontal scrollable flag cards */}
        <div style={{
          display: "flex", gap: 12, overflowX: "auto",
          padding: "4px 0 14px 0", scrollbarWidth: "none",
          WebkitOverflowScrolling: "touch",
          scrollSnapType: "x mandatory",
        }}>
          {[
            { code: "Russian Federation", flag: "🇷🇺", label: "Россия", grad: "linear-gradient(135deg, #1565c0, #e53935)" },
            { code: "Kazakhstan", flag: "🇰🇿", label: "Казахстан", grad: "linear-gradient(135deg, #00bcd4, #ffd600)" },
            { code: "Kyrgyzstan", flag: "🇰🇬", label: "Кыргызстан", grad: "linear-gradient(135deg, #e53935, #ffd600)" },
            { code: "United States", flag: "🇺🇸", label: "США", grad: "linear-gradient(135deg, #1565c0, #b71c1c)" },
            { code: "United Kingdom", flag: "🇬🇧", label: "UK", grad: "linear-gradient(135deg, #0d47a1, #c62828)" },
            { code: "Germany", flag: "🇩🇪", label: "Германия", grad: "linear-gradient(135deg, #212121, #ffc107)" },
            { code: "Turkey", flag: "🇹🇷", label: "Турция", grad: "linear-gradient(135deg, #c62828, #e53935)" },
            { code: "France", flag: "🇫🇷", label: "Франция", grad: "linear-gradient(135deg, #1565c0, #c62828)" },
            { code: "Brazil", flag: "🇧🇷", label: "Бразилия", grad: "linear-gradient(135deg, #2e7d32, #ffd600)" },
            { code: "Japan", flag: "🇯🇵", label: "Япония", grad: "linear-gradient(135deg, #e8eaf6, #c62828)" },
            { code: "Korea, Republic of", flag: "🇰🇷", label: "Корея", grad: "linear-gradient(135deg, #1565c0, #c62828)" },
            { code: "India", flag: "🇮🇳", label: "Индия", grad: "linear-gradient(135deg, #ff9800, #2e7d32)" },
          ].map(({ code, flag, label, grad }) => (
            <button key={code} onClick={() => {
              haptic("medium");
              setGeoCountry(code);
              setGeoLoading(true);
              fetchLastfmGeoTop(code, 15).then(t => { setGeoTracks(t); setGeoLoading(false); }).catch(() => setGeoLoading(false));
            }} style={{
              minWidth: 88, height: 100, borderRadius: 20, border: "none",
              background: geoCountry === code ? grad : tc.cardBg,
              cursor: "pointer", flexShrink: 0,
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 6,
              scrollSnapAlign: "start",
              boxShadow: geoCountry === code ? `0 4px 20px ${tc.highlight}30` : "none",
              border: geoCountry === code ? `2px solid ${tc.highlight}` : tc.cardBorder,
              transition: "all 0.2s ease",
              position: "relative",
              overflow: "hidden",
            }}>
              <span style={{ fontSize: 36, lineHeight: 1, filter: geoCountry === code ? "none" : "grayscale(0.3)" }}>
                {flag}
              </span>
              <span style={{
                fontSize: 11, fontWeight: 700,
                color: geoCountry === code ? "#fff" : tc.hintColor,
                letterSpacing: 0.3,
              }}>
                {label}
              </span>
              {geoCountry === code && (
                <div style={{
                  position: "absolute", bottom: 0, left: 0, right: 0, height: 3,
                  background: "#fff", borderRadius: "3px 3px 0 0", opacity: 0.6,
                }} />
              )}
            </button>
          ))}
        </div>
        {/* Tracks for selected country */}
        <div style={{
          padding: 16, borderRadius: 22,
          background: tc.cardBg, border: tc.cardBorder,
        }}>
          <HorizontalCards tracks={geoTracks} loading={geoLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
        </div>
      </div>

      {/* ===== Genre Discovery (tag-based) ===== */}
      <div style={{
        marginBottom: 28, padding: 16, borderRadius: 22,
        background: tc.cardBg, border: tc.cardBorder,
        transform: "translateZ(0)",
      }}>
        <SectionHeading icon={<IconDiscover size={16} color={tc.highlight} />} title="Жанры" tc={tc} />
        <div style={{
          display: "flex", gap: 8, flexWrap: "wrap", marginBottom: tagTracks.length > 0 || tagLoading ? 12 : 0,
        }}>
          {[
            { tag: "indie", label: "Indie", grad: "linear-gradient(135deg, #43a047, #66bb6a)" },
            { tag: "hip-hop", label: "Hip-Hop", grad: "linear-gradient(135deg, #ff6f00, #ffa726)" },
            { tag: "electronic", label: "Electronic", grad: "linear-gradient(135deg, #7c4dff, #b388ff)" },
            { tag: "rock", label: "Rock", grad: "linear-gradient(135deg, #d32f2f, #ef5350)" },
            { tag: "jazz", label: "Jazz", grad: "linear-gradient(135deg, #1565c0, #42a5f5)" },
            { tag: "classical", label: "Classical", grad: "linear-gradient(135deg, #5d4037, #8d6e63)" },
            { tag: "r&b", label: "R&B", grad: "linear-gradient(135deg, #ad1457, #ec407a)" },
            { tag: "pop", label: "Pop", grad: "linear-gradient(135deg, #00bcd4, #26c6da)" },
            { tag: "metal", label: "Metal", grad: "linear-gradient(135deg, #212121, #616161)" },
            { tag: "lo-fi", label: "Lo-Fi", grad: "linear-gradient(135deg, #78909c, #b0bec5)" },
            { tag: "soul", label: "Soul", grad: "linear-gradient(135deg, #e65100, #ff9800)" },
            { tag: "ambient", label: "Ambient", grad: "linear-gradient(135deg, #004d40, #26a69a)" },
          ].map(({ tag, label, grad }) => (
            <button key={tag} onClick={() => {
              haptic("medium");
              setActiveTag(tag);
              setTagLoading(true);
              setTagTracks([]);
              fetchLastfmTagTop(tag, 15).then(t => { setTagTracks(t); setTagLoading(false); }).catch(() => setTagLoading(false));
            }} style={{
              padding: "7px 14px", borderRadius: 12, border: "none",
              background: activeTag === tag ? grad : `${tc.highlight}15`,
              color: activeTag === tag ? "#fff" : tc.hintColor,
              fontSize: 11, fontWeight: 600, cursor: "pointer",
              transition: "all 0.2s ease",
            }}>
              {label}
            </button>
          ))}
        </div>
        {(tagLoading || tagTracks.length > 0) && (
          <>
            {activeTag && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <div style={{ fontSize: 13, color: tc.textColor }}>
                  Лучшее в <span style={{ fontWeight: 600, color: tc.highlight }}>{activeTag}</span>
                </div>
                {tagTracks.length > 0 && (
                  <button onClick={() => handlePlayAll(tagTracks)} style={{
                    padding: "4px 10px", borderRadius: 10, border: "none",
                    background: tc.accentGradient,
                    color: "#fff", fontSize: 10, fontWeight: 600, cursor: "pointer",
                    display: "flex", alignItems: "center", gap: 3,
                  }}>
                    <IconPlaySmall size={10} color="#fff" />
                    Все
                  </button>
                )}
              </div>
            )}
            <HorizontalCards tracks={tagTracks} loading={tagLoading} error={false} tc={tc} onTrackClick={handlePlayTrack} />
          </>
        )}
      </div>

      {/* ===== AI Playlist Generator ===== */}
      <div style={{
        padding: 16, borderRadius: 22,
        background: tc.cardBg, border: tc.cardBorder,
        transform: "translateZ(0)",
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
                  transform: "translateZ(0)",
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
});
