import { useEffect, useRef, useState, useCallback } from "preact/hooks";
import { memo } from "preact/compat";
import { extractDominantColor, rgbToCSS } from "../colorExtractor";
import { getStoryCardUrl } from "../api";
import { IconClose, IconUpload } from "./Icons";

interface ShareCardProps {
  track: {
    title: string;
    artist: string;
    video_id?: string;
    cover_url?: string;
    duration_fmt?: string;
  };
  onClose: () => void;
  accentColor?: string;
  themeId?: string;
}

/**
 * ShareCard — generates a viral share card for Instagram Stories / social media.
 * Uses canvas to create an image with track info + QR code.
 */
export const ShareCard = memo(function ShareCard({ track, onClose, accentColor = "#7c4dff", themeId = "blackroom" }: ShareCardProps) {
  const isTequila = themeId === "tequila";
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const [isGenerating, setIsGenerating] = useState(false);
  const [cardUrl, setCardUrl] = useState<string | null>(null);
  const [dominantColor, setDominantColor] = useState(accentColor);

  const generateCard = useCallback(async () => {
    if (!canvasRef.current) return;
    const generationId = ++generationRef.current;
    setIsGenerating(true);

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setIsGenerating(false);
      return;
    }

    // Set canvas size (Instagram Story ratio 9:16)
    canvas.width = 1080;
    canvas.height = 1920;

    // Extract color from cover
    let bgColor = accentColor;
    if (track.cover_url) {
      try {
        const color = await extractDominantColor(track.cover_url);
        if (generationId !== generationRef.current) {
          return;
        }
        bgColor = rgbToCSS(color);
      } catch {
        // Use default
      }
    }
    setDominantColor(bgColor);

    // Background gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, bgColor);
    gradient.addColorStop(0.5, isTequila ? "#2b170d" : "#1a1a2e");
    gradient.addColorStop(1, isTequila ? "#120a06" : "#0d0d1a");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (isTequila) {
      const glow = ctx.createRadialGradient(canvas.width / 2, 240, 100, canvas.width / 2, 240, 700);
      glow.addColorStop(0, "rgba(255, 213, 79, 0.18)");
      glow.addColorStop(1, "rgba(255, 213, 79, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // Draw cover image (if available)
    if (track.cover_url) {
      try {
        const img = new Image();
        img.crossOrigin = "anonymous";
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject();
          img.src = track.cover_url!;
        });
        if (generationId !== generationRef.current) {
          return;
        }

        // Draw large cover with rounded corners
        const coverSize = 700;
        const coverX = (canvas.width - coverSize) / 2;
        const coverY = 350;

        // Create rounded rect clip
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(coverX, coverY, coverSize, coverSize, 40);
        ctx.clip();
        ctx.drawImage(img, coverX, coverY, coverSize, coverSize);
        ctx.restore();

        // Add shadow/glow effect
        ctx.shadowColor = isTequila ? "rgba(255, 167, 38, 0.8)" : bgColor;
        ctx.shadowBlur = 60;
        ctx.strokeStyle = isTequila ? "rgba(255, 213, 79, 0.28)" : "rgba(255,255,255,0.1)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(coverX, coverY, coverSize, coverSize, 40);
        ctx.stroke();
        ctx.shadowBlur = 0;
      } catch {
        // Skip cover
      }
    }

    // Track title
    ctx.fillStyle = isTequila ? "#fef0e0" : "#ffffff";
    ctx.font = "bold 64px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    
    // Word wrap title
    const maxWidth = canvas.width - 100;
    const titleLines = wrapText(ctx, track.title, maxWidth);
    let titleY = 1150;
    titleLines.forEach((line, i) => {
      ctx.fillText(line, canvas.width / 2, titleY + i * 75);
    });

    // Artist name
    ctx.fillStyle = isTequila ? "rgba(254,240,224,0.78)" : "rgba(255,255,255,0.7)";
    ctx.font = "48px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillText(track.artist || "Unknown Artist", canvas.width / 2, titleY + titleLines.length * 75 + 50);

    // Duration badge
    if (track.duration_fmt) {
      ctx.fillStyle = isTequila ? "rgba(255,213,79,0.12)" : "rgba(255,255,255,0.1)";
      ctx.beginPath();
      ctx.roundRect(canvas.width / 2 - 80, titleY + titleLines.length * 75 + 110, 160, 50, 25);
      ctx.fill();
      
      ctx.fillStyle = isTequila ? "#ffd54f" : "rgba(255,255,255,0.8)";
      ctx.font = "32px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(track.duration_fmt, canvas.width / 2, titleY + titleLines.length * 75 + 135);
    }

    // Branding
    ctx.fillStyle = isTequila ? "rgba(255,213,79,0.72)" : "rgba(255,255,255,0.5)";
    ctx.font = "bold 36px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillText(isTequila ? "𝐓 𝐄 𝐐 𝐔 𝐈 𝐋 𝐀  𝐌 𝐔 𝐒 𝐈 𝐂" : "BLACK ROOM", canvas.width / 2, 1700);

    if (isTequila) {
      ctx.fillStyle = "rgba(200,168,130,0.92)";
      ctx.font = "28px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText("inspired by 𝗧𝗘𝗤𝗨𝗜𝗟𝗔 𝗦𝗨𝗡𝗦𝗛𝗜𝗡𝗘.", canvas.width / 2, 1752);
    }

    // Swipe up hint
    ctx.fillStyle = isTequila ? "rgba(200,168,130,0.78)" : "rgba(255,255,255,0.4)";
    ctx.font = "28px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillText("⬆ Swipe up to listen", canvas.width / 2, isTequila ? 1810 : 1780);

    // Music note decoration
    ctx.font = "120px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillStyle = isTequila ? "rgba(255,213,79,0.1)" : "rgba(255,255,255,0.1)";
    ctx.fillText("♪", 100, 200);
    ctx.fillText("♫", canvas.width - 150, 1600);

    // Convert to blob URL
    try {
      canvas.toBlob((blob) => {
        if (generationId !== generationRef.current) {
          return;
        }

        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current);
          objectUrlRef.current = null;
        }

        if (blob) {
          const url = URL.createObjectURL(blob);
          objectUrlRef.current = url;
          setCardUrl(url);
        } else {
          setCardUrl(null);
        }
        setIsGenerating(false);
      }, "image/png");
    } catch {
      // Canvas tainted (CORS) — toBlob throws SecurityError
      setIsGenerating(false);
    }
  }, [track, accentColor, isTequila]);

  useEffect(() => {
    setCardUrl(null);
    void generateCard();

    return () => {
      generationRef.current += 1;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [generateCard]);

  const handleShare = useCallback((e: Event) => {
    e.stopPropagation();
    const appLink = `https://t.me/TSmymusicbot_bot/app?startapp=play_${track.video_id || ""}`;
    // Put everything into text so it's one cohesive message
    const msg = `🎵 ${track.artist} — ${track.title}\n\n▶️ Послушать: ${appLink}`;
    const shareUrl = `https://t.me/share/url?url=&text=${encodeURIComponent(msg)}`;
    const tg = (window as any).Telegram?.WebApp;
    if (tg?.openTelegramLink) {
      tg.openTelegramLink(shareUrl);
    } else {
      window.open(shareUrl, "_blank");
    }
  }, [track]);

  const handleDownload = useCallback((e: Event) => {
    e.stopPropagation();
    const path = track.video_id ? getStoryCardUrl(track.video_id) : null;
    if (!path) return;
    const absUrl = path.startsWith("http") ? path : `${window.location.origin}${path}`;
    // openLink opens external browser; window.open as fallback
    const tg = (window as any).Telegram?.WebApp;
    if (tg?.openLink) {
      tg.openLink(absUrl);
    } else {
      window.open(absUrl, "_blank");
    }
  }, [track.video_id]);

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: isTequila ? "rgba(12, 6, 3, 0.92)" : "rgba(0,0,0,0.9)",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        type="button"
        aria-label="Close share card"
        title="Close"
        style={{
          position: "absolute",
          top: 20,
          right: 20,
          background: isTequila ? "rgba(255, 213, 79, 0.12)" : "rgba(255,255,255,0.1)",
          border: isTequila ? "1px solid rgba(255, 213, 79, 0.16)" : "none",
          borderRadius: "50%",
          width: 44,
          height: 44,
          color: isTequila ? "#ffd54f" : "#fff",
          fontSize: 24,
          cursor: "pointer",
        }}
      >
        <IconClose size={20} />
      </button>

      {/* Preview */}
      <div
        style={{
          maxHeight: "60vh",
          maxWidth: "90vw",
          overflow: "hidden",
          borderRadius: 20,
          boxShadow: `0 0 60px ${dominantColor}40`,
          border: isTequila ? "1px solid rgba(255, 213, 79, 0.16)" : "none",
        }}
      >
        <canvas
          ref={canvasRef}
          style={{
            maxHeight: "60vh",
            maxWidth: "90vw",
            objectFit: "contain",
          }}
        />
      </div>

      {/* Actions */}
      <div style={{ marginTop: 20, display: "flex", gap: 12 }}>
        {isGenerating ? (
          <div style={{ color: isTequila ? "#fef0e0" : "#fff", fontSize: 16 }}>Generating...</div>
        ) : (
          <>
            <button
              type="button"
              onClick={handleShare}
              style={{
                padding: "12px 28px",
                borderRadius: 24,
                border: "none",
                background: isTequila ? "linear-gradient(135deg, #ff6d00, #ffa726)" : dominantColor,
                color: isTequila ? "#1a120b" : "#fff",
                fontSize: 16,
                fontWeight: 600,
                cursor: "pointer",
                boxShadow: isTequila ? "0 8px 24px rgba(255, 109, 0, 0.3)" : "none",
                WebkitTapHighlightColor: "transparent",
                touchAction: "manipulation",
              }}
            >
              <IconUpload size={16} /> Share
            </button>
            <button
              type="button"
              onClick={handleDownload}
              style={{
                padding: "12px 28px",
                borderRadius: 24,
                border: isTequila ? "1px solid rgba(255, 213, 79, 0.16)" : "none",
                background: isTequila ? "rgba(40, 25, 15, 0.62)" : "rgba(255,255,255,0.1)",
                color: isTequila ? "#fef0e0" : "#fff",
                fontSize: 16,
                fontWeight: 600,
                cursor: "pointer",
                WebkitTapHighlightColor: "transparent",
                touchAction: "manipulation",
              }}
            >
              ⬇ Download
            </button>
          </>
        )}
      </div>

      <p style={{ marginTop: 16, color: isTequila ? "#c8a882" : "rgba(255,255,255,0.5)", fontSize: 14 }}>
        Share to Instagram Stories, Telegram, etc.
      </p>
    </div>
  );
});

// Helper: word wrap text
function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  if (!text.trim()) {
    return ["Untitled Track"];
  }

  const words = text.split(" ");
  const lines: string[] = [];
  let currentLine = words[0];

  for (let i = 1; i < words.length; i++) {
    const word = words[i];
    const width = ctx.measureText(currentLine + " " + word).width;
    if (width < maxWidth) {
      currentLine += " " + word;
    } else {
      lines.push(currentLine);
      currentLine = word;
    }
  }
  lines.push(currentLine);
  
  // Limit to 2 lines
  if (lines.length > 2) {
    lines[1] = lines[1].slice(0, -3) + "...";
    return lines.slice(0, 2);
  }
  
  return lines;
}
