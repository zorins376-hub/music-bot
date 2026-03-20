/// <reference lib="webworker" />
/* eslint-disable no-restricted-globals */

const CACHE_NAME = "blackroom-v5";
const AUDIO_CACHE_NAME = "blackroom-audio-v1";

// Static assets to precache
const PRECACHE_URLS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
];

// Install: precache static assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  // Skip waiting to activate immediately
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name !== AUDIO_CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  // Take control of all pages immediately
  self.clients.claim();
});

// Fetch handler with different strategies
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // HTML navigation: always prefer network so users get fresh app shell.
  if (request.mode === "navigate" || url.pathname === "/" || url.pathname === "/index.html") {
    event.respondWith(networkFirst(request));
    return;
  }

  // Audio streams: Cache-first with network fallback
  if (url.pathname.includes("/api/stream/") || url.pathname.includes("/audio/")) {
    event.respondWith(handleAudioRequest(request));
    return;
  }

  // API requests: Network-first
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Hashed static assets: Cache-first
  event.respondWith(cacheFirst(request));
});

// Cache-first strategy for static assets
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok && request.method === "GET") {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Return offline fallback if available
    return new Response("Offline", { status: 503 });
  }
}

// Network-first strategy for API
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

// Audio handling with streaming cache
async function handleAudioRequest(request) {
  // Check audio cache first
  const cached = await caches.match(request);
  if (cached) {
    console.log("[SW] Audio cache hit:", request.url);
    return cached;
  }

  try {
    const response = await fetch(request);
    
    // Only cache successful GET requests
    if (response.ok && request.method === "GET") {
      // Clone response for caching
      const responseClone = response.clone();
      
      // Cache in background (don't block response)
      caches.open(AUDIO_CACHE_NAME).then(async (cache) => {
        // Check cache size before adding
        const keys = await cache.keys();
        const MAX_AUDIO_ENTRIES = 50;
        
        if (keys.length >= MAX_AUDIO_ENTRIES) {
          // Remove oldest entries (first 10)
          const toDelete = keys.slice(0, 10);
          await Promise.all(toDelete.map((k) => cache.delete(k)));
        }
        
        cache.put(request, responseClone);
      });
    }
    
    return response;
  } catch {
    // No cached version
    return new Response("Audio unavailable offline", { status: 503 });
  }
}

// Handle messages from main thread
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
  
  if (event.data?.type === "CLEAR_AUDIO_CACHE") {
    caches.delete(AUDIO_CACHE_NAME);
  }

  // Persistent notification for the notification shade
  if (event.data?.type === "SHOW_NOW_PLAYING") {
    const { title, artist, icon } = event.data;
    self.registration.showNotification(title || "Playing", {
      body: artist || "Black Room Radio",
      icon: icon || "/icon.svg",
      badge: "/icon.svg",
      tag: "now-playing",
      renotify: true,
      silent: true,
      ongoing: true,
      requireInteraction: true,
      actions: [
        { action: "prev", title: "⏮" },
        { action: "pause", title: "⏯" },
        { action: "next", title: "⏭" },
      ],
    }).catch(() => {});
  }

  if (event.data?.type === "HIDE_NOW_PLAYING") {
    self.registration.getNotifications({ tag: "now-playing" }).then((notifications) => {
      notifications.forEach((n) => n.close());
    });
  }
});

// Handle notification actions (play/pause/next/prev from shade)
self.addEventListener("notificationclick", (event) => {
  const action = event.action;
  event.notification.close();

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      if (clients.length > 0) {
        const client = clients[0];
        // Send action back to the app
        client.postMessage({ type: "MEDIA_ACTION", action: action || "toggle" });
        client.focus().catch(() => {});
      } else {
        // No open window — try to open one
        self.clients.openWindow("/");
      }
    })
  );
});

// Background sync for offline actions (future)
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-queue") {
    // Sync queue actions when back online
    event.waitUntil(syncOfflineActions());
  }
});

async function syncOfflineActions() {
  // Placeholder for offline queue sync
  console.log("[SW] Sync offline actions");
}

export {};
