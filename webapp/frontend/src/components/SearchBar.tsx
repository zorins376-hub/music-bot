import { useState } from "preact/hooks";
import { searchTracks, type Track } from "../api";
import { SkeletonTrack } from "./Skeleton";
import { IconSpinner, IconSearch } from "./Icons";

interface Props {
  onSelect: (track: Track) => void;
  accentColor?: string;
  themeId?: string;
}

export function SearchBar({ onSelect, accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const isTequila = themeId === "tequila";
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);

  const doSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const tracks = await searchTracks(query.trim());
      setResults(tracks);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          type="text"
          value={query}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          placeholder="Поиск треков..."
          style={{
            flex: 1,
            padding: isTequila ? "10px 16px" : "8px 14px",
            borderRadius: 14,
            border: isTequila ? "1px solid rgba(255, 213, 79, 0.16)" : "1px solid var(--tg-theme-hint-color, #555)",
            background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
            color: isTequila ? "#fef0e0" : "var(--tg-theme-text-color, #eee)",
            fontSize: 14,
            outline: "none",
            backdropFilter: isTequila ? "blur(14px)" : undefined,
          }}
        />
        <button
          onClick={doSearch}
          disabled={loading}
          style={{
            padding: isTequila ? "8px 18px" : "8px 16px",
            borderRadius: 14,
            border: "none",
            background: isTequila ? "linear-gradient(135deg, #ff6d00, #ffa726)" : accentColor,
            color: isTequila ? "#1a120b" : "#fff",
            fontSize: 14,
            cursor: "pointer",
            boxShadow: isTequila ? "0 4px 16px rgba(255, 109, 0, 0.26)" : "none",
          }}
        >
          {loading ? <IconSpinner size={18} /> : <IconSearch size={18} />}
        </button>
      </div>

      {loading ? (
        <>
          <SkeletonTrack />
          <SkeletonTrack />
          <SkeletonTrack />
          <SkeletonTrack />
          <SkeletonTrack />
        </>
      ) : results.map((t) => (
        <div
          key={t.video_id}
          onClick={() => onSelect(t)}
          style={{
            display: "flex",
            alignItems: "center",
            padding: isTequila ? "10px 12px" : "8px 12px",
            borderRadius: 12,
            marginBottom: 6,
            cursor: "pointer",
            background: isTequila ? "rgba(40, 25, 15, 0.55)" : "var(--tg-theme-secondary-bg-color, #2a2a3e)",
            border: isTequila ? "1px solid rgba(255, 213, 79, 0.1)" : "none",
            backdropFilter: isTequila ? "blur(12px)" : undefined,
          }}
        >
          {t.cover_url && (
            <img
              src={t.cover_url}
              alt=""
              style={{ width: 44, height: 44, borderRadius: 8, marginRight: 12, objectFit: "cover" }}
            />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: isTequila ? "#fef0e0" : undefined }}>{t.title}</div>
            <div style={{ fontSize: 12, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>{t.artist}</div>
          </div>
          <div style={{ fontSize: 12, color: isTequila ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>{t.duration_fmt}</div>
        </div>
      ))}
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}
