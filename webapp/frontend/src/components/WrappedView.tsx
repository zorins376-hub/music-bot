import { useState, useEffect, useRef } from "preact/hooks";
import { fetchWrapped, type WrappedData, type Track } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconSpinner, IconFire, IconMusicNote, IconCrown, IconHeadphones,
  IconPlaySmall, IconChart, IconMoon, IconRocket, IconStar, IconHeart,
} from "./Icons";

interface Props {
  userId: number;
  onPlayTrack: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

const PERSONALITIES: Record<string, { label: string; emoji: string; desc: string }> = {
  Explorer:         { label: "Explorer", emoji: "compass", desc: "You love discovering new artists and sounds" },
  Loyalist:         { label: "Loyalist", emoji: "crown", desc: "You know what you love and stick with it" },
  Eclectic:         { label: "Eclectic", emoji: "rainbow", desc: "Your taste spans across genres" },
  "Marathon Runner": { label: "Marathon Runner", emoji: "rocket", desc: "Music is your constant companion" },
  "Night Owl":       { label: "Night Owl", emoji: "moon", desc: "The night is when you truly listen" },
};

function formatTime(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function formatTimeRu(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const h = Math.floor(seconds / 3600);
  return `${h} ${h === 1 ? "hour" : "hours"}`;
}

export function WrappedView({
  userId,
  onPlayTrack,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [data, setData] = useState<WrappedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [slideAnim, setSlideAnim] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(false);
    fetchWrapped()
      .then((d) => {
        if (d.error && d.total_plays === 0) {
          setError(true);
        } else {
          setData(d);
        }
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [userId]);

  // Inject animations
  useEffect(() => {
    if (document.getElementById("wrapped-anims")) return;
    const s = document.createElement("style");
    s.id = "wrapped-anims";
    s.textContent = `
      @keyframes wrp-fadeUp { 0% { opacity:0; transform:translateY(30px); } 100% { opacity:1; transform:translateY(0); } }
      @keyframes wrp-scaleIn { 0% { opacity:0; transform:scale(0.6); } 100% { opacity:1; transform:scale(1); } }
      @keyframes wrp-countUp { 0% { opacity:0; transform:translateY(20px) scale(0.8); } 100% { opacity:1; transform:translateY(0) scale(1); } }
      @keyframes wrp-slideLeft { 0% { opacity:0; transform:translateX(60px); } 100% { opacity:1; transform:translateX(0); } }
      @keyframes wrp-slideRight { 0% { opacity:0; transform:translateX(-60px); } 100% { opacity:1; transform:translateX(0); } }
      @keyframes wrp-glow { 0%,100% { filter:brightness(1); } 50% { filter:brightness(1.3); } }
      @keyframes wrp-barGrow { 0% { width:0%; } 100% { width:var(--bar-w); } }
    `;
    document.head.appendChild(s);
  }, []);

  const goSlide = (dir: number) => {
    haptic("light");
    setSlideAnim(dir > 0 ? "wrp-slideLeft" : "wrp-slideRight");
    setTimeout(() => {
      setCurrentSlide((p) => Math.max(0, Math.min(p + dir, totalSlides - 1)));
      setSlideAnim("");
    }, 50);
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <IconSpinner size={32} color={tc.highlight} />
        <div style={{ fontSize: 14, color: tc.hintColor, marginTop: 16 }}>Preparing your recap...</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>{"<3"}</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: tc.textColor }}>Listen more to unlock your recap!</div>
        <div style={{ fontSize: 13, color: tc.hintColor, marginTop: 6 }}>Start playing tracks and come back later</div>
      </div>
    );
  }

  const personality = PERSONALITIES[data.personality] || PERSONALITIES.Explorer;
  const totalSlides = 6;

  // ── Slide components ──
  const cardBase: Record<string, string | number> = {
    borderRadius: 24,
    padding: "32px 20px",
    minHeight: 380,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    position: "relative",
    overflow: "hidden",
  };

  const slides = [
    // Slide 0: Intro with big number
    () => (
      <div style={{
        ...cardBase,
        background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
        border: tc.cardBorder,
      }}>
        <div style={{
          fontSize: 13, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
          color: tc.highlight, marginBottom: 24,
          animation: "wrp-fadeUp 0.6s ease-out",
        }}>
          YOUR MUSIC RECAP
        </div>
        <div style={{
          fontSize: 72, fontWeight: 800, color: tc.textColor,
          lineHeight: 1, marginBottom: 8,
          animation: "wrp-countUp 0.8s ease-out 0.2s both",
          background: tc.accentGradient, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
        }}>
          {data.total_plays.toLocaleString()}
        </div>
        <div style={{
          fontSize: 18, fontWeight: 600, color: tc.textColor,
          animation: "wrp-fadeUp 0.6s ease-out 0.4s both",
        }}>
          tracks played
        </div>
        <div style={{
          fontSize: 14, color: tc.hintColor, marginTop: 12,
          animation: "wrp-fadeUp 0.6s ease-out 0.6s both",
        }}>
          {formatTime(data.total_time)} of pure music
        </div>
        <div style={{
          display: "flex", gap: 20, marginTop: 32,
          animation: "wrp-fadeUp 0.6s ease-out 0.8s both",
        }}>
          <StatBubble label="Artists" value={data.unique_artists} tc={tc} icon={<IconHeadphones size={14} color={tc.highlight} />} />
          <StatBubble label="Tracks" value={data.unique_tracks} tc={tc} icon={<IconMusicNote size={14} color={tc.highlight} />} />
          <StatBubble label="Favorites" value={data.total_favorites} tc={tc} icon={<IconHeart size={14} color="#ff4081" filled />} />
        </div>
      </div>
    ),

    // Slide 1: Top Artist
    () => {
      const artist = data.top_artists[0];
      if (!artist) return <EmptySlide tc={tc} text="No top artist yet" />;
      return (
        <div style={{
          ...cardBase,
          background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
          border: tc.cardBorder,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
            color: tc.hintColor, marginBottom: 20,
            animation: "wrp-fadeUp 0.5s ease-out",
          }}>
            #1 ARTIST
          </div>
          <div style={{
            width: 100, height: 100, borderRadius: 50,
            background: tc.accentGradient,
            display: "flex", alignItems: "center", justifyContent: "center",
            marginBottom: 20, boxShadow: tc.glowShadow,
            animation: "wrp-scaleIn 0.6s ease-out 0.2s both",
          }}>
            <IconCrown size={40} color="#fff" />
          </div>
          <div style={{
            fontSize: 28, fontWeight: 800, color: tc.textColor,
            animation: "wrp-fadeUp 0.6s ease-out 0.4s both",
            maxWidth: "100%",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {artist.name}
          </div>
          <div style={{
            fontSize: 15, color: tc.highlight, marginTop: 8, fontWeight: 600,
            animation: "wrp-fadeUp 0.5s ease-out 0.6s both",
          }}>
            {artist.count} plays
          </div>
          {data.top_artists.length > 1 && (
            <div style={{
              marginTop: 24, width: "100%",
              animation: "wrp-fadeUp 0.5s ease-out 0.8s both",
            }}>
              {data.top_artists.slice(1, 6).map((a, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 12px", borderRadius: 12,
                  marginBottom: 4,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: tc.hintColor, width: 24 }}>#{i + 2}</span>
                  <span style={{ fontSize: 14, fontWeight: 500, color: tc.textColor, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                  <span style={{ fontSize: 12, color: tc.hintColor }}>{a.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    },

    // Slide 2: Top Track
    () => {
      if (!data.top_track) return <EmptySlide tc={tc} text="No top track yet" />;
      return (
        <div style={{
          ...cardBase,
          background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
          border: tc.cardBorder,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
            color: tc.hintColor, marginBottom: 20,
            animation: "wrp-fadeUp 0.5s ease-out",
          }}>
            MOST PLAYED TRACK
          </div>
          <div style={{
            width: 140, height: 140, borderRadius: 20,
            overflow: "hidden", marginBottom: 20,
            boxShadow: `${tc.glowShadow}, 0 20px 60px rgba(0,0,0,0.4)`,
            animation: "wrp-scaleIn 0.6s ease-out 0.2s both",
          }}>
            {data.top_track.cover_url ? (
              <img src={data.top_track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", background: tc.activeBg, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <IconMusicNote size={48} color={tc.highlight} />
              </div>
            )}
          </div>
          <div style={{
            fontSize: 22, fontWeight: 800, color: tc.textColor,
            animation: "wrp-fadeUp 0.6s ease-out 0.4s both",
            maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {data.top_track.title}
          </div>
          <div style={{
            fontSize: 15, color: tc.hintColor, marginTop: 4,
            animation: "wrp-fadeUp 0.5s ease-out 0.5s both",
          }}>
            {data.top_track.artist}
          </div>
          <div style={{
            fontSize: 16, fontWeight: 700, color: tc.highlight, marginTop: 12,
            animation: "wrp-fadeUp 0.5s ease-out 0.6s both",
          }}>
            Played {data.top_track.play_count} times
          </div>
          {data.top_track && (
            <button
              onClick={() => {
                haptic("medium");
                onPlayTrack({
                  video_id: data.top_track!.video_id,
                  title: data.top_track!.title,
                  artist: data.top_track!.artist,
                  duration: 0, duration_fmt: "0:00", source: "db",
                  cover_url: data.top_track!.cover_url,
                });
              }}
              style={{
                marginTop: 20, padding: "12px 28px", borderRadius: 14,
                border: "none", background: tc.accentGradient, color: "#fff",
                fontSize: 14, fontWeight: 700, cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 8,
                boxShadow: tc.glowShadow,
                animation: "wrp-fadeUp 0.5s ease-out 0.7s both",
              }}
            >
              <IconPlaySmall size={14} color="#fff" /> Play now
            </button>
          )}
        </div>
      );
    },

    // Slide 3: Genres
    () => {
      if (data.top_genres.length === 0) return <EmptySlide tc={tc} text="No genre data yet" />;
      const maxCount = data.top_genres[0]?.count || 1;
      return (
        <div style={{
          ...cardBase,
          background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
          border: tc.cardBorder,
          justifyContent: "flex-start", paddingTop: 28,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
            color: tc.hintColor, marginBottom: 24,
            animation: "wrp-fadeUp 0.5s ease-out",
          }}>
            YOUR GENRES
          </div>
          <div style={{ width: "100%" }}>
            {data.top_genres.map((g, i) => {
              const pct = Math.round((g.count / maxCount) * 100);
              return (
                <div key={i} style={{
                  marginBottom: 14,
                  animation: `wrp-fadeUp 0.5s ease-out ${0.2 + i * 0.15}s both`,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 15, fontWeight: 600, color: tc.textColor }}>{g.name}</span>
                    <span style={{ fontSize: 13, color: tc.hintColor }}>{g.count} plays</span>
                  </div>
                  <div style={{
                    width: "100%", height: 8, borderRadius: 4,
                    background: "rgba(255,255,255,0.06)",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      height: "100%", borderRadius: 4,
                      background: tc.accentGradient,
                      width: `${pct}%`,
                      animation: `wrp-barGrow 0.8s ease-out ${0.4 + i * 0.15}s both`,
                      ["--bar-w" as any]: `${pct}%`,
                    }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    },

    // Slide 4: Listening Clock
    () => {
      const maxHour = Math.max(...data.listening_hours, 1);
      return (
        <div style={{
          ...cardBase,
          background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
          border: tc.cardBorder,
          justifyContent: "flex-start", paddingTop: 28,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
            color: tc.hintColor, marginBottom: 8,
            animation: "wrp-fadeUp 0.5s ease-out",
          }}>
            LISTENING CLOCK
          </div>
          <div style={{
            fontSize: 14, color: tc.textColor, marginBottom: 20, fontWeight: 500,
            animation: "wrp-fadeUp 0.5s ease-out 0.2s both",
          }}>
            Peak hour: <span style={{ color: tc.highlight, fontWeight: 700 }}>{data.peak_hour}:00</span>
            {data.peak_hour >= 22 || data.peak_hour <= 4 ? " (Night Owl!)" : ""}
          </div>
          <div style={{
            display: "flex", alignItems: "flex-end", gap: 2,
            height: 140, width: "100%", padding: "0 4px",
            animation: "wrp-fadeUp 0.6s ease-out 0.3s both",
          }}>
            {data.listening_hours.map((count, h) => {
              const heightPct = maxHour > 0 ? (count / maxHour) * 100 : 0;
              const isPeak = h === data.peak_hour;
              return (
                <div key={h} style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  height: "100%",
                  justifyContent: "flex-end",
                }}>
                  <div style={{
                    width: "100%",
                    height: `${Math.max(2, heightPct)}%`,
                    borderRadius: 3,
                    background: isPeak ? tc.accentGradient : "rgba(255,255,255,0.12)",
                    transition: "height 0.5s ease-out",
                    boxShadow: isPeak ? tc.glowShadow : "none",
                  }} />
                </div>
              );
            })}
          </div>
          <div style={{
            display: "flex", justifyContent: "space-between", width: "100%",
            fontSize: 10, color: tc.hintColor, marginTop: 8, padding: "0 4px",
          }}>
            <span>0:00</span>
            <span>6:00</span>
            <span>12:00</span>
            <span>18:00</span>
            <span>23:00</span>
          </div>
        </div>
      );
    },

    // Slide 5: Personality + Summary
    () => (
      <div style={{
        ...cardBase,
        background: `linear-gradient(160deg, ${theme.bgColor}, ${theme.secondaryBg})`,
        border: tc.cardBorder,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
          color: tc.hintColor, marginBottom: 20,
          animation: "wrp-fadeUp 0.5s ease-out",
        }}>
          YOUR MUSIC PERSONALITY
        </div>
        <div style={{
          width: 90, height: 90, borderRadius: 45,
          background: tc.accentGradient,
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 16, boxShadow: tc.glowShadow,
          animation: "wrp-scaleIn 0.6s ease-out 0.2s both, wrp-glow 2s ease-in-out infinite",
        }}>
          {personality.emoji === "crown" ? <IconCrown size={36} color="#fff" /> :
           personality.emoji === "compass" ? <IconChart size={36} color="#fff" /> :
           personality.emoji === "rocket" ? <IconRocket size={36} color="#fff" /> :
           personality.emoji === "moon" ? <IconMoon size={36} color="#fff" /> :
           <IconStar size={36} color="#fff" filled />}
        </div>
        <div style={{
          fontSize: 26, fontWeight: 800, color: tc.textColor,
          animation: "wrp-fadeUp 0.6s ease-out 0.4s both",
        }}>
          {personality.label}
        </div>
        <div style={{
          fontSize: 14, color: tc.hintColor, marginTop: 8, maxWidth: 260, lineHeight: 1.5,
          animation: "wrp-fadeUp 0.5s ease-out 0.6s both",
        }}>
          {personality.desc}
        </div>

        <div style={{
          marginTop: 28, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center",
          animation: "wrp-fadeUp 0.5s ease-out 0.8s both",
        }}>
          <MiniStat label="Level" value={String(data.level)} tc={tc} />
          <MiniStat label="XP" value={data.xp.toLocaleString()} tc={tc} />
          <MiniStat label="Streak" value={`${data.streak_days}d`} tc={tc} />
        </div>

        <button
          onClick={() => {
            haptic("medium");
            const text = `My music personality: ${personality.label}! ${data.total_plays} tracks, ${formatTime(data.total_time)} of music. Check yours!`;
            const url = `https://t.me/TSmymusicbot_bot/app`;
            try {
              window.Telegram?.WebApp?.openTelegramLink?.(
                `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`
              );
            } catch {
              window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`, "_blank");
            }
          }}
          style={{
            marginTop: 24, padding: "12px 28px", borderRadius: 14,
            border: "none", background: tc.accentGradient, color: "#fff",
            fontSize: 14, fontWeight: 700, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 8,
            boxShadow: tc.glowShadow,
            animation: "wrp-fadeUp 0.5s ease-out 1s both",
          }}
        >
          <IconRocket size={14} color="#fff" /> Share Recap
        </button>
      </div>
    ),
  ];

  // Touch swipe handler
  const touchStart = useRef(0);
  const handleTouchStart = (e: TouchEvent) => { touchStart.current = e.touches[0].clientX; };
  const handleTouchEnd = (e: TouchEvent) => {
    const diff = e.changedTouches[0].clientX - touchStart.current;
    if (diff > 60 && currentSlide > 0) goSlide(-1);
    else if (diff < -60 && currentSlide < totalSlides - 1) goSlide(1);
  };

  return (
    <div
      style={{ paddingBottom: 24, userSelect: "none" }}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* Slide indicator dots */}
      <div style={{
        display: "flex", justifyContent: "center", gap: 6, marginBottom: 16,
      }}>
        {Array.from({ length: totalSlides }).map((_, i) => (
          <div
            key={i}
            onClick={() => { haptic("light"); setCurrentSlide(i); }}
            style={{
              width: i === currentSlide ? 24 : 8,
              height: 8,
              borderRadius: 4,
              background: i === currentSlide ? tc.accentGradient : "rgba(255,255,255,0.12)",
              transition: "all 0.3s ease",
              cursor: "pointer",
            }}
          />
        ))}
      </div>

      {/* Current slide */}
      <div
        key={currentSlide}
        style={{
          animation: slideAnim ? `${slideAnim} 0.4s ease-out` : "wrp-fadeUp 0.4s ease-out",
        }}
      >
        {slides[currentSlide]()}
      </div>

      {/* Navigation arrows */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginTop: 16, padding: "0 8px",
      }}>
        <button
          onClick={() => currentSlide > 0 && goSlide(-1)}
          style={{
            padding: "10px 20px", borderRadius: 12,
            border: tc.cardBorder, background: tc.cardBg,
            color: currentSlide > 0 ? tc.textColor : tc.hintColor,
            fontSize: 13, fontWeight: 600, cursor: currentSlide > 0 ? "pointer" : "default",
            opacity: currentSlide > 0 ? 1 : 0.4,
          }}
        >
          Back
        </button>
        <span style={{ fontSize: 12, color: tc.hintColor }}>
          {currentSlide + 1} / {totalSlides}
        </span>
        <button
          onClick={() => currentSlide < totalSlides - 1 && goSlide(1)}
          style={{
            padding: "10px 20px", borderRadius: 12,
            border: "none", background: currentSlide < totalSlides - 1 ? tc.accentGradient : tc.cardBg,
            color: currentSlide < totalSlides - 1 ? "#fff" : tc.hintColor,
            fontSize: 13, fontWeight: 700, cursor: currentSlide < totalSlides - 1 ? "pointer" : "default",
            opacity: currentSlide < totalSlides - 1 ? 1 : 0.4,
            boxShadow: currentSlide < totalSlides - 1 ? tc.glowShadow : "none",
          }}
        >
          Next
        </button>
      </div>

      {/* Top Tracks List (below slides) */}
      {data.top_tracks && data.top_tracks.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{
            fontSize: 15, fontWeight: 700, color: tc.textColor, marginBottom: 12,
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <IconFire size={16} color={tc.highlight} /> Top Tracks
          </div>
          {data.top_tracks.slice(0, 10).map((track, i) => (
            <div
              key={track.video_id}
              onClick={() => { haptic("light"); onPlayTrack(track); }}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 12px", borderRadius: 14, marginBottom: 6,
                background: tc.cardBg, border: tc.cardBorder,
                cursor: "pointer", transition: "all 0.15s ease",
              }}
            >
              <span style={{
                fontSize: 14, fontWeight: 700, color: i < 3 ? tc.highlight : tc.hintColor,
                width: 24, textAlign: "center", flexShrink: 0,
              }}>
                {i === 0 ? "\u{1F947}" : i === 1 ? "\u{1F948}" : i === 2 ? "\u{1F949}" : `${i + 1}`}
              </span>
              <div style={{
                width: 40, height: 40, borderRadius: 8, overflow: "hidden", flexShrink: 0,
                background: tc.coverPlaceholderBg,
              }}>
                {track.cover_url ? (
                  <img src={track.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <IconMusicNote size={16} color={tc.hintColor} />
                  </div>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: tc.textColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {track.title}
                </div>
                <div style={{ fontSize: 11, color: tc.hintColor }}>
                  {track.artist}
                </div>
              </div>
              <div style={{ flexShrink: 0, textAlign: "right" }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: tc.highlight }}>{(track as any).play_count}x</div>
                <IconPlaySmall size={12} color={tc.hintColor} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Helper components ──

function StatBubble({ label, value, tc, icon }: { label: string; value: number; tc: any; icon?: any }) {
  return (
    <div style={{
      padding: "12px 16px", borderRadius: 14,
      background: tc.cardBg, border: tc.cardBorder,
      textAlign: "center", minWidth: 72,
    }}>
      {icon && <div style={{ marginBottom: 4 }}>{icon}</div>}
      <div style={{ fontSize: 20, fontWeight: 800, color: tc.textColor }}>{value}</div>
      <div style={{ fontSize: 10, color: tc.hintColor, fontWeight: 600, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function MiniStat({ label, value, tc }: { label: string; value: string; tc: any }) {
  return (
    <div style={{
      padding: "10px 16px", borderRadius: 12,
      background: tc.cardBg, border: tc.cardBorder,
      textAlign: "center",
    }}>
      <div style={{ fontSize: 16, fontWeight: 800, color: tc.highlight }}>{value}</div>
      <div style={{ fontSize: 10, color: tc.hintColor, fontWeight: 600, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function EmptySlide({ tc, text }: { tc: any; text: string }) {
  return (
    <div style={{
      borderRadius: 24, padding: "60px 20px", minHeight: 380,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      background: tc.cardBg, border: tc.cardBorder,
    }}>
      <IconMusicNote size={40} color={tc.hintColor} />
      <div style={{ fontSize: 15, color: tc.hintColor, marginTop: 16 }}>{text}</div>
    </div>
  );
}
