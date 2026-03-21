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
    bgImage: "/tequila-bg.webp",
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

/** Derived color helpers — replaces binary `warm = themeId === "tequila"` in components */
export interface ThemeColors {
  textColor: string;
  hintColor: string;
  cardBg: string;
  cardBorder: string;
  activeBg: string;
  accentGradient: string;
  highlight: string;
  glowShadow: string;
  accentBorderAlpha: string;
  coverPlaceholderBg: string;
  isTequila: boolean;
}

export function themeColors(theme: Theme, accentColor?: string): ThemeColors {
  const accent = accentColor || theme.accent;
  const isTequila = theme.id === "tequila";

  // Per-theme card border colors
  const borderMap: Record<string, string> = {
    blackroom: "rgba(124, 77, 255, 0.1)",
    tequila:   "rgba(255, 213, 79, 0.12)",
    neon:      "rgba(0, 230, 255, 0.12)",
    midnight:  "rgba(168, 85, 247, 0.1)",
    emerald:   "rgba(52, 211, 153, 0.1)",
  };

  const glowMap: Record<string, string> = {
    blackroom: "0 4px 20px rgba(124, 77, 255, 0.2)",
    tequila:   "0 4px 24px rgba(255, 143, 0, 0.3)",
    neon:      "0 4px 24px rgba(0, 230, 255, 0.25), 0 0 40px rgba(255, 0, 255, 0.1)",
    midnight:  "0 4px 20px rgba(168, 85, 247, 0.25)",
    emerald:   "0 4px 20px rgba(52, 211, 153, 0.2)",
  };

  const gradientMap: Record<string, string> = {
    blackroom: `linear-gradient(135deg, ${accent}, #b388ff)`,
    tequila:   "linear-gradient(135deg, #ff8f00, #ffd54f)",
    neon:      "linear-gradient(135deg, #00e6ff, #ff00ff)",
    midnight:  "linear-gradient(135deg, #a855f7, #ec4899)",
    emerald:   "linear-gradient(135deg, #34d399, #06b6d4)",
  };

  const activeBgMap: Record<string, string> = {
    blackroom: `linear-gradient(135deg, ${accent}, rgba(124, 77, 255, 0.3))`,
    tequila:   "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,167,38,0.2))",
    neon:      "linear-gradient(135deg, rgba(0,230,255,0.25), rgba(255,0,255,0.15))",
    midnight:  "linear-gradient(135deg, rgba(168,85,247,0.3), rgba(236,72,153,0.15))",
    emerald:   "linear-gradient(135deg, rgba(52,211,153,0.25), rgba(6,182,212,0.15))",
  };

  const placeholderMap: Record<string, string> = {
    blackroom: "rgba(124, 77, 255, 0.06)",
    tequila:   "rgba(255, 213, 79, 0.06)",
    neon:      "rgba(0, 230, 255, 0.06)",
    midnight:  "rgba(168, 85, 247, 0.06)",
    emerald:   "rgba(52, 211, 153, 0.06)",
  };

  const id = theme.id;
  return {
    textColor: theme.textColor,
    hintColor: theme.hintColor,
    cardBg: theme.secondaryBg,
    cardBorder: `1px solid ${borderMap[id] || borderMap.blackroom}`,
    activeBg: activeBgMap[id] || activeBgMap.blackroom,
    accentGradient: gradientMap[id] || gradientMap.blackroom,
    highlight: isTequila ? "#ffd54f" : accent,
    glowShadow: glowMap[id] || glowMap.blackroom,
    accentBorderAlpha: borderMap[id] || borderMap.blackroom,
    coverPlaceholderBg: placeholderMap[id] || placeholderMap.blackroom,
    isTequila,
  };
}

/** Semantic colors that don't change with theme */
export const semanticColors = {
  error: "#f44336",
  errorBg: "rgba(244, 67, 54, 0.1)",
  success: "#81c784",
  successBg: "rgba(76, 175, 80, 0.15)",
  liveRed: "#ff3232",
  livePulse: "#ff4444",
  warning: "#ffb300",
  white: "#fff",
} as const;

/** Apply the active theme as CSS custom properties on :root.
 *  Components can then use var(--theme-bg), var(--theme-accent), etc.  */
export function applyThemeCSSVars(theme: Theme): void {
  const s = document.documentElement.style;
  s.setProperty("--theme-bg", theme.bgColor);
  s.setProperty("--theme-bg-secondary", theme.secondaryBg);
  s.setProperty("--theme-text", theme.textColor);
  s.setProperty("--theme-hint", theme.hintColor);
  s.setProperty("--theme-accent", theme.accent);
  s.setProperty("--theme-accent-alpha", theme.accentAlpha);
  s.setProperty("--theme-glass-bg", theme.glassBg);
  s.setProperty("--theme-nav-inactive", theme.navInactiveBg);
  s.setProperty("--theme-vis-start", theme.visualizerGradient[0]);
  s.setProperty("--theme-vis-end", theme.visualizerGradient[1]);
}
