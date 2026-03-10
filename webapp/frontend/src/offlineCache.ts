// IndexedDB Offline Cache for audio streams
const DB_NAME = "music_cache";
const DB_VERSION = 1;
const STORE_NAME = "tracks";
const MAX_CACHE_SIZE = 100 * 1024 * 1024; // 100MB max cache

interface CachedTrack {
  video_id: string;
  blob: Blob;
  timestamp: number;
  size: number;
}

let db: IDBDatabase | null = null;

export async function initCache(): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    
    request.onerror = () => reject(request.error);
    
    request.onsuccess = () => {
      db = request.result;
      resolve();
    };
    
    request.onupgradeneeded = (event) => {
      const database = (event.target as IDBOpenDBRequest).result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "video_id" });
        store.createIndex("timestamp", "timestamp", { unique: false });
      }
    };
  });
}

export async function getCachedTrack(videoId: string): Promise<Blob | null> {
  if (!db) await initCache();
  
  return new Promise((resolve, reject) => {
    const transaction = db!.transaction(STORE_NAME, "readonly");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.get(videoId);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const result = request.result as CachedTrack | undefined;
      resolve(result?.blob || null);
    };
  });
}

export async function cacheTrack(videoId: string, blob: Blob): Promise<void> {
  if (!db) await initCache();
  
  // Check total cache size and evict old entries if needed
  await evictIfNeeded(blob.size);
  
  return new Promise((resolve, reject) => {
    const transaction = db!.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    
    const entry: CachedTrack = {
      video_id: videoId,
      blob,
      timestamp: Date.now(),
      size: blob.size,
    };
    
    const request = store.put(entry);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

async function evictIfNeeded(newSize: number): Promise<void> {
  const totalSize = await getCacheTotalSize();
  
  if (totalSize + newSize > MAX_CACHE_SIZE) {
    // Get all entries sorted by timestamp (oldest first)
    const entries = await getAllEntries();
    entries.sort((a, b) => a.timestamp - b.timestamp);
    
    let freed = 0;
    const toDelete: string[] = [];
    
    for (const entry of entries) {
      if (totalSize + newSize - freed <= MAX_CACHE_SIZE * 0.8) break;
      toDelete.push(entry.video_id);
      freed += entry.size;
    }
    
    // Delete old entries
    for (const id of toDelete) {
      await deleteTrack(id);
    }
  }
}

async function getCacheTotalSize(): Promise<number> {
  const entries = await getAllEntries();
  return entries.reduce((sum, e) => sum + e.size, 0);
}

async function getAllEntries(): Promise<CachedTrack[]> {
  if (!db) await initCache();
  
  return new Promise((resolve, reject) => {
    const transaction = db!.transaction(STORE_NAME, "readonly");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.getAll();
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result as CachedTrack[]);
  });
}

async function deleteTrack(videoId: string): Promise<void> {
  if (!db) return;
  
  return new Promise((resolve, reject) => {
    const transaction = db!.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.delete(videoId);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

// Get cached stream URL or return API URL for direct streaming
export async function getStreamUrl(videoId: string, apiUrl: string): Promise<string> {
  try {
    // Check cache first
    const cached = await getCachedTrack(videoId);
    if (cached) {
      console.log(`[Cache] Hit: ${videoId}`);
      return URL.createObjectURL(cached);
    }
    
    // No cache — return direct API stream URL for immediate playback
    // The browser will start playing as data arrives (no waiting for full download)
    console.log(`[Cache] Miss, streaming direct: ${videoId}`);
    
    // Cache in background (don't block playback)
    backgroundCache(videoId, apiUrl);
    
    return apiUrl;
  } catch (e) {
    console.error("[Cache] Error:", e);
  }
  
  // Fallback to direct URL
  return apiUrl;
}

// Background fetch + cache (does not block playback)
const _bgCacheInFlight = new Set<string>();
function backgroundCache(videoId: string, apiUrl: string) {
  if (_bgCacheInFlight.has(videoId)) return;
  _bgCacheInFlight.add(videoId);
  fetch(apiUrl)
    .then(r => r.ok ? r.blob() : null)
    .then(blob => {
      if (blob && blob.size > 10240) {
        return cacheTrack(videoId, blob);
      }
    })
    .catch(() => {})
    .finally(() => _bgCacheInFlight.delete(videoId));
}

// Prefetch stream URLs for upcoming tracks (tells backend to resolve URLs in advance)
export async function prefetchTracks(videoIds: string[]): Promise<void> {
  if (!videoIds.length) return;
  try {
    await fetch("/api/prefetch", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": window.Telegram?.WebApp?.initData || "",
      },
      body: JSON.stringify({ video_ids: videoIds }),
    });
  } catch {}
}

export async function getCacheStats(): Promise<{ count: number; size: number }> {
  const entries = await getAllEntries();
  return {
    count: entries.length,
    size: entries.reduce((sum, e) => sum + e.size, 0),
  };
}

export async function clearCache(): Promise<void> {
  if (!db) return;
  
  return new Promise((resolve, reject) => {
    const transaction = db!.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.clear();
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

// Initialize on module load
initCache().catch(console.error);
