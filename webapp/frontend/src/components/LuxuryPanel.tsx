/**
 * LuxuryPanel — Premium audio effects: spectrum, bass, party, warmth, reverb,
 * karaoke, speed, mood, crossfade, cover mode, spatial panner.
 * Extracted from Player.tsx for modularity (AUDIT #11).
 */
import { haptic } from "./PlayerHelpers";
import {
  IconSpectrum, IconBassBoost, IconParty, IconFire, IconHiRes,
  IconSpatial, IconMood, IconMoon, IconMic, IconWave, IconSpeed,
  IconMoodChill, IconMoodEnergy, IconMoodFocus, IconMoodRomance,
  IconMoodMelancholy, IconMoodParty,
} from "./Icons";

const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;
const MOOD_OPTIONS = [
  { id: "chill", label: "Chill", icon: (c: string) => <IconMoodChill size={18} color={c} /> },
  { id: "energy", label: "Energy", icon: (c: string) => <IconMoodEnergy size={18} color={c} /> },
  { id: "focus", label: "Focus", icon: (c: string) => <IconMoodFocus size={18} color={c} /> },
  { id: "romance", label: "Romance", icon: (c: string) => <IconMoodRomance size={18} color={c} /> },
  { id: "melancholy", label: "Melancholy", icon: (c: string) => <IconMoodMelancholy size={18} color={c} /> },
  { id: "party", label: "Party", icon: (c: string) => <IconMoodParty size={18} color={c} /> },
];

export interface LuxuryPanelProps {
  warm: boolean;
  accentColor: string;
  showSpectrum: boolean;
  onToggleSpectrum?: () => void;
  bassBoost: boolean;
  onBassBoost?: (on: boolean) => void;
  partyMode: boolean;
  onPartyMode?: (on: boolean) => void;
  tapeWarmth: boolean;
  onTapeWarmth?: (on: boolean) => void;
  airBand: boolean;
  onAirBand?: (on: boolean) => void;
  stereoWiden: boolean;
  onStereoWiden?: (on: boolean) => void;
  softClip: boolean;
  onSoftClip?: (on: boolean) => void;
  nightMode: boolean;
  onNightMode?: (on: boolean) => void;
  reverbEnabled: boolean;
  onReverb?: (on: boolean) => void;
  reverbPreset: "studio" | "concert" | "club" | "cathedral";
  onReverbPreset?: (preset: "studio" | "concert" | "club" | "cathedral") => void;
  reverbMix: number;
  onReverbMix?: (mix: number) => void;
  karaokeMode: boolean;
  onKaraokeMode?: (on: boolean) => void;
  crossfadeDuration: number;
  onCrossfadeDuration?: (sec: number) => void;
  coverMode: "default" | "vinyl" | "cd" | "case";
  onCoverMode?: (mode: "default" | "vinyl" | "cd" | "case") => void;
  panValue: number;
  onPanChange?: (value: number) => void;
  playbackSpeed: number;
  onSpeedChange?: (speed: number) => void;
  moodFilter: string | null;
  onMoodChange?: (mood: string | null) => void;
  quality: string;
}

