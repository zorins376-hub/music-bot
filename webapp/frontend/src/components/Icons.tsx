/**
 * Unified SVG Icon Set
 * Consistent stroke-based icons for the music player UI
 */

interface IconProps {
  size?: number;
  color?: string;
  strokeWidth?: number;
}

// Music note icon (replaces ♫)
export const IconMusic = ({ size = 24, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18V5l12-2v13"/>
    <circle cx="6" cy="18" r="3"/>
    <circle cx="18" cy="16" r="3"/>
  </svg>
);

// Single music note (replaces ♪)
export const IconMusicNote = ({ size = 24, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18V5l12-2v13"/>
    <circle cx="6" cy="18" r="3"/>
  </svg>
);

// Drag handle icon (replaces ☰)
export const IconDragHandle = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round">
    <line x1="4" y1="8" x2="20" y2="8"/>
    <line x1="4" y1="16" x2="20" y2="16"/>
  </svg>
);

// Back arrow icon (replaces ←)
export const IconArrowLeft = ({ size = 20, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <line x1="19" y1="12" x2="5" y2="12"/>
    <polyline points="12 19 5 12 12 5"/>
  </svg>
);

// Target/Drop icon (replaces 🎯)
export const IconTarget = ({ size = 16, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <circle cx="12" cy="12" r="6"/>
    <circle cx="12" cy="12" r="2"/>
  </svg>
);

// Swipe left indicator
export const IconSwipeLeft = ({ size = 16, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15 18 9 12 15 6"/>
    <line x1="21" y1="12" x2="9" y2="12"/>
  </svg>
);

// Trash/Delete icon
export const IconTrash = ({ size = 24, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6"/>
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    <line x1="10" y1="11" x2="10" y2="17"/>
    <line x1="14" y1="11" x2="14" y2="17"/>
  </svg>
);

// Chevron up/expand
export const IconChevronUp = ({ size = 20, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="18 15 12 9 6 15"/>
  </svg>
);

// Info hint icon
export const IconInfo = ({ size = 16, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="16" x2="12" y2="12"/>
    <line x1="12" y1="8" x2="12.01" y2="8"/>
  </svg>
);

// Equalizer bars (animated)
export const IconEqualizer = ({ size = 20, color = "currentColor", animated = true }: IconProps & { animated?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
    <rect x="4" y="10" width="4" height="10" rx="1" style={animated ? { animation: "eq1 0.4s ease infinite alternate" } : {}}>
      {animated && <animate attributeName="height" values="10;16;10" dur="0.4s" repeatCount="indefinite"/>}
    </rect>
    <rect x="10" y="6" width="4" height="14" rx="1">
      {animated && <animate attributeName="height" values="14;8;14" dur="0.5s" repeatCount="indefinite"/>}
    </rect>
    <rect x="16" y="8" width="4" height="12" rx="1">
      {animated && <animate attributeName="height" values="12;18;12" dur="0.35s" repeatCount="indefinite"/>}
    </rect>
  </svg>
);

export const IconCrown = ({ size = 16, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 8l4.5 4 4.5-7 4.5 7L21 8l-2 10H5L3 8z"/>
    <line x1="7" y1="18" x2="17" y2="18"/>
  </svg>
);

export const IconShield = ({ size = 16, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l7 3v6c0 4.5-2.8 7.9-7 9-4.2-1.1-7-4.5-7-9V6l7-3z"/>
    <path d="M9.5 12l1.7 1.7L14.8 10"/>
  </svg>
);

// Wave icon for AI DJ
export const IconWave = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 12h4l3-9 4 18 3-9h4"/>
  </svg>
);

// Heart icon
export const IconHeart = ({ size = 24, color = "currentColor", filled = false }: IconProps & { filled?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? color : "none"} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

// Share icon
export const IconShare = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="18" cy="5" r="3"/>
    <circle cx="6" cy="12" r="3"/>
    <circle cx="18" cy="19" r="3"/>
    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
  </svg>
);

// Image/Story icon
export const IconImage = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21 15 16 10 5 21"/>
  </svg>
);

// Moon/Sleep icon
export const IconMoon = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
);

// Lyrics/Text icon
export const IconLyrics = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
    <polyline points="10 9 9 9 8 9"/>
  </svg>
);

// Loading spinner
export const IconSpinner = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} style={{ animation: "spin 1s linear infinite" }}>
    <circle cx="12" cy="12" r="10" strokeOpacity="0.25"/>
    <path d="M12 2a10 10 0 0 1 10 10" strokeOpacity="1"/>
  </svg>
);

// Search icon
export const IconSearch = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8"/>
    <line x1="21" y1="21" x2="16.65" y2="16.65"/>
  </svg>
);

// Lime / citrus icon (for Tequila theme)
export const IconLime = ({ size = 18, color = "currentColor", strokeWidth = 1.8 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="9"/>
    <path d="M12 3c0 5 4 9 9 9"/>
    <path d="M12 3c0 5 -4 9 -9 9"/>
    <path d="M12 21c0 -5 4 -9 9 -9"/>
    <path d="M12 21c0 -5 -4 -9 -9 -9"/>
    <circle cx="12" cy="12" r="2.5"/>
  </svg>
);

// Sunrise icon (for theme switch → Tequila)
export const IconSunrise = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 18a5 5 0 0 0-10 0"/>
    <line x1="12" y1="9" x2="12" y2="2"/>
    <line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/>
    <line x1="1" y1="18" x2="3" y2="18"/>
    <line x1="21" y1="18" x2="23" y2="18"/>
    <line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/>
    <line x1="23" y1="22" x2="1" y2="22"/>
    <polyline points="8 6 12 2 16 6"/>
  </svg>
);

// Close / X icon
export const IconClose = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"/>
    <line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
);

// Upload / Share out icon
export const IconUpload = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="17 8 12 3 7 8"/>
    <line x1="12" y1="3" x2="12" y2="15"/>
  </svg>
);

// Sad face icon
export const IconSad = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <path d="M16 16s-1.5-2-4-2-4 2-4 2"/>
    <line x1="9" y1="9" x2="9.01" y2="9"/>
    <line x1="15" y1="9" x2="15.01" y2="9"/>
  </svg>
);

