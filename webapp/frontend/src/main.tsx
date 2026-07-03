import { render } from "preact";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
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
        disableVerticalSwipes?: () => void;
        setHeaderColor?: (color: string) => void;
        setBackgroundColor?: (color: string) => void;
        onEvent?: (event: string, cb: () => void) => void;
        viewportStableHeight?: number;
        viewportHeight?: number;
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

const _tg = window.Telegram?.WebApp;
_tg?.ready();
_tg?.expand();
// Native feel: a downward flick inside a scrollable list must NOT dismiss a
// full-screen player. Guarded — older Telegram clients lack this method.
_tg?.disableVerticalSwipes?.();
// Match the Telegram chrome to the app's near-black boot background so there's
// no light flash / seam around the webview on open.
_tg?.setHeaderColor?.("#050406");
_tg?.setBackgroundColor?.("#050406");
// Keep a CSS var in sync with Telegram's real viewport so fixed bars (mini
// player, tab bar) don't jump on expand or hide behind the keyboard.
const _syncVh = () => {
  const h = _tg?.viewportStableHeight || _tg?.viewportHeight;
  if (h) document.documentElement.style.setProperty("--tg-vh", h + "px");
};
_syncVh();
_tg?.onEvent?.("viewportChanged", _syncVh);

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
  // Build the WebAudio startup graph off the critical paint path (was ~1.2s of
  // main-thread work sitting in front of first render).
  const _idle = window.requestIdleCallback || ((cb: () => void) => window.setTimeout(cb, 200));
  _idle(() => playStartupWhoosh());
  bootLoader.style.pointerEvents = "none"; // immediately unblock clicks
  bootLoader.classList.add("is-exiting");
  // 400ms is enough to read as an intentional intro, not a loading tax
  // (was a fixed 920ms floor on every open, even when JS was warm-cached).
  window.setTimeout(() => {
    bootLoader.classList.add("is-hidden");
    window.setTimeout(() => bootLoader.remove(), 100);
  }, 400);
}

// Render app AFTER boot-loader exit is scheduled
try {
  render(<ErrorBoundary><App /></ErrorBoundary>, document.getElementById("app")!);
} catch (e) {
  console.error("App render failed:", e);
}
