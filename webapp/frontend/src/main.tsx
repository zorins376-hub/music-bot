import { render } from "preact";
import { App } from "./App";
import { initCache } from "./offlineCache";

// Preconnect to API server for faster first request
const preconnect = document.createElement("link");
preconnect.rel = "preconnect";
preconnect.href = window.location.origin;
document.head.appendChild(preconnect);

// Initialize IndexedDB cache immediately (don't block first play)
initCache().catch(() => {});

// Telegram WebApp SDK
declare global {
  interface Window {
    Telegram: {
      WebApp: {
        initData: string;
        initDataUnsafe: { user?: { id: number; first_name: string } };
        ready: () => void;
        expand: () => void;
        close: () => void;
        MainButton: {
          text: string;
          show: () => void;
          hide: () => void;
          onClick: (cb: () => void) => void;
        };
        themeParams: Record<string, string>;
      };
    };
  }
}

window.Telegram?.WebApp?.ready();
window.Telegram?.WebApp?.expand();

// Boot-loader exit MUST run BEFORE render() —
// if App crashes during first render, the preloader still dismisses.
const bootLoader = document.getElementById("boot-loader");

function playStartupWhoosh() {
  try {
    const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    const ctx = new AudioContextCtor();
    const now = ctx.currentTime;

    const master = ctx.createGain();
    master.gain.setValueAtTime(0.0001, now);
    master.gain.exponentialRampToValueAtTime(0.05, now + 0.06);
    master.gain.exponentialRampToValueAtTime(0.0001, now + 1.2);
    master.connect(ctx.destination);

    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(220, now);
    osc.frequency.exponentialRampToValueAtTime(510, now + 0.75);

    const oscGain = ctx.createGain();
    oscGain.gain.setValueAtTime(0.0001, now);
    oscGain.gain.exponentialRampToValueAtTime(0.05, now + 0.08);
    oscGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.95);

    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(1200, now);
    filter.frequency.exponentialRampToValueAtTime(3800, now + 0.9);

    osc.connect(filter);
    filter.connect(oscGain);
    oscGain.connect(master);

    const bufferSize = Math.max(1, Math.floor(ctx.sampleRate * 1.2));
    const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i += 1) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / bufferSize);
    }
    const noise = ctx.createBufferSource();
    noise.buffer = noiseBuffer;

    const noiseFilter = ctx.createBiquadFilter();
    noiseFilter.type = "bandpass";
    noiseFilter.frequency.setValueAtTime(900, now);
    noiseFilter.frequency.exponentialRampToValueAtTime(2400, now + 0.9);

    const noiseGain = ctx.createGain();
    noiseGain.gain.setValueAtTime(0.0001, now);
    noiseGain.gain.exponentialRampToValueAtTime(0.03, now + 0.04);
    noiseGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.8);

    noise.connect(noiseFilter);
    noiseFilter.connect(noiseGain);
    noiseGain.connect(master);

    osc.start(now);
    osc.stop(now + 1.0);
    noise.start(now);
    noise.stop(now + 0.82);

    window.setTimeout(() => {
      void ctx.close().catch(() => {});
    }, 1500);
  } catch {
    // ignore browsers that block startup audio
  }
}

if (bootLoader) {
  playStartupWhoosh();
  bootLoader.style.pointerEvents = "none"; // immediately unblock clicks
  bootLoader.classList.add("is-exiting");
  window.setTimeout(() => {
    bootLoader.classList.add("is-hidden");
    window.setTimeout(() => bootLoader.remove(), 100);
  }, 920);
}

// Render app AFTER boot-loader exit is scheduled
try {
  render(<App />, document.getElementById("app")!);
} catch (e) {
  console.error("App render failed:", e);
}