export function LuxuryPanel({
  warm, accentColor,
  showSpectrum, onToggleSpectrum,
  bassBoost, onBassBoost,
  partyMode, onPartyMode,
  tapeWarmth, onTapeWarmth,
  airBand, onAirBand,
  stereoWiden, onStereoWiden,
  softClip, onSoftClip,
  nightMode, onNightMode,
  reverbEnabled, onReverb,
  reverbPreset, onReverbPreset,
  reverbMix, onReverbMix,
  karaokeMode, onKaraokeMode,
  crossfadeDuration, onCrossfadeDuration,
  coverMode, onCoverMode,
  panValue, onPanChange,
  playbackSpeed, onSpeedChange,
  moodFilter, onMoodChange,
  quality,
}: LuxuryPanelProps) {
  const panelBg = warm
    ? "linear-gradient(180deg, rgba(40, 25, 15, 0.78), rgba(28, 18, 12, 0.72))"
    : "linear-gradient(180deg, rgba(124, 77, 255, 0.08), rgba(32, 24, 50, 0.28))";
  const panelBorder = warm
    ? "1px solid rgba(255, 213, 79, 0.18)"
    : "1px solid rgba(179, 136, 255, 0.12)";
  const labelColor = warm ? "#c8a882" : "#bca8ff";
  const activeGrad = warm
    ? "linear-gradient(135deg, rgba(255,109,0,0.35), rgba(255,213,79,0.24))"
    : `linear-gradient(135deg, ${accentColor}, #e040fb)`;
  const inactiveBg = warm ? "rgba(255, 213, 79, 0.05)" : "rgba(124, 77, 255, 0.07)";
  const textColor = warm ? "#fef0e0" : "var(--tg-theme-text-color, #eee)";
  const hlColor = warm ? "#ffd54f" : accentColor;

  return (
    <div style={{
      marginTop: 14,
      padding: warm ? "14px 14px 12px" : "14px",
      borderRadius: 22,
      display: "flex",
      flexDirection: "column",
      gap: 14,
      background: panelBg,
      border: panelBorder,
      backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
    }}>
      {/* Quick Toggles Row */}
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
        <button onClick={onToggleSpectrum} style={{
          padding: "8px 14px", borderRadius: 16,
          border: showSpectrum ? `1px solid ${hlColor}` : panelBorder,
          background: showSpectrum ? activeGrad : inactiveBg,
          color: showSpectrum ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconSpectrum size={14} color={showSpectrum ? "#fff" : hlColor} /> Спектр
        </button>

        <button onClick={() => onBassBoost?.(!bassBoost)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: bassBoost ? `1px solid ${hlColor}` : panelBorder,
          background: bassBoost ? activeGrad : inactiveBg,
          color: bassBoost ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconBassBoost size={14} color={bassBoost ? "#fff" : hlColor} /> Bass+
        </button>

        <button onClick={() => onPartyMode?.(!partyMode)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: partyMode ? `1px solid ${hlColor}` : panelBorder,
          background: partyMode
            ? "linear-gradient(135deg, #ff6d00, #e040fb)"
            : inactiveBg,
          color: partyMode ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
          animation: partyMode ? "partyPulse 1.5s ease-in-out infinite" : "none",
        }}>
          <IconParty size={14} color={partyMode ? "#fff" : hlColor} /> Party
        </button>
      </div>

      {/* Luxury Audio Toggles */}
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
        <button onClick={() => onTapeWarmth?.(!tapeWarmth)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: tapeWarmth ? `1px solid ${hlColor}` : panelBorder,
          background: tapeWarmth ? (warm ? "linear-gradient(135deg, #ff8f00, #ffb300)" : activeGrad) : inactiveBg,
          color: tapeWarmth ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconFire size={14} color={tapeWarmth ? "#fff" : hlColor} /> Warmth
        </button>
        <button onClick={() => onAirBand?.(!airBand)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: airBand ? `1px solid ${hlColor}` : panelBorder,
          background: airBand ? activeGrad : inactiveBg,
          color: airBand ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconHiRes size={14} color={airBand ? "#fff" : hlColor} /> Air
        </button>
        <button onClick={() => onStereoWiden?.(!stereoWiden)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: stereoWiden ? `1px solid ${hlColor}` : panelBorder,
          background: stereoWiden ? activeGrad : inactiveBg,
          color: stereoWiden ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconSpatial size={14} color={stereoWiden ? "#fff" : hlColor} /> Wide
        </button>
        <button onClick={() => onSoftClip?.(!softClip)} style={{
          padding: "8px 14px", borderRadius: 16,
          border: softClip ? `1px solid ${hlColor}` : panelBorder,
          background: softClip ? activeGrad : inactiveBg,
          color: softClip ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconMood size={14} color={softClip ? "#fff" : hlColor} /> Limiter
        </button>
      </div>

      {/* Pro Audio Effects */}
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
        <button onClick={() => { haptic("medium"); onNightMode?.(!nightMode); }} style={{
          padding: "8px 14px", borderRadius: 16,
          border: nightMode ? `1px solid ${hlColor}` : panelBorder,
          background: nightMode ? (warm ? "linear-gradient(135deg, #1a237e, #283593)" : "linear-gradient(135deg, #1a237e, #4527a0)") : inactiveBg,
          color: nightMode ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconMoon size={14} color={nightMode ? "#fff" : hlColor} /> Night
        </button>
        <button onClick={() => { haptic("medium"); onReverb?.(!reverbEnabled); }} style={{
          padding: "8px 14px", borderRadius: 16,
          border: reverbEnabled ? `1px solid ${hlColor}` : panelBorder,
          background: reverbEnabled ? activeGrad : inactiveBg,
          color: reverbEnabled ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconSpatial size={14} color={reverbEnabled ? "#fff" : hlColor} /> Room
        </button>
        <button onClick={() => { haptic("medium"); onKaraokeMode?.(!karaokeMode); }} style={{
          padding: "8px 14px", borderRadius: 16,
          border: karaokeMode ? `1px solid ${hlColor}` : panelBorder,
          background: karaokeMode ? activeGrad : inactiveBg,
          color: karaokeMode ? "#fff" : textColor,
          fontSize: 12, fontWeight: 600, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <IconMic size={14} color={karaokeMode ? "#fff" : hlColor} /> Karaoke
        </button>
      </div>

      {/* Room Reverb Settings (when active) */}
      {reverbEnabled && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "8px 0" }}>
          <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>
            {(["studio", "concert", "club", "cathedral"] as const).map(preset => {
              const labels = { studio: "Studio", concert: "Concert", club: "Club", cathedral: "Cathedral" };
              const active = reverbPreset === preset;
              return (
                <button key={preset} onClick={() => { haptic("light"); onReverbPreset?.(preset); }} style={{
                  padding: "5px 10px", borderRadius: 12,
                  border: active ? `1px solid ${hlColor}` : panelBorder,
                  background: active ? activeGrad : inactiveBg,
                  color: active ? "#fff" : textColor,
                  fontSize: 10, fontWeight: 600, cursor: "pointer",
                }}>
                  {labels[preset]}
                </button>
              );
            })}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 10, color: labelColor, fontWeight: 600, minWidth: 28 }}>DRY</span>
            <input
              type="range" min={0} max={100} step={5}
              value={Math.round(reverbMix * 100)}
              onInput={(e) => { onReverbMix?.(Number((e.target as HTMLInputElement).value) / 100); }}
              style={{ flex: 1, height: 4, accentColor: hlColor, cursor: "pointer" }}
            />
            <span style={{ fontSize: 10, color: labelColor, fontWeight: 600, minWidth: 28 }}>WET</span>
          </div>
        </div>
      )}

      {/* Crossfade Duration */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
            <IconWave size={14} color={labelColor} /> Crossfade
          </div>
          <span style={{ fontSize: 10, color: labelColor, fontVariantNumeric: "tabular-nums" }}>
            {crossfadeDuration === 0 ? "OFF" : `${crossfadeDuration}s`}
          </span>
        </div>
        <input
          type="range" min={0} max={12} step={1}
          value={crossfadeDuration}
          onInput={(e) => { haptic("light"); onCrossfadeDuration?.(Number((e.target as HTMLInputElement).value)); }}
          style={{ width: "100%", height: 4, accentColor: hlColor, cursor: "pointer" }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: labelColor, opacity: 0.7 }}>
          <span>OFF</span><span>12 сек</span>
        </div>
      </div>

      {/* Cover Mode Selector */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
          💿 Cover Style
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {(["default", "vinyl", "cd", "case"] as const).map(mode => {
            const labels = { default: "Обложка", vinyl: "Винил", cd: "CD", case: "Кейс" };
            const icons = { default: "🖼", vinyl: "🎵", cd: "💿", case: "📀" };
            const active = coverMode === mode;
            return (
              <button key={mode} onClick={() => { haptic("light"); onCoverMode?.(mode); }} style={{
                flex: 1, padding: "5px 4px", borderRadius: 10, fontSize: 10, fontWeight: 600, cursor: "pointer",
                border: active ? `1px solid ${hlColor}` : panelBorder,
                background: active ? activeGrad : inactiveBg,
                color: active ? "#fff" : textColor,
                display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
              }}>
                <span style={{ fontSize: 14 }}>{icons[mode]}</span>
                {labels[mode]}
              </button>
            );
          })}
        </div>
      </div>

      {/* 3D Spatial Panner */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
            <IconSpatial size={14} color={labelColor} /> 3D Spatial
          </div>
          <span style={{ fontSize: 10, color: labelColor, fontVariantNumeric: "tabular-nums" }}>
            {panValue === 0 ? "Center" : panValue < 0 ? `L ${Math.abs(Math.round(panValue * 100))}%` : `R ${Math.round(panValue * 100)}%`}
          </span>
        </div>
        <input
          type="range" min={-1} max={1} step={0.01}
          value={panValue}
          onInput={(e) => onPanChange?.(Number((e.target as HTMLInputElement).value))}
          style={{ width: "100%", height: 4, accentColor: hlColor, cursor: "pointer" }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: labelColor, opacity: 0.7 }}>
          <span>◀ Left</span><span>Right ▶</span>
        </div>
      </div>

      {/* Playback Speed */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
          <IconSpeed size={14} color={labelColor} /> Скорость
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 6 }}>
          {SPEED_OPTIONS.map((s) => {
            const active = playbackSpeed === s;
            return (
              <button
                key={s}
                onClick={() => { haptic("light"); onSpeedChange?.(s); }}
                style={{
                  padding: "7px 4px", borderRadius: 12,
                  border: active ? `1px solid ${hlColor}` : panelBorder,
                  background: active ? activeGrad : inactiveBg,
                  color: active ? "#fff" : textColor,
                  fontSize: 11, fontWeight: active ? 700 : 500,
                  cursor: "pointer",
                }}
              >
                {s}x
              </button>
            );
          })}
        </div>
      </div>

      {/* Mood Filter for AI Wave */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase", color: labelColor, display: "flex", alignItems: "center", gap: 6 }}>
          <IconMood size={14} color={labelColor} /> Настроение
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
          {MOOD_OPTIONS.map((m) => {
            const active = moodFilter === m.id;
            return (
              <button
                key={m.id}
                onClick={() => { haptic("light"); onMoodChange?.(active ? null : m.id); }}
                style={{
                  padding: "8px 6px", borderRadius: 14,
                  border: active ? `1px solid ${hlColor}` : panelBorder,
                  background: active ? activeGrad : inactiveBg,
                  color: active ? "#fff" : textColor,
                  fontSize: 12, fontWeight: active ? 700 : 500,
                  cursor: "pointer",
                  display: "flex", flexDirection: "column",
                  alignItems: "center", gap: 2,
                }}
              >
                {m.icon(active ? "#fff" : textColor)}
                <span style={{ fontSize: 10 }}>{m.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Hi-Res Badge */}
      {(quality === "320" || quality === "auto") && (
        <div style={{
          display: "flex", justifyContent: "center", gap: 8, marginTop: 2,
        }}>
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "5px 12px", borderRadius: 999,
            fontSize: 10, fontWeight: 700, letterSpacing: 1,
            color: warm ? "#ffd54f" : "#b388ff",
            background: warm ? "rgba(255, 213, 79, 0.08)" : "rgba(124, 77, 255, 0.08)",
            border: warm ? "1px solid rgba(255, 213, 79, 0.15)" : "1px solid rgba(179, 136, 255, 0.15)",
            textTransform: "uppercase",
          }}>
            <IconHiRes size={14} color={warm ? "#ffd54f" : "#b388ff"} />
            HI-RES AUDIO · {quality === "320" ? "320kbps" : "ADAPTIVE"}
          </span>
        </div>
      )}
    </div>
  );
}
