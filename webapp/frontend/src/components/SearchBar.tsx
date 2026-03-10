import { useState } from "preact/hooks";
import { searchTracks, type Track } from "../api";
import { SkeletonTrack } from "./Skeleton";
import { IconSpinner, IconSearch } from "./Icons";

interface Props {
  onSelect: (track: Track) => void;
}

export function SearchBar({ onSelect }: Props) {
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
            padding: "8px 14px",
            borderRadius: 12,
            border: "1px solid var(--tg-theme-hint-color, #555)",
            background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
            color: "var(--tg-theme-text-color, #eee)",
            fontSize: 14,
            outline: "none",
          }}
        />
        <button
          onClick={doSearch}
          disabled={loading}
          style={{
            padding: "8px 16px",
            borderRadius: 12,
            border: "none",
            background: "var(--tg-theme-button-color, #7c4dff)",
            color: "#fff",
            fontSize: 14,
            cursor: "pointer",
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
            padding: "8px 12px",
            borderRadius: 8,
            marginBottom: 4,
            cursor: "pointer",
            background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
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
            <div style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</div>
            <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)" }}>{t.artist}</div>
          </div>
          <div style={{ fontSize: 12, color: "var(--tg-theme-hint-color, #aaa)" }}>{t.duration_fmt}</div>
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
