/**
 * Sleep & Focus Sounds Mixer
 *
 * Real ambient audio files for nature/ambient sounds + Web Audio synthesis for noise colors.
 * Nature/ambient: rain, ocean, thunder, fire, wind, forest, cafe, train, night → /sounds/{id}.mp3
 * Noise: white, pink, brown → procedural Web Audio generation
 */
import { useState, useEffect, useRef, useCallback } from "preact/hooks";
import { memo } from "preact/compat";
import { getThemeById, themeColors } from "../themes";
import { IconMoon, IconClose, IconSpinner } from "./Icons";

interface Props {
  accentColor?: string;
  themeId?: string;
}

interface SoundDef {
  id: string;
  label: string;
  icon: string;
  category: "nature" | "noise" | "ambient";
}

const SOUNDS: SoundDef[] = [
  { id: "rain",        label: "Rain",        icon: "rain",    category: "nature" },
  { id: "ocean",       label: "Ocean",       icon: "ocean",   category: "nature" },
  { id: "thunder",     label: "Thunder",     icon: "thunder", category: "nature" },
  { id: "fire",        label: "Fireplace",   icon: "fire",    category: "nature" },
  { id: "wind",        label: "Wind",        icon: "wind",    category: "nature" },
  { id: "forest",      label: "Forest",      icon: "forest",  category: "nature" },
  { id: "white_noise", label: "White Noise", icon: "white",   category: "noise" },
  { id: "pink_noise",  label: "Pink Noise",  icon: "pink",    category: "noise" },
  { id: "brown_noise", label: "Brown Noise", icon: "brown",   category: "noise" },
  { id: "cafe",        label: "Cafe",        icon: "cafe",    category: "ambient" },
  { id: "train",       label: "Train",       icon: "train",   category: "ambient" },
  { id: "night",       label: "Night",       icon: "night",   category: "ambient" },
];

/** IDs that use real audio files */
const FILE_SOUNDS = new Set(["rain", "ocean", "thunder", "fire", "wind", "forest", "cafe", "train", "night"]);

const ICON_SVG: Record<string, string> = {
  rain:    "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 4c.83 0 1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5v-5c0-.83.67-1.5 1.5-1.5zm-4 3c.83 0 1.5.67 1.5 1.5v3c0 .83-.67 1.5-1.5 1.5S6.5 14.33 6.5 13.5v-3c0-.83.67-1.5 1.5-1.5zm8 0c.83 0 1.5.67 1.5 1.5v3c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5v-3c0-.83.67-1.5 1.5-1.5z",
  ocean:   "M2 12c2-2 4-2 6 0s4 2 6 0 4-2 6 0M2 16c2-2 4-2 6 0s4 2 6 0 4-2 6 0M2 8c2-2 4-2 6 0s4 2 6 0 4-2 6 0",
  thunder: "M13 2L3 14h8l-1 8 10-12h-8l1-8z",
  fire:    "M12 22c-4.42 0-8-3.58-8-8 0-4 3-7 5-9l1 3c.5 1.5 2.5.5 2-1L14 2c3 3 6 7 6 12 0 4.42-3.58 8-8 8z",
  wind:    "M9.59 4.59A2 2 0 1 1 11 8H2M12.59 19.41A2 2 0 1 0 14 16H2M17.73 7.27A2.5 2.5 0 1 1 19.5 12H2",
  forest:  "M17 21v-4.5a3.5 3.5 0 0 0-3.5-3.5 3.5 3.5 0 0 0-3.5 3.5V21M5 21l5-10 5 10M12 3v3M6.5 6.5l2 2M17.5 6.5l-2 2",
  white:   "M3 12h4l3-9 4 18 3-9h4",
  pink:    "M3 12h4l3-6 4 12 3-6h4",
  brown:   "M3 12h4l3-3 4 6 3-3h4",
  cafe:    "M18 8h1a4 4 0 0 1 0 8h-1M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8zM6 1v3M10 1v3M14 1v3",
  train:   "M4 15a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v8zM8 19l-2 3M16 19l2 3M9 12h0M15 12h0",
  night:   "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79zM12 7l1 2h2l-1.5 1.5.5 2L12 11.5 10 12.5l.5-2L9 9h2l1-2",
};

const haptic = (s: "light" | "medium" | "heavy") => {
  try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(s); } catch {}
};

// ── Hybrid Audio Engine: real files + procedural noise ──

class AmbientGenerator {
  private ctx: AudioContext;
  private masterGain: GainNode;
  private synthSources: Map<string, { node: AudioNode; gain: GainNode }> = new Map();
  private audioElements: Map<string, { el: HTMLAudioElement; mediaNode: MediaElementAudioSourceNode; gain: GainNode }> = new Map();

