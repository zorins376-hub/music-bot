/// <reference lib="webworker" />
declare const self: ServiceWorkerGlobalScope;

const CACHE_NAME = "blackroom-v1";
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

  // Static assets: Cache-first
  event.respondWith(cacheFirst(request));
});

// Cache-first strategy for static assets
async function cacheFirst(request: Request): Promise<Response> {
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
async function networkFirst(request: Request): Promise<Response> {
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
async function handleAudioRequest(request: Request): Promise<Response> {
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
