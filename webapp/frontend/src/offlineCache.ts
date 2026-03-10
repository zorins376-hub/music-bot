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

// Get cached stream URL or fetch and cache
export async function getStreamUrl(videoId: string, apiUrl: string): Promise<string> {
  try {
    // Check cache first
    const cached = await getCachedTrack(videoId);
    if (cached) {
      console.log(`[Cache] Hit: ${videoId}`);
      return URL.createObjectURL(cached);
    }
    
    // Fetch from API
    console.log(`[Cache] Miss, fetching: ${videoId}`);
    const response = await fetch(apiUrl);
    
    if (response.ok) {
      const blob = await response.blob();
      
      // Cache in background (don't await)
      cacheTrack(videoId, blob).catch(console.error);
      
      return URL.createObjectURL(blob);
    }
  } catch (e) {
    console.error("[Cache] Error:", e);
  }
  
  // Fallback to direct URL
  return apiUrl;
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
