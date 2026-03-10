export interface Theme {
  id: string;
  name: string;
  subtitle?: string;
  /** Background color for the app body */
  bgColor: string;
  /** Secondary/card background */
  secondaryBg: string;
  /** Primary text color */
  textColor: string;
  /** Hint / muted text */
  hintColor: string;
  /** Default accent (used when no cover color extracted) */
  accent: string;
  accentAlpha: string;
  /** Optional background image URL */
  bgImage?: string;
  /** Overlay on top of background image */
  bgOverlay?: string;
  /** Gradient for visualizer bars */
  visualizerGradient: [string, string];
  /** Glass panel background */
  glassBg: string;
  /** Nav button inactive background */
  navInactiveBg: string;
}

export const themes: Theme[] = [
  {
    id: "blackroom",
    name: "BLACK ROOM",
    bgColor: "#1a1a2e",
    secondaryBg: "#2a2a3e",
    textColor: "#eee",
    hintColor: "#aaa",
    accent: "rgb(124, 77, 255)",
    accentAlpha: "rgba(124, 77, 255, 0.4)",
    visualizerGradient: ["rgb(124, 77, 255)", "#e040fb"],
    glassBg: "rgba(20, 20, 30, 0.92)",
    navInactiveBg: "#2a2a3e",
  },
  {
    id: "tequila",
    name: "𝐓 𝐄 𝐐 𝐔 𝐈 𝐋 𝐀",
    subtitle: "inspired by 𝗧𝗘𝗤𝗨𝗜𝗟𝗔 𝗦𝗨𝗡𝗦𝗛𝗜𝗡𝗘.",
    bgColor: "#1a120b",
    secondaryBg: "rgba(40, 25, 15, 0.75)",
    textColor: "#fef0e0",
    hintColor: "#c8a882",
    accent: "rgb(255, 167, 38)",
    accentAlpha: "rgba(255, 167, 38, 0.4)",
    bgImage: "/tequila-bg.png",
    bgOverlay: "linear-gradient(180deg, rgba(26,18,11,0.55) 0%, rgba(26,18,11,0.85) 100%)",
    visualizerGradient: ["#ff6d00", "#ffd54f"],
    glassBg: "rgba(40, 25, 15, 0.88)",
    navInactiveBg: "rgba(40, 25, 15, 0.7)",
  },
  {
    id: "neon",
    name: "NEON CITY",
    subtitle: "cyberpunk vibes",
    bgColor: "#0a0a1a",
    secondaryBg: "rgba(20, 10, 40, 0.8)",
    textColor: "#e0f0ff",
    hintColor: "#6ecfff",
    accent: "rgb(0, 230, 255)",
    accentAlpha: "rgba(0, 230, 255, 0.35)",
    visualizerGradient: ["#00e6ff", "#ff00ff"],
    glassBg: "rgba(10, 10, 30, 0.92)",
    navInactiveBg: "rgba(20, 10, 40, 0.7)",
  },
  {
    id: "midnight",
    name: "MIDNIGHT VELVET",
    subtitle: "deep dark luxury",
    bgColor: "#0c0c14",
    secondaryBg: "rgba(18, 14, 28, 0.85)",
    textColor: "#e8e4f0",
    hintColor: "#8b7faa",
    accent: "rgb(168, 85, 247)",
    accentAlpha: "rgba(168, 85, 247, 0.35)",
    visualizerGradient: ["#a855f7", "#ec4899"],
    glassBg: "rgba(12, 12, 20, 0.94)",
    navInactiveBg: "rgba(18, 14, 28, 0.7)",
  },
  {
    id: "emerald",
    name: "EMERALD LOUNGE",
    subtitle: "green luxury",
    bgColor: "#0a1a0f",
    secondaryBg: "rgba(12, 30, 18, 0.8)",
    textColor: "#e0f5e8",
    hintColor: "#6dbb8a",
    accent: "rgb(52, 211, 153)",
    accentAlpha: "rgba(52, 211, 153, 0.35)",
    visualizerGradient: ["#34d399", "#06b6d4"],
    glassBg: "rgba(10, 20, 14, 0.92)",
    navInactiveBg: "rgba(12, 30, 18, 0.7)",
  },
];

const STORAGE_KEY = "br_theme";

export function getSavedThemeId(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || "blackroom";
  } catch {
    return "blackroom";
  }
}

export function saveThemeId(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {}
}

export function getThemeById(id: string): Theme {
  return themes.find((t) => t.id === id) || themes[0];
}
