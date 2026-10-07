/**
 * Caches map tile images (as Blobs) in IndexedDB, keyed by tile URL.
 * Used by CachedTileLayer (see LiveTrackingMap.jsx) so the last-viewed
 * area of the tracking map keeps rendering even with no connection,
 * instead of going blank.
 *
 * Deliberately NOT scoped per-user like the other IndexedDB stores in
 * this app — map tiles for "the area around Bengaluru" aren't private
 * data tied to any one account, so sharing one cache across whoever
 * uses this browser is both fine and more useful (an agent and a
 * customer viewing the same neighborhood both benefit from tiles the
 * other already cached).
 */

const DB_NAME = "map_tile_cache";
const DB_VERSION = 1;
const STORE_NAME = "tiles";
const MAX_CACHED_TILES = 600; // roughly enough for several screens' worth of pan/zoom in one area

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "url" });
        store.createIndex("cached_at", "cached_at", { unique: false });
      }
    };
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function cacheTile(url, blob) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put({ url, blob, cached_at: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  }).then(() => trimCacheIfNeeded());
}

export async function getCachedTile(url) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).get(url);
    request.onsuccess = () => resolve(request.result ? request.result.blob : null);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Evicts the oldest-cached tiles once the store grows past the cap —
 * keeps this a bounded "recently viewed areas" cache rather than an
 * ever-growing offline map of everywhere the app has ever shown.
 */
async function trimCacheIfNeeded() {
  const db = await openDb();
  const count = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).count();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });

  if (count <= MAX_CACHED_TILES) return;

  const excess = count - MAX_CACHED_TILES;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const index = tx.objectStore(STORE_NAME).index("cached_at");
    let deleted = 0;
    const cursorRequest = index.openCursor();
    cursorRequest.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor && deleted < excess) {
        cursor.delete();
        deleted += 1;
        cursor.continue();
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