// Play triangle icon (small, for nav)
export const IconPlaySmall = ({ size = 12, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} stroke="none">
    <polygon points="6,3 20,12 6,21"/>
  </svg>
);

// Diamond icon
export const IconDiamond = ({ size = 12, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} stroke="none">
    <polygon points="12,2 22,12 12,22 2,12"/>
  </svg>
);

// Spectrum/Visualizer icon
export const IconSpectrum = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round">
    <line x1="3" y1="20" x2="3" y2="14"/><line x1="6" y1="20" x2="6" y2="8"/>
    <line x1="9" y1="20" x2="9" y2="12"/><line x1="12" y1="20" x2="12" y2="4"/>
    <line x1="15" y1="20" x2="15" y2="10"/><line x1="18" y1="20" x2="18" y2="6"/>
    <line x1="21" y1="20" x2="21" y2="16"/>
  </svg>
);

// 3D/Spatial Audio icon
export const IconSpatial = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 12a5 5 0 0 1 5-5"/>
    <path d="M2 12a5 5 0 0 0 5 5"/>
    <path d="M22 12a5 5 0 0 0-5-5"/>
    <path d="M22 12a5 5 0 0 1-5 5"/>
    <circle cx="12" cy="12" r="3"/>
    <path d="M9 12h-3" opacity="0.5"/><path d="M18 12h-3" opacity="0.5"/>
  </svg>
);

// Speed/Playback rate icon
export const IconSpeed = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 6 12 12 16 14"/>
  </svg>
);

// Bass Boost icon
export const IconBassBoost = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18V5l12-2v13"/>
    <circle cx="6" cy="18" r="3"/>
    <circle cx="18" cy="16" r="3"/>
    <path d="M2 8l3 3 3-3" strokeWidth="2.5"/>
  </svg>
);

// Mood/Emotion icon
export const IconMood = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
    <line x1="9" y1="9" x2="9.01" y2="9"/>
    <line x1="15" y1="9" x2="15.01" y2="9"/>
  </svg>
);

// Party/Celebration icon
export const IconParty = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
  </svg>
);

// Microphone/Karaoke icon
export const IconMic = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
    <line x1="12" y1="19" x2="12" y2="23"/>
    <line x1="8" y1="23" x2="16" y2="23"/>
  </svg>
);

// Hi-Res Audio badge icon
export const IconHiRes = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="6" width="20" height="12" rx="3"/>
    <text x="12" y="14.5" fontSize="7" fill={color} stroke="none" fontWeight="bold" textAnchor="middle">HR</text>
  </svg>
);

// ─── MOOD ICONS (SVG replacements for emoji) ──────────────

/** 🌊 Chill — wave */
export const IconMoodChill = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 12c1.5-2 3-3 4.5-1s3 1 4.5-1 3-3 4.5-1 3 1 4.5-1"/>
    <path d="M2 17c1.5-2 3-3 4.5-1s3 1 4.5-1 3-3 4.5-1 3 1 4.5-1"/>
    <path d="M2 7c1.5-2 3-3 4.5-1s3 1 4.5-1 3-3 4.5-1 3 1 4.5-1"/>
  </svg>
);

/** ⚡ Energy — lightning bolt */
export const IconMoodEnergy = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
  </svg>
);

/** 🎯 Focus — crosshair target */
export const IconMoodFocus = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <circle cx="12" cy="12" r="6"/>
    <circle cx="12" cy="12" r="2"/>
    <line x1="12" y1="2" x2="12" y2="5"/>
    <line x1="12" y1="19" x2="12" y2="22"/>
    <line x1="2" y1="12" x2="5" y2="12"/>
    <line x1="19" y1="12" x2="22" y2="12"/>
  </svg>
);

/** 💜 Romance — heart */
export const IconMoodRomance = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 1 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

/** 🌧 Melancholy — cloud with rain */
export const IconMoodMelancholy = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 10a4 4 0 0 0-7.46-2A3.5 3.5 0 1 0 7 14h11a3 3 0 0 0 0-6z"/>
    <line x1="8" y1="17" x2="7" y2="20"/>
    <line x1="12" y1="17" x2="11" y2="20"/>
    <line x1="16" y1="17" x2="15" y2="20"/>
  </svg>
);

/** 🎉 Party — confetti popper */
export const IconMoodParty = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="3 21 7 7 17 17 3 21"/>
    <line x1="11" y1="3" x2="11" y2="6"/>
    <line x1="17" y1="5" x2="15" y2="7.5"/>
    <line x1="21" y1="11" x2="18" y2="11"/>
    <circle cx="14" cy="3" r="1" fill={color} stroke="none"/>
    <circle cx="20" cy="7" r="1" fill={color} stroke="none"/>
    <circle cx="21" cy="14" r="1" fill={color} stroke="none"/>
  </svg>
);
