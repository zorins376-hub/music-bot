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

// Lime / citrus icon in cross-section (for Tequila theme)
export const IconLime = ({ size = 18, color = "currentColor", strokeWidth = 1.8 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    {/* Outer peel */}
    <circle cx="12" cy="12" r="10"/>
    {/* Inner pith */}
    <circle cx="12" cy="12" r="8" strokeDasharray="1 3" strokeWidth="1" opacity="0.8"/>
    {/* Center core */}
    <circle cx="12" cy="12" r="2" fill={color} fillOpacity="0.1"/>
    {/* Segments (8 slices) */}
    <path d="M12 4 L12 10" />
    <path d="M12 20 L12 14" />
    <path d="M4 12 L10 12" />
    <path d="M20 12 L14 12" />
    <path d="M6.34 6.34 L10.59 10.59" />
    <path d="M17.66 17.66 L13.41 13.41" />
    <path d="M17.66 6.34 L13.41 10.59" />
    <path d="M6.34 17.66 L10.59 13.41" />
    {/* Juice droplets (dots) in segments */}
    <circle cx="14" cy="8" r="0.5" fill={color} stroke="none"/>
    <circle cx="10" cy="16" r="0.5" fill={color} stroke="none"/>
    <circle cx="8" cy="10" r="0.5" fill={color} stroke="none"/>
    <circle cx="16" cy="14" r="0.5" fill={color} stroke="none"/>
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

/** 📊 Chart — bar chart icon */
export const IconChart = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="12" width="4" height="9" rx="1" />
    <rect x="10" y="6" width="4" height="15" rx="1" />
    <rect x="17" y="3" width="4" height="18" rx="1" />
  </svg>
);

/** ➕ Plus icon */
export const IconPlus = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

/** 📈 Trending up icon */
export const IconTrending = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
    <polyline points="17 6 23 6 23 12"/>
  </svg>
);

/** 🔍 Similar/Discover icon */
export const IconSimilar = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <path d="M8 12h8"/>
    <path d="M12 8v8"/>
  </svg>
);

/** 🚀 Rocket/Launch icon */
export const IconRocket = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/>
    <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
    <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
    <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
  </svg>
);

// ─── PARTY BANNER ICONS ──────────────────────────────────

/** 🎧 Headphones icon */
export const IconHeadphones = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 18v-6a9 9 0 0 1 18 0v6"/>
    <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>
  </svg>
);

/** 🏠 Home/Room icon */
export const IconHome = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
    <polyline points="9 22 9 12 15 12 15 22"/>
  </svg>
);

/** 💬 Chat/Message icon */
export const IconChat = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
  </svg>
);

/** 🤖 Robot/AI icon */
export const IconRobot = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="10" rx="2"/>
    <circle cx="12" cy="5" r="2"/>
    <path d="M12 7v4"/>
    <line x1="8" y1="16" x2="8" y2="16"/>
    <line x1="16" y1="16" x2="16" y2="16"/>
  </svg>
);

/** 🔥 Fire/Hot icon */
export const IconFire = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>
  </svg>
);

/** 📺 TV/Monitor icon */
export const IconTV = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="7" width="20" height="15" rx="2" ry="2"/>
    <polyline points="17 2 12 7 7 2"/>
  </svg>
);

/** 🎭 Stage/Theater icon */
export const IconStage = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="9" cy="9" r="5"/>
    <path d="M14 9a5 5 0 0 1 5 5"/>
    <circle cx="17" cy="17" r="3"/>
    <path d="M6 14a5 5 0 0 0-3 5"/>
  </svg>
);

/** 📋 Clipboard/History icon */
export const IconClipboard = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
    <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
  </svg>
);

/** 🔗 Link icon */
export const IconLink = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
  </svg>
);

/** 🔔 Bell/Notification icon */
export const IconBell = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
    <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
  </svg>
);

/** 👥 Users/People icon */
export const IconUsers = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>
);

/** 💾 Save/Download icon */
export const IconSave = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
    <polyline points="17 21 17 13 7 13 7 21"/>
    <polyline points="7 3 7 8 15 8"/>
  </svg>
);

/** 🏁 Flag/Finish icon */
export const IconFlag = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
    <line x1="4" y1="22" x2="4" y2="15"/>
  </svg>
);

/** ⏱ Clock/Duration icon */
export const IconClock = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 6 12 12 16 14"/>
  </svg>
);

/** ✨ Sparkles/Magic icon */
export const IconSparkles = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>
    <path d="M5 3v4"/>
    <path d="M19 17v4"/>
    <path d="M3 5h4"/>
    <path d="M17 19h4"/>
  </svg>
);

/** 🔄 Sync/Refresh icon */
export const IconSync = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2v6h-6"/>
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
    <path d="M3 22v-6h6"/>
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
  </svg>
);

/** 🏆 Trophy icon */
export const IconTrophy = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>
    <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>
    <path d="M4 22h16"/>
    <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>
    <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>
    <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>
  </svg>
);

/** 🪩 Disco ball icon */
export const IconDisco = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="9"/>
    <path d="M12 3v18"/>
    <path d="M3.6 9h16.8"/>
    <path d="M3.6 15h16.8"/>
    <path d="M12 3a14.3 14.3 0 0 1 0 18"/>
    <path d="M12 3a14.3 14.3 0 0 0 0 18"/>
  </svg>
);

/**  Wave/Hello icon */
export const IconHello = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2"/>
    <path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2"/>
    <path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8"/>
    <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>
  </svg>
);

/** 🖼 Picture/Poster icon */
export const IconPicture = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21 15 16 10 5 21"/>
  </svg>
);

/** 🧹 Broom/Clean icon */
export const IconBroom = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="m13 11 9-9"/>
    <path d="m15 13-3-3"/>
    <path d="M14 4 7.5 10.5"/>
    <path d="m4 20 6-6"/>
    <path d="m2 22 2-2"/>
    <path d="M6 18c-2.5-2.5-2.5-5 0-7l1 1c-2 2-2 4 0 6"/>
    <path d="M10 14c2-2 4-2 6 0l-1 1c-2-2-4-2-6 0"/>
  </svg>
);

/** ⚡ Lightning/Bolt icon */
export const IconBolt = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
  </svg>
);

/** ❤️ Heart filled icon */
export const IconHeartFilled = ({ size = 18, color = "currentColor" }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);

/** ✎ Edit/Pencil icon */
export const IconEdit = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
  </svg>
);

/** 👤 User icon */
export const IconUser = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
    <circle cx="12" cy="7" r="4"/>
  </svg>
);

/** ↓ Download icon */
export const IconDownload = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="7 10 12 15 17 10"/>
    <line x1="12" y1="15" x2="12" y2="3"/>
  </svg>
);

/** ★ Star icon */
export const IconStar = ({ size = 18, color = "currentColor", filled = false }: IconProps & { filled?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? color : "none"} stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
  </svg>
);

/** 🎯 Compass/Discover icon */
export const IconDiscover = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>
  </svg>
);

/** ✓ Check/checkmark icon */
export const IconCheck = ({ size = 18, color = "currentColor", strokeWidth = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);
