import { useRef, useEffect, useCallback } from "preact/hooks";

interface Props {
  analyser: AnalyserNode | null;
  isPlaying: boolean;
  accentColor?: string;
  themeId?: string;
  width?: number;
  height?: number;
  style?: "bars" | "wave" | "circle";
}

/**
 * Real-time audio spectrum visualizer.
 * Renders frequencies from an AnalyserNode onto a canvas.
 */
export function SpectrumVisualizer({
  analyser,
  isPlaying,
  accentColor = "#7c4dff",
  themeId = "blackroom",
  width = 320,
  height = 80,
  style = "bars",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const isTequila = themeId === "tequila";

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !analyser) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    analyser.getByteFrequencyData(dataArray);

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.scale(dpr, dpr);

    if (style === "bars") {
      drawBars(ctx, dataArray, bufferLength, w, h, isTequila, accentColor);
    } else if (style === "wave") {
      drawWave(ctx, dataArray, bufferLength, w, h, isTequila, accentColor);
    } else if (style === "circle") {
      drawCircle(ctx, dataArray, bufferLength, w, h, isTequila, accentColor);
    }

    ctx.restore();
    rafRef.current = requestAnimationFrame(draw);
  }, [analyser, style, accentColor, isTequila]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
  }, [width, height]);

  useEffect(() => {
    if (isPlaying && analyser) {
      rafRef.current = requestAnimationFrame(draw);
    }
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [isPlaying, analyser, draw]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        width,
        height,
        borderRadius: 16,
        opacity: isPlaying ? 1 : 0.3,
        transition: "opacity 0.5s ease",
      }}
    />
  );
}

function drawBars(
  ctx: CanvasRenderingContext2D,
  data: Uint8Array,
  len: number,
  w: number,
  h: number,
  warm: boolean,
  accent: string,
) {
  const barCount = 48;
  const gap = 2;
  const barWidth = (w - gap * (barCount - 1)) / barCount;
  const step = Math.floor(len / barCount);

  // Single gradient for all bars (vertical, full height) — avoids 48 gradient creations/frame
  const grad = ctx.createLinearGradient(0, h, 0, 0);
  if (warm) {
    grad.addColorStop(0, "rgba(255, 109, 0, 0.9)");
    grad.addColorStop(0.5, "rgba(255, 167, 38, 0.8)");
    grad.addColorStop(1, "rgba(255, 213, 79, 0.95)");
  } else {
    grad.addColorStop(0, accent);
    grad.addColorStop(0.5, "#b388ff");
    grad.addColorStop(1, "#e040fb");
  }

  // Draw all bars with shared gradient
  ctx.fillStyle = grad;
  for (let i = 0; i < barCount; i++) {
    const val = data[i * step] / 255;
    const barH = Math.max(2, val * h * 0.92);
    const x = i * (barWidth + gap);
    const y = h - barH;
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barH, [barWidth / 2, barWidth / 2, 0, 0]);
    ctx.fill();
  }

  // Batch reflections with single alpha switch
  ctx.globalAlpha = 0.15;
  for (let i = 0; i < barCount; i++) {
    const val = data[i * step] / 255;
    const barH = Math.max(2, val * h * 0.92);
    const x = i * (barWidth + gap);
    ctx.beginPath();
    ctx.roundRect(x, h, barWidth, barH * 0.25, [0, 0, barWidth / 2, barWidth / 2]);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawWave(
  ctx: CanvasRenderingContext2D,
  data: Uint8Array,
  len: number,
  w: number,
  h: number,
  warm: boolean,
  accent: string,
) {
  const points = 64;
  const step = Math.floor(len / points);
  
  ctx.beginPath();
  ctx.moveTo(0, h);

  for (let i = 0; i < points; i++) {
    const val = data[i * step] / 255;
    const x = (i / (points - 1)) * w;
    const y = h - val * h * 0.85;
    if (i === 0) {
      ctx.lineTo(x, y);
    } else {
      const prevX = ((i - 1) / (points - 1)) * w;
      const cpX = (prevX + x) / 2;
      ctx.quadraticCurveTo(cpX, y, x, y);
    }
  }

  ctx.lineTo(w, h);
  ctx.closePath();

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  if (warm) {
    grad.addColorStop(0, "rgba(255, 167, 38, 0.7)");
    grad.addColorStop(1, "rgba(255, 109, 0, 0.1)");
  } else {
    grad.addColorStop(0, "rgba(124, 77, 255, 0.7)");
    grad.addColorStop(1, "rgba(224, 64, 251, 0.1)");
  }
  ctx.fillStyle = grad;
  ctx.fill();

  // Stroke line on top
  ctx.beginPath();
  ctx.moveTo(0, h);
  for (let i = 0; i < points; i++) {
    const val = data[i * step] / 255;
    const x = (i / (points - 1)) * w;
    const y = h - val * h * 0.85;
    if (i === 0) ctx.lineTo(x, y);
    else {
      const prevX = ((i - 1) / (points - 1)) * w;
      ctx.quadraticCurveTo((prevX + x) / 2, y, x, y);
    }
  }
  ctx.strokeStyle = warm ? "rgba(255, 213, 79, 0.9)" : "rgba(179, 136, 255, 0.9)";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function drawCircle(
  ctx: CanvasRenderingContext2D,
  data: Uint8Array,
  len: number,
  w: number,
  h: number,
  warm: boolean,
  accent: string,
) {
  const cx = w / 2;
  const cy = h / 2;
  const baseR = Math.min(w, h) * 0.28;
  const points = 64;
  const step = Math.floor(len / points);

  ctx.beginPath();
  for (let i = 0; i <= points; i++) {
    const idx = i % points;
    const val = data[idx * step] / 255;
    const angle = (idx / points) * Math.PI * 2 - Math.PI / 2;
    const r = baseR + val * baseR * 0.8;
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();

  const grad = ctx.createRadialGradient(cx, cy, baseR * 0.3, cx, cy, baseR * 2);
  if (warm) {
    grad.addColorStop(0, "rgba(255, 167, 38, 0.6)");
    grad.addColorStop(1, "rgba(255, 109, 0, 0.15)");
  } else {
    grad.addColorStop(0, "rgba(124, 77, 255, 0.6)");
    grad.addColorStop(1, "rgba(224, 64, 251, 0.15)");
  }
  ctx.fillStyle = grad;
  ctx.fill();
  ctx.strokeStyle = warm ? "rgba(255, 213, 79, 0.8)" : "rgba(179, 136, 255, 0.8)";
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Inner circle
  ctx.beginPath();
  ctx.arc(cx, cy, baseR * 0.6, 0, Math.PI * 2);
  ctx.fillStyle = warm ? "rgba(26, 18, 11, 0.6)" : "rgba(26, 26, 46, 0.6)";
  ctx.fill();
}
