import { useState, useEffect } from "preact/hooks";
import { fetchLyrics } from "../api";

interface Props {
  trackId: string;
  onBack: () => void;
}

export function LyricsView({ trackId, onBack }: Props) {
  const [lyrics, setLyrics] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchLyrics(trackId)
      .then(setLyrics)
      .catch(() => setLyrics(null))
      .finally(() => setLoading(false));
  }, [trackId]);

  return (
    <div>
      <button
        onClick={onBack}
        style={{ background: "none", border: "none", color: "var(--tg-theme-link-color, #7c4dff)", cursor: "pointer", marginBottom: 12, fontSize: 14 }}
      >
        ← Назад к плееру
      </button>

      {loading ? (
        <div style={{ textAlign: "center", padding: 32 }}>⏳ Загрузка текста...</div>
      ) : lyrics ? (
        <pre style={{
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 14,
          lineHeight: 1.6,
          padding: 12,
          borderRadius: 12,
          background: "var(--tg-theme-secondary-bg-color, #2a2a3e)",
        }}>
          {lyrics}
        </pre>
      ) : (
        <div style={{ textAlign: "center", padding: 32, color: "var(--tg-theme-hint-color, #aaa)" }}>
          Текст не найден 😔
        </div>
      )}
    </div>
  );
}