  constructor() {
    this.ctx = new AudioContext();
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = 0.5;
    this.masterGain.connect(this.ctx.destination);
  }

  get context() { return this.ctx; }

  setMasterVolume(v: number) {
    this.masterGain.gain.setTargetAtTime(v, this.ctx.currentTime, 0.05);
  }

  startSound(id: string, volume: number) {
    if (this.synthSources.has(id) || this.audioElements.has(id)) return;
    if (this.ctx.state === "suspended") this.ctx.resume();

    if (FILE_SOUNDS.has(id)) {
      this._startFileSound(id, volume);
    } else {
      this._startSynthSound(id, volume);
    }
  }

  private _startFileSound(id: string, volume: number) {
    const gain = this.ctx.createGain();
    gain.gain.value = 0;
    gain.connect(this.masterGain);
    gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.3);

    const el = new Audio(`/sounds/${id}.mp3`);
    el.loop = true;
    el.crossOrigin = "anonymous";
    el.volume = 1; // volume controlled via Web Audio gain
    const mediaNode = this.ctx.createMediaElementSource(el);
    mediaNode.connect(gain);
    el.play().catch(() => {});
    this.audioElements.set(id, { el, mediaNode, gain });
  }

  private _startSynthSound(id: string, volume: number) {
    const gain = this.ctx.createGain();
    gain.gain.value = 0;
    gain.connect(this.masterGain);
    gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.3);

    let node: AudioNode;
    switch (id) {
      case "white_noise": node = this.createNoise("white"); break;
      case "pink_noise":  node = this.createNoise("pink"); break;
      case "brown_noise": node = this.createNoise("brown"); break;
      default:            node = this.createNoise("white");
    }
    node.connect(gain);
    this.synthSources.set(id, { node, gain });
  }

  stopSound(id: string) {
    // File-based sound
    const fileSrc = this.audioElements.get(id);
    if (fileSrc) {
      fileSrc.gain.gain.setTargetAtTime(0, this.ctx.currentTime, 0.3);
      setTimeout(() => {
        try {
          fileSrc.el.pause();
          fileSrc.el.src = "";
          fileSrc.mediaNode.disconnect();
          fileSrc.gain.disconnect();
        } catch {}
        this.audioElements.delete(id);
      }, 600);
      return;
    }
    // Synth sound
    const src = this.synthSources.get(id);
    if (!src) return;
    src.gain.gain.setTargetAtTime(0, this.ctx.currentTime, 0.3);
    setTimeout(() => {
      try {
        src.node.disconnect();
        src.gain.disconnect();
      } catch {}
      this.synthSources.delete(id);
    }, 600);
  }

  setVolume(id: string, volume: number) {
    const fileSrc = this.audioElements.get(id);
    if (fileSrc) {
      fileSrc.gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.05);
      return;
    }
    const src = this.synthSources.get(id);
    if (src) {
      src.gain.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.05);
    }
  }

  stopAll() {
    for (const [id] of this.audioElements) this.stopSound(id);
    for (const [id] of this.synthSources) this.stopSound(id);
  }

  destroy() {
    // Immediate cleanup without fade
    for (const [, src] of this.audioElements) {
      try { src.el.pause(); src.el.src = ""; src.mediaNode.disconnect(); src.gain.disconnect(); } catch {}
    }
    this.audioElements.clear();
    for (const [, src] of this.synthSources) {
      try { src.node.disconnect(); src.gain.disconnect(); } catch {}
    }
    this.synthSources.clear();
    this.ctx.close();
  }

  // ── Noise generators (synthesis) ──

  private createNoise(type: "white" | "pink" | "brown"): AudioBufferSourceNode {
    const bufferSize = this.ctx.sampleRate * 4;
    const buffer = this.ctx.createBuffer(2, bufferSize, this.ctx.sampleRate);

    for (let ch = 0; ch < 2; ch++) {
      const data = buffer.getChannelData(ch);
      let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
      let lastOut = 0;

      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;

        if (type === "white") {
          data[i] = white * 0.5;
        } else if (type === "pink") {
          b0 = 0.99886 * b0 + white * 0.0555179;
          b1 = 0.99332 * b1 + white * 0.0750759;
          b2 = 0.96900 * b2 + white * 0.1538520;
          b3 = 0.86650 * b3 + white * 0.3104856;
          b4 = 0.55000 * b4 + white * 0.5329522;
          b5 = -0.7616 * b5 - white * 0.0168980;
          data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
          b6 = white * 0.115926;
        } else {
          const next = lastOut + white * 0.02;
          lastOut = Math.max(-1, Math.min(1, next));
          data[i] = lastOut * 3.5;
        }
      }
    }

    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    src.start();
    return src;
  }
}

