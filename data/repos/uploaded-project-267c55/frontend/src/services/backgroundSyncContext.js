/**
 * A small, unscoped IndexedDB record holding "who's currently logged
 * in" (user id + token), written by the main thread and read by the
 * service worker (see public/sw.js's 'sync' event handler).
 *
 * This exists because the Background Sync API fires in the service
 * worker — a completely separate execution context with no access to
 * React state, AuthContext, or anything else in memory on the page.
 * The SW needs SOME way to know which user's offline queues to replay
 * and what token to authenticate with; this tiny shared record is that
 * bridge. It's intentionally NOT scoped per-user (there's only ever one
 * "currently logged in" context to store), unlike every other store in
 * this app.
 *
 * Security tradeoff, stated plainly: this persists an auth token in
 * IndexedDB so a closed-tab service worker can use it. That's a wider
 * exposure window than keeping a token only in memory/context. For a
 * real production deployment, prefer a short-lived token here (refreshed
 * frequently) over the long-lived session token, so a stolen local copy
 * has a short useful life.
 */

const DB_NAME = "app_sync_context";
const DB_VERSION = 1;
const STORE_NAME = "context";
const CONTEXT_KEY = "current";

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Called whenever a component that owns an offline queue mounts with a
 * known user + token (AgentDeliveryList.jsx, DeliveryMessages.jsx) —
 * keeps this record fresh so a background sync firing later has a
 * valid, current token to work with.
 */
export async function writeSyncContext({ userId, token, role, apiBaseUrl }) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put({ id: CONTEXT_KEY, userId, token, role, apiBaseUrl });
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function clearSyncContext() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(CONTEXT_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
