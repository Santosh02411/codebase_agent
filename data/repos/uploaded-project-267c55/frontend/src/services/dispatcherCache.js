/**
 * IndexedDB cache + offline write queue for the Dispatcher view.
 *
 * Two halves:
 *   - A READ cache (as before): every successful fetch of the org's
 *     deliveries is mirrored here, so the dispatcher's screen falls
 *     back to it instead of going blank when offline.
 *   - A WRITE queue (new): assigning an agent, creating a delivery, or
 *     managing the product catalog while offline queues the action here
 *     instead of failing outright — replayed by
 *     services/dispatcherSyncEngine.js the moment connectivity returns,
 *     the same local-write-first pattern used everywhere else in this
 *     app (services/indexedDb.js for agents, customerOfflineStore.js
 *     for customers).
 *
 * Scoped per dispatcher user (see setActiveDispatcher), for the same
 * reason every other store in this app is scoped per user: without
 * this, a shared/public device logging in as a different dispatcher
 * would see the previous dispatcher's leftover cached org data or
 * queued actions.
 */

const DB_VERSION = 2;
const DELIVERIES_STORE = "deliveries";
const META_STORE = "meta";
const ACTIONS_STORE = "pending_actions";
const LAST_SYNCED_KEY = "last_synced_at";

import { requestBackgroundSync } from "./backgroundSync";

let activeDbName = null;

export function setActiveDispatcher(userId) {
  activeDbName = `dispatcher_cache_${userId}`;
}

function openDb() {
  if (!activeDbName) {
    return Promise.reject(new Error("setActiveDispatcher() must be called before using the dispatcher cache."));
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(activeDbName, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(DELIVERIES_STORE)) {
        db.createObjectStore(DELIVERIES_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(META_STORE)) {
        db.createObjectStore(META_STORE, { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains(ACTIONS_STORE)) {
        db.createObjectStore(ACTIONS_STORE, { keyPath: "id", autoIncrement: true });
      }
    };

    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Replaces the entire cached delivery list with a fresh server response,
 * and stamps the current time as the last successful sync.
 */
export async function cacheDispatcherDeliveries(records) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([DELIVERIES_STORE, META_STORE], "readwrite");
    const deliveryStore = tx.objectStore(DELIVERIES_STORE);
    const metaStore = tx.objectStore(META_STORE);

    deliveryStore.clear();
    for (const record of records) {
      deliveryStore.put(record);
    }
    metaStore.put({ key: LAST_SYNCED_KEY, value: new Date().toISOString() });

    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getCachedDispatcherDeliveries() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DELIVERIES_STORE, "readonly");
    const request = tx.objectStore(DELIVERIES_STORE).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function getDispatcherLastSyncedAt() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readonly");
    const request = tx.objectStore(META_STORE).get(LAST_SYNCED_KEY);
    request.onsuccess = () => resolve(request.result ? request.result.value : null);
    request.onerror = (event) => reject(event.target.error);
  });
}

// ---------- Offline write queue ----------
// type is one of: "create_delivery", "assign_agent", "create_product",
// "update_product", "delete_product". payload is whatever that action's
// API call needs (see services/dispatcherSyncEngine.js for exactly how
// each type is replayed).

export async function queueDispatcherAction(type, payload) {
  const db = await openDb();
  const action = { type, payload, queued_at: new Date().toISOString() };
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readwrite");
    const request = tx.objectStore(ACTIONS_STORE).add(action);
    request.onsuccess = () => {
      requestBackgroundSync();
      resolve({ ...action, id: request.result });
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getQueuedDispatcherActions() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readonly");
    const request = tx.objectStore(ACTIONS_STORE).getAll();
    request.onsuccess = () => resolve(request.result.sort((a, b) => a.id - b.id));
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function removeQueuedDispatcherAction(id) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readwrite");
    tx.objectStore(ACTIONS_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
