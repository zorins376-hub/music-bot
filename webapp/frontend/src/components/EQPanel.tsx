/**
 * EQPanel — Audio quality selector + EQ presets + Bypass toggle.
 * Extracted from Player.tsx for modularity (AUDIT #11).
 */
import type { EqPreset } from "../api";
import { haptic, AudioBadge, QUALITY_OPTIONS, EQ_OPTIONS, formatEqPresetLabel } from "./PlayerHelpers";
import { IconEqualizer } from "./Icons";

export interface EQPanelProps {
  quality: string;
  eqPreset: EqPreset;
  bypassProcessing: boolean;
  accentColor: string;
  accentColorAlpha: string;
  warm: boolean;
  isAdmin: boolean;
  onQualityChange?: (quality: string) => void;
  onEqPresetChange?: (preset: EqPreset) => void;
  onBypassToggle?: (on: boolean) => void;
}

export function EQPanel({
  quality, eqPreset, bypassProcessing, accentColor, accentColorAlpha,
  warm, isAdmin, onQualityChange, onEqPresetChange, onBypassToggle,
}: EQPanelProps) {
  const qualityLabel = quality === "auto" ? "Auto" : `${quality} kbps`;
  const eqPresetLabel = formatEqPresetLabel(eqPreset);

  return (
    <div style={{
      marginTop: 18,
      padding: warm ? "16px 16px 14px" : "16px",
      borderRadius: 22,
      display: "flex",
      flexDirection: "column",
      gap: 14,
      background: warm ? "linear-gradient(180deg, rgba(40, 25, 15, 0.78), rgba(28, 18, 12, 0.72))" : "linear-gradient(180deg, rgba(124, 77, 255, 0.12), rgba(32, 24, 50, 0.32))",
      border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : "1px solid rgba(179, 136, 255, 0.16)",
      boxShadow: warm ? "0 16px 40px rgba(0,0,0,0.2)" : `0 16px 40px ${accentColorAlpha}`,
      backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, textAlign: "left" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: warm ? "#ffd54f" : accentColor, fontSize: 15, fontWeight: 700, letterSpacing: 0.6 }}>
            <IconEqualizer size={18} color={warm ? "#ffd54f" : accentColor} animated={false} />
            <span>Audio Pro</span>
          </div>
          <div style={{ fontSize: 12, color: warm ? "#c8a882" : "var(--tg-theme-hint-color, #aaa)" }}>
            {isAdmin ? "Advanced sound for admin access" : "Premium sound scene with curated EQ presets"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <AudioBadge label={qualityLabel} active warm={warm} />
          <AudioBadge label={bypassProcessing ? "RAW" : eqPresetLabel} active warm={warm} />
        </div>
      </div>

      {/* Bypass / RAW mode toggle */}
      <button
        onClick={() => { haptic("medium"); onBypassToggle?.(!bypassProcessing); }}
        style={{
          padding: "10px 16px",
          borderRadius: 16,
          border: bypassProcessing
            ? (warm ? "1px solid #ffd54f" : `1px solid ${accentColor}`)
            : (warm ? "1px solid rgba(255, 213, 79, 0.18)" : "1px solid rgba(179, 136, 255, 0.16)"),
          background: bypassProcessing
            ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))" : `linear-gradient(135deg, ${accentColor}, #e040fb)`)
            : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
          color: bypassProcessing ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          transition: "all 0.3s ease",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          {bypassProcessing ? (
            <>
              <line x1="1" y1="1" x2="23" y2="23"/>
              <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/>
              <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2c0 .76-.13 1.49-.35 2.17"/>
              <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
            </>
          ) : (
            <>
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
            </>
          )}
        </svg>
        {bypassProcessing ? "RAW · Без обработки" : "Включить RAW (без обработки)"}
      </button>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: warm ? "#c8a882" : "#bca8ff" }}>
          Stream quality
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
          {QUALITY_OPTIONS.map((value) => {
            const active = quality === value;
            return (
              <button
                key={value}
                onClick={() => onQualityChange?.(value)}
                style={{
                  padding: warm ? "10px 8px" : "9px 8px",
                  borderRadius: 16,
                  border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : `1px solid ${active ? accentColor : accentColorAlpha}`,
                  background: active
                    ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))" : `linear-gradient(135deg, ${accentColor}, #e040fb)`)
                    : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
                  color: active ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: active ? 700 : 600,
                }}
              >
                {value === "auto" ? "Auto" : `${value}`}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: warm ? "#c8a882" : "#bca8ff" }}>
          EQ presets
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
          {EQ_OPTIONS.map((option) => {
            const active = eqPreset === option.value;
            return (
              <button
                key={option.value}
                onClick={() => onEqPresetChange?.(option.value)}
                style={{
                  padding: warm ? "11px 10px" : "10px",
                  minHeight: 64,
                  borderRadius: 18,
                  border: warm ? "1px solid rgba(255, 213, 79, 0.18)" : `1px solid ${active ? accentColor : accentColorAlpha}`,
                  background: active
                    ? (warm ? "linear-gradient(135deg, rgba(255,109,0,0.34), rgba(255,213,79,0.22))" : `linear-gradient(135deg, ${accentColor}, rgba(224,64,251,0.92))`)
                    : (warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)"),
                  color: active ? "#fff" : (warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)"),
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  justifyContent: "center",
                  gap: 4,
                  textAlign: "left",
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.1 }}>{option.label}</span>
                <span style={{ fontSize: 10, opacity: active ? 0.95 : 0.72, textTransform: "uppercase", letterSpacing: 0.6 }}>{option.note}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
