import { useState, useEffect, useCallback } from "preact/hooks";
import { fetchActivityFeed, type ActivityItem, type Track } from "../api";
import { getThemeById, themeColors } from "../themes";
import {
  IconSpinner, IconHeadphones, IconPlaySmall, IconMusic, IconFire, IconUser,
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

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "сейчас";
  if (mins < 60) return `${mins}м`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}ч`;
  const days = Math.floor(hours / 24);
  return `${days}д`;
}

export function ActivityFeedView({
  userId,
  onPlayTrack,
  accentColor = "var(--tg-theme-button-color, #7c4dff)",
  themeId = "blackroom",
}: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [feed, setFeed] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const loadFeed = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await fetchActivityFeed(40);
      setFeed(data);
    } catch {
      setError(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadFeed(); }, []);

  const handlePlay = useCallback((item: ActivityItem) => {
    haptic("light");
    const track: Track = {
      video_id: item.video_id,
      title: item.track_title,
      artist: item.track_artist,
      duration: 0,
      duration_fmt: "0:00",
      source: "youtube",
      cover_url: item.cover_url,
    };
    onPlayTrack(track);
  }, [onPlayTrack]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 64 }}>
        <IconSpinner size={28} color={tc.hintColor} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: "center", padding: 64, color: tc.hintColor, fontSize: 14 }}>
        Не удалось загрузить ленту
      </div>
    );
  }

  if (feed.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 48 }}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>👥</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: tc.textColor, marginBottom: 6 }}>
          Лента пока пуста
        </div>
        <div style={{ fontSize: 13, color: tc.hintColor }}>
          Здесь появится то, что слушают другие
        </div>
      </div>
    );
  }

  // Group by time sections
  const now = Date.now();
  const recentItems = feed.filter((f) => f.played_at && (now - new Date(f.played_at).getTime()) < 3600000);
  const olderItems = feed.filter((f) => !f.played_at || (now - new Date(f.played_at).getTime()) >= 3600000);

  const renderItem = (item: ActivityItem, idx: number) => {
    const isMe = item.user_id === userId;
    return (
      <div
        key={`${item.video_id}-${item.user_id}-${idx}`}
        onClick={() => handlePlay(item)}
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 12px", borderRadius: 14, marginBottom: 6,
          background: isMe ? (tc.isTequila ? "rgba(255,143,0,0.06)" : `${accentColor}06`) : tc.cardBg,
          border: tc.cardBorder,
          backdropFilter: "blur(16px)",
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
      >
        {/* User avatar */}
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: tc.activeBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0, fontSize: 14, fontWeight: 700,
          color: tc.highlight,
        }}>
          {item.user_name.charAt(0).toUpperCase()}
        </div>

        {/* Track cover */}
        <div style={{
          width: 40, height: 40, borderRadius: 10, overflow: "hidden",
          flexShrink: 0,
          background: tc.coverPlaceholderBg,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {item.cover_url
            ? <img src={item.cover_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : <IconMusic size={18} color={tc.hintColor} />
          }
        </div>

        {/* Info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 12, color: tc.highlight, fontWeight: 600, marginBottom: 2,
          }}>
            {item.user_name}{isMe ? " (ты)" : ""}
          </div>
          <div style={{
            fontSize: 13, fontWeight: 500, color: tc.textColor,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {item.track_title}
          </div>
          <div style={{
            fontSize: 11, color: tc.hintColor,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {item.track_artist}
          </div>
        </div>

        {/* Time + play */}
        <div style={{ flexShrink: 0, textAlign: "right" }}>
          {item.played_at && (
            <div style={{ fontSize: 10, color: tc.hintColor, marginBottom: 4 }}>
              {timeAgo(item.played_at)}
            </div>
          )}
          <IconPlaySmall size={14} color={tc.highlight} />
        </div>
      </div>
    );
  };

  return (
    <div style={{ paddingBottom: 24 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 16,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: tc.activeBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: tc.glowShadow.replace(/0\.\d+\)/, (m) => `${parseFloat(m) * 0.3})`),
        }}>
          <IconHeadphones size={20} color={tc.highlight} />
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: tc.textColor }}>
            Лента активности
          </div>
          <div style={{ fontSize: 12, color: tc.hintColor }}>
            Что слушают прямо сейчас
          </div>
        </div>
      </div>

      {/* Live now section */}
      {recentItems.length > 0 && (
        <>
          <div style={{
            fontSize: 13, fontWeight: 600, color: tc.highlight,
            display: "flex", alignItems: "center", gap: 5,
            marginBottom: 8,
          }}>
            <IconFire size={13} color={tc.isTequila ? "#ffab40" : "#ff7043"} /> Сейчас слушают
          </div>
          {recentItems.map(renderItem)}
        </>
      )}

      {/* Older */}
      {olderItems.length > 0 && (
        <>
          <div style={{
            fontSize: 13, fontWeight: 600, color: tc.hintColor,
            marginBottom: 8, marginTop: recentItems.length > 0 ? 16 : 0,
          }}>
            Недавно
          </div>
          {olderItems.map(renderItem)}
        </>
      )}

      {/* Refresh */}
      <div style={{ textAlign: "center", marginTop: 16 }}>
        <button
          onClick={() => { haptic("light"); loadFeed(); }}
          style={{
            padding: "10px 24px", borderRadius: 12, border: tc.cardBorder,
            background: tc.cardBg, color: tc.highlight,
            fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}
        >
          Обновить
        </button>
      </div>
    </div>
  );
}