// ── Presets ──
const PRESETS = [
  { name: "Deep Sleep",   sounds: { brown_noise: 0.6, rain: 0.3 } },
  { name: "Focus",        sounds: { pink_noise: 0.4, cafe: 0.3 } },
  { name: "Nature",       sounds: { rain: 0.5, thunder: 0.2, forest: 0.3 } },
  { name: "Cozy Night",   sounds: { fire: 0.5, rain: 0.3, night: 0.2 } },
  { name: "Train Ride",   sounds: { train: 0.5, rain: 0.2 } },
  { name: "Beach",        sounds: { ocean: 0.6, wind: 0.2 } },
];

export const SleepSoundsView = memo(function SleepSoundsView({ accentColor = "var(--tg-theme-button-color, #7c4dff)", themeId = "blackroom" }: Props) {
  const theme = getThemeById(themeId);
  const tc = themeColors(theme, accentColor);

  const [activeSounds, setActiveSounds] = useState<Record<string, number>>({});
  const [masterVolume, setMasterVolume] = useState(0.5);
  const [timerMinutes, setTimerMinutes] = useState<number | null>(null);
  const [timerRemaining, setTimerRemaining] = useState<number | null>(null);
  const generatorRef = useRef<AmbientGenerator | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      generatorRef.current?.destroy();
      generatorRef.current = null;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const getGenerator = useCallback(() => {
    if (!generatorRef.current) {
      generatorRef.current = new AmbientGenerator();
    }
    return generatorRef.current;
  }, []);

  const toggleSound = useCallback((id: string) => {
    haptic("light");
    const gen = getGenerator();
    setActiveSounds((prev) => {
      const next = { ...prev };
      if (id in next) {
        gen.stopSound(id);
        delete next[id];
      } else {
        const vol = 0.5;
        gen.startSound(id, vol);
        next[id] = vol;
      }
      return next;
    });
  }, [getGenerator]);

  const setVolume = useCallback((id: string, vol: number) => {
    const gen = getGenerator();
    gen.setVolume(id, vol);
    setActiveSounds((prev) => ({ ...prev, [id]: vol }));
  }, [getGenerator]);

  const handleMasterVolume = useCallback((vol: number) => {
    setMasterVolume(vol);
    getGenerator().setMasterVolume(vol);
  }, [getGenerator]);

  const applyPreset = useCallback((preset: typeof PRESETS[0]) => {
    haptic("medium");
    const gen = getGenerator();
    for (const id of Object.keys(activeSounds)) {
      gen.stopSound(id);
    }
    const next: Record<string, number> = {};
    for (const [id, vol] of Object.entries(preset.sounds)) {
      gen.startSound(id, vol);
      next[id] = vol;
    }
    setActiveSounds(next);
  }, [getGenerator, activeSounds]);

  const stopAll = useCallback(() => {
    haptic("medium");
    getGenerator().stopAll();
    setActiveSounds({});
    setTimerMinutes(null);
    setTimerRemaining(null);
    if (timerRef.current) clearInterval(timerRef.current);
  }, [getGenerator]);

  const startTimer = useCallback((minutes: number) => {
    haptic("medium");
    setTimerMinutes(minutes);
    setTimerRemaining(minutes * 60);
    if (timerRef.current) clearInterval(timerRef.current);
    const end = Date.now() + minutes * 60 * 1000;
    timerRef.current = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      setTimerRemaining(remaining);
      if (remaining <= 0) {
        if (timerRef.current) clearInterval(timerRef.current);
        stopAll();
      }
    }, 1000);
  }, [stopAll]);

  const activeCount = Object.keys(activeSounds).length;
  const formatTimer = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;

  return (
    <div style={{ paddingBottom: 24 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 20,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 42, height: 42, borderRadius: 14,
            background: tc.activeBg,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: tc.glowShadow,
          }}>
            <IconMoon size={22} color={tc.highlight} />
          </div>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: tc.textColor }}>
              Sleep & Focus
            </div>
            <div style={{ fontSize: 12, color: tc.hintColor }}>
              {activeCount > 0 ? `${activeCount} sound${activeCount > 1 ? "s" : ""} active` : "Mix ambient sounds"}
            </div>
          </div>
        </div>
        {activeCount > 0 && (
          <button
            onClick={stopAll}
            style={{
              padding: "8px 16px", borderRadius: 12,
              border: "1px solid rgba(244,67,54,0.3)",
              background: "rgba(244,67,54,0.1)",
              color: "#f44336", fontSize: 12, fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Stop All
          </button>
        )}
      </div>

      {/* Timer */}
      {activeCount > 0 && (
        <div style={{
          padding: "12px 16px", borderRadius: 16,
          background: tc.cardBg, border: tc.cardBorder,
          marginBottom: 16,
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: tc.hintColor, marginBottom: 8,
          }}>
            Sleep Timer {timerRemaining !== null && (
              <span style={{ color: tc.highlight, fontWeight: 700 }}>
                {" "}{formatTimer(timerRemaining)}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[15, 30, 45, 60, 90].map((m) => (
              <button
                key={m}
                onClick={() => startTimer(m)}
                style={{
                  padding: "6px 14px", borderRadius: 10,
                  border: timerMinutes === m ? `1px solid ${tc.highlight}` : tc.cardBorder,
                  background: timerMinutes === m ? tc.activeBg : "transparent",
                  color: timerMinutes === m ? tc.highlight : tc.textColor,
                  fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}
              >
                {m}m
              </button>
            ))}
            {timerMinutes !== null && (
              <button
                onClick={() => {
                  setTimerMinutes(null);
                  setTimerRemaining(null);
                  if (timerRef.current) clearInterval(timerRef.current);
                }}
                style={{
                  padding: "6px 12px", borderRadius: 10,
                  border: "1px solid rgba(244,67,54,0.2)",
                  background: "transparent",
                  color: "#f44336", fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {/* Master Volume */}
      {activeCount > 0 && (
        <div style={{
          padding: "12px 16px", borderRadius: 16,
          background: tc.cardBg, border: tc.cardBorder,
          marginBottom: 16,
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: tc.hintColor, minWidth: 50 }}>Master</span>
          <input
            type="range" min={0} max={100} step={5}
            value={Math.round(masterVolume * 100)}
            onInput={(e) => handleMasterVolume(Number((e.target as HTMLInputElement).value) / 100)}
            style={{ flex: 1, height: 4, accentColor: tc.highlight, cursor: "pointer" }}
          />
          <span style={{ fontSize: 12, fontWeight: 700, color: tc.highlight, minWidth: 32, textAlign: "right" }}>
            {Math.round(masterVolume * 100)}%
          </span>
        </div>
      )}

      {/* Quick Presets */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: tc.hintColor, marginBottom: 10 }}>
          Quick Presets
        </div>
        <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, WebkitOverflowScrolling: "touch" }}>
          {PRESETS.map((p) => (
            <button
              key={p.name}
              onClick={() => applyPreset(p)}
              style={{
                padding: "10px 18px", borderRadius: 14, flexShrink: 0,
                border: tc.cardBorder,
                background: tc.cardBg,
                color: tc.textColor,
                fontSize: 13, fontWeight: 600, cursor: "pointer",
                transition: "all 0.2s ease",
                whiteSpace: "nowrap",
              }}
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Sound Grid */}
      {(["nature", "noise", "ambient"] as const).map((cat) => {
        const catSounds = SOUNDS.filter((s) => s.category === cat);
        const labels = { nature: "Nature", noise: "Noise Colors", ambient: "Ambient" };
        return (
          <div key={cat} style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: tc.hintColor, marginBottom: 10 }}>
              {labels[cat]}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
              {catSounds.map((sound) => {
                const isActive = sound.id in activeSounds;
                const volume = activeSounds[sound.id] ?? 0.5;
                return (
                  <div key={sound.id} style={{
                    borderRadius: 16,
                    border: isActive ? `1px solid ${tc.highlight}` : tc.cardBorder,
                    background: isActive ? tc.activeBg : tc.cardBg,
                    overflow: "hidden",
                    transition: "all 0.2s ease",
                  }}>
                    <button
                      onClick={() => toggleSound(sound.id)}
                      style={{
                        width: "100%", padding: "16px 8px 8px",
                        border: "none", background: "transparent",
                        cursor: "pointer",
                        display: "flex", flexDirection: "column",
                        alignItems: "center", gap: 6,
                      }}
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                        stroke={isActive ? tc.highlight : tc.hintColor}
                        strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                      >
                        <path d={ICON_SVG[sound.icon] || ICON_SVG.white} />
                      </svg>
                      <span style={{
                        fontSize: 11, fontWeight: 600,
                        color: isActive ? tc.highlight : tc.textColor,
                      }}>
                        {sound.label}
                      </span>
                    </button>
                    {isActive && (
                      <div style={{ padding: "0 10px 10px" }}>
                        <input
                          type="range" min={0} max={100} step={5}
                          value={Math.round(volume * 100)}
                          onInput={(e) => setVolume(sound.id, Number((e.target as HTMLInputElement).value) / 100)}
                          style={{ width: "100%", height: 3, accentColor: tc.highlight, cursor: "pointer" }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
});
