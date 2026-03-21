/**
 * Dynamic Color Extraction from cover image.
 * Uses Canvas API to extract dominant color from YouTube thumbnails.
 */

interface RGB { r: number; g: number; b: number; }

/**
 * Extract dominant color from an image URL.
 * Loads image onto a hidden canvas, samples pixels, and returns dominant colour.
 */
export function extractDominantColor(imageUrl: string): Promise<RGB> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const size = 64; // Scale down for speed
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) { resolve({ r: 124, g: 77, b: 255 }); return; }

      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;

      // Simple colour bucketing
      const buckets: Map<string, { r: number; g: number; b: number; count: number }> = new Map();
      for (let i = 0; i < data.length; i += 16) { // Sample every 4th pixel
        const r = Math.round(data[i] / 32) * 32;
        const g = Math.round(data[i + 1] / 32) * 32;
        const b = Math.round(data[i + 2] / 32) * 32;

        // Skip near-black and near-white (they are boring)
        const brightness = (r + g + b) / 3;
        if (brightness < 30 || brightness > 230) continue;
        // Skip near-gray
        const saturation = Math.max(r, g, b) - Math.min(r, g, b);
        if (saturation < 30) continue;

        const key = `${r},${g},${b}`;
        const existing = buckets.get(key);
        if (existing) {
          existing.r += data[i];
          existing.g += data[i + 1];
          existing.b += data[i + 2];
          existing.count++;
        } else {
          buckets.set(key, { r: data[i], g: data[i + 1], b: data[i + 2], count: 1 });
        }
      }

      // Find bucket with most pixels
      let best: { r: number; g: number; b: number; count: number } | null = null;
      for (const bucket of buckets.values()) {
        if (!best || bucket.count > best.count) best = bucket;
      }

      if (best && best.count > 0) {
        resolve({
          r: Math.round(best.r / best.count),
          g: Math.round(best.g / best.count),
          b: Math.round(best.b / best.count),
        });
      } else {
        // Fallback purple
        resolve({ r: 124, g: 77, b: 255 });
      }
    };
    img.onerror = () => resolve({ r: 124, g: 77, b: 255 });
    img.src = imageUrl;
  });
}

/** Convert RGB to CSS string */
export function rgbToCSS(c: RGB): string {
  return `rgb(${c.r}, ${c.g}, ${c.b})`;
}

/** Convert RGB to CSS string with alpha */
export function rgbaToCSS(c: RGB, a: number): string {
  return `rgba(${c.r}, ${c.g}, ${c.b}, ${a})`;
}

/** Lighten a color for highlights */
export function lightenColor(c: RGB, amount = 0.3): RGB {
  return {
    r: Math.min(255, Math.round(c.r + (255 - c.r) * amount)),
    g: Math.min(255, Math.round(c.g + (255 - c.g) * amount)),
    b: Math.min(255, Math.round(c.b + (255 - c.b) * amount)),
  };
}

/**
 * Extract top-3 dominant colors from an image URL.
 * Returns array of 3 RGB colors sorted by frequency.
 */
export function extractTopColors(imageUrl: string): Promise<RGB[]> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const size = 64;
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) { resolve([{ r: 124, g: 77, b: 255 }, { r: 76, g: 40, b: 180 }, { r: 30, g: 15, b: 90 }]); return; }

      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;

      const buckets: Map<string, { r: number; g: number; b: number; count: number }> = new Map();
      for (let i = 0; i < data.length; i += 16) {
        const r = Math.round(data[i] / 32) * 32;
        const g = Math.round(data[i + 1] / 32) * 32;
        const b = Math.round(data[i + 2] / 32) * 32;

        const brightness = (r + g + b) / 3;
        if (brightness < 30 || brightness > 230) continue;
        const saturation = Math.max(r, g, b) - Math.min(r, g, b);
        if (saturation < 20) continue;

        const key = `${r},${g},${b}`;
        const existing = buckets.get(key);
        if (existing) {
          existing.r += data[i];
          existing.g += data[i + 1];
          existing.b += data[i + 2];
          existing.count++;
        } else {
          buckets.set(key, { r: data[i], g: data[i + 1], b: data[i + 2], count: 1 });
        }
      }

      const sorted = [...buckets.values()].sort((a, b) => b.count - a.count);
      const fallback: RGB = { r: 124, g: 77, b: 255 };
      const colors: RGB[] = [];
      for (let i = 0; i < 3; i++) {
        const b = sorted[i];
        if (b && b.count > 0) {
          colors.push({ r: Math.round(b.r / b.count), g: Math.round(b.g / b.count), b: Math.round(b.b / b.count) });
        } else {
          colors.push(fallback);
        }
      }
      resolve(colors);
    };
    img.onerror = () => resolve([{ r: 124, g: 77, b: 255 }, { r: 76, g: 40, b: 180 }, { r: 30, g: 15, b: 90 }]);
    img.src = imageUrl;
  });
}

/**
 * Extract dominant + top-3 colors in a single image load & canvas pass.
 * Avoids duplicate image loading and double canvas operations.
 */
export function extractColors(imageUrl: string): Promise<{ dominant: RGB; top3: RGB[] }> {
  return new Promise((resolve) => {
    const fallback: RGB = { r: 124, g: 77, b: 255 };
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const size = 64;
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        resolve({ dominant: fallback, top3: [fallback, { r: 76, g: 40, b: 180 }, { r: 30, g: 15, b: 90 }] });
        return;
      }

      ctx.drawImage(img, 0, 0, size, size);
      const data = ctx.getImageData(0, 0, size, size).data;

      const buckets: Map<string, { r: number; g: number; b: number; count: number }> = new Map();
      for (let i = 0; i < data.length; i += 16) {
        const r = Math.round(data[i] / 32) * 32;
        const g = Math.round(data[i + 1] / 32) * 32;
        const b = Math.round(data[i + 2] / 32) * 32;

        const brightness = (r + g + b) / 3;
        if (brightness < 30 || brightness > 230) continue;
        const saturation = Math.max(r, g, b) - Math.min(r, g, b);
        if (saturation < 20) continue;

        const key = `${r},${g},${b}`;
        const existing = buckets.get(key);
        if (existing) {
          existing.r += data[i];
          existing.g += data[i + 1];
          existing.b += data[i + 2];
          existing.count++;
        } else {
          buckets.set(key, { r: data[i], g: data[i + 1], b: data[i + 2], count: 1 });
        }
      }

      const sorted = [...buckets.values()].sort((a, b) => b.count - a.count);

      // Dominant color (top bucket)
      const best = sorted[0];
      const dominant = best && best.count > 0
        ? { r: Math.round(best.r / best.count), g: Math.round(best.g / best.count), b: Math.round(best.b / best.count) }
        : fallback;

      // Top 3 colors
      const top3: RGB[] = [];
      for (let i = 0; i < 3; i++) {
        const b = sorted[i];
        if (b && b.count > 0) {
          top3.push({ r: Math.round(b.r / b.count), g: Math.round(b.g / b.count), b: Math.round(b.b / b.count) });
        } else {
          top3.push(fallback);
        }
      }

      resolve({ dominant, top3 });
    };
    img.onerror = () => resolve({ dominant: fallback, top3: [fallback, { r: 76, g: 40, b: 180 }, { r: 30, g: 15, b: 90 }] });
    img.src = imageUrl;
  });
}
