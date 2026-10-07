/**
 * IndexedDB wrapper for offline delivery record storage.
 *
 * This is the client-side "source of truth" while offline. Every write from
 * the Agent view goes here FIRST, never directly to the server.
 *
 * We use the raw IndexedDB API (no external library) so it's easy to explain
 * line-by-line in an interview.
 *
 * IMPORTANT: the database is scoped PER USER (see setActiveUser below).
 * Without this, IndexedDB is shared by browser origin only — meaning if
 * two different agents log in on the same browser (a common real-world
 * case: a shared device, or simply testing two accounts), Agent B would
 * see Agent A's leftover local records the moment they logged in, since
 * nothing in the app distinguished "whose" local data it was. Call
 * setActiveUser(user.id) once, right after login, before any other
 * function in this file is used.
 */

const DB_VERSION = 2;
const STORE_NAME = "deliveries";
const PINGS_STORE = "location_pings";
const MAX_QUEUED_PINGS = 30; // caps how large a gap of missed pings we'll try to replay — old enough entries get dropped rather than growing unbounded over a long offline stretch

import { requestBackgroundSync } from "./backgroundSync";

let activeDbName = null;

/**
 * Must be called once a user is known to be logged in (their id from
 * AuthContext), before any other function in this module runs. Every
 * subsequent open/read/write in this file uses a database name scoped to
 * that specific user, so switching accounts on the same browser can never
 * leak one user's local records into another's view.
 */
export function setActiveUser(userId) {
  activeDbName = `delivery_sync_db_${userId}`;
}

/**
 * Opens (or creates) the IndexedDB database and the object store.
 * Returns a Promise that resolves to the open database connection.
 */
function openDb() {
  if (!activeDbName) {
    return Promise.reject(
      new Error("setActiveUser() must be called before using IndexedDB storage.")
    );
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(activeDbName, DB_VERSION);

    // Runs only the first time, or when DB_VERSION is bumped
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("sync_status", "sync_status", { unique: false });
      }
      if (!db.objectStoreNames.contains(PINGS_STORE)) {
        db.createObjectStore(PINGS_STORE, { keyPath: "id", autoIncrement: true });
      }
    };

    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Saves (creates or updates) a delivery record locally.
 * Always sets sync_status to "pending" since it's a local-only change
 * until it's confirmed synced with the server.
 */
export async function saveDeliveryLocally(record) {
  const db = await openDb();
  const saved = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const recordToSave = { ...record, sync_status: "pending" };
    const request = store.put(recordToSave);

    request.onsuccess = () => resolve(recordToSave);
    request.onerror = (event) => reject(event.target.error);
  });

  // Ask the browser to wake the service worker and sync this the moment
  // connectivity is detected — even if every tab gets closed before that
  // happens.
  requestBackgroundSync();

  return saved;
}

/**
 * Retrieves all delivery records stored locally.
 */
export async function getAllLocalDeliveries() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const request = store.getAll();

    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Retrieves only records that haven't been synced yet.
 * This is what the sync engine calls when connectivity returns.
 */
export async function getPendingDeliveries() {
  const all = await getAllLocalDeliveries();
  return all.filter((record) => record.sync_status === "pending");
}

/**
 * Marks a local record as synced after the server confirms it.
 * If the server returned a different final version (due to conflict
 * resolution), we store that version instead of our local one.
 */
export async function markAsSynced(id, resolvedRecord) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const finalRecord = { ...resolvedRecord, sync_status: "synced" };
    const request = store.put(finalRecord);

    request.onsuccess = () => resolve(finalRecord);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Permanently deletes a delivery record from local IndexedDB storage.
 */
export async function deleteDeliveryLocally(id) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const request = store.delete(id);

    request.onsuccess = () => resolve();
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Merges deliveries assigned by a dispatcher (fetched from the server)
 * into local IndexedDB, WITHOUT overwriting any record the agent has
 * already touched locally and hasn't synced yet.
 *
 * Why this matters: if an agent already changed a delivery's status while
 * offline (sync_status: "pending"), blindly overwriting it with the
 * server's older version would silently lose that change. So this only
 * inserts records that are either brand new locally, or already marked
 * "synced" (meaning there's no unsynced local edit to protect).
 */
export async function mergeAssignedDeliveries(serverRecords) {
  const existingLocal = await getAllLocalDeliveries();
  const existingById = new Map(existingLocal.map((r) => [r.id, r]));

  for (const serverRecord of serverRecords) {
    const local = existingById.get(serverRecord.id);
    if (!local || local.sync_status === "synced") {
      // markAsSynced (not saveDeliveryLocally) is used deliberately here —
      // saveDeliveryLocally always marks records "pending", which would
      // incorrectly queue this freshly-pulled, already-synced record to be
      // uploaded again on the next sync.
      await markAsSynced(serverRecord.id, serverRecord);
    }
    // If local exists and is "pending", skip — don't clobber an unsynced
    // local edit. The next push-sync will reconcile it against the server
    // using the existing last-write-wins conflict logic.
  }
}

// ---------- Live GPS ping queue ----------
// When an agent's device has no signal, a location update to the server
// currently just fails. Instead of losing it silently, it's queued here
// and replayed (oldest first) the moment connectivity returns — see
// services/locationSyncEngine.js. Capped at MAX_QUEUED_PINGS so a long
// stretch offline doesn't grow this unboundedly; only the most recent
// pings matter for a live map anyway.

export async function queueLocationPing(latitude, longitude) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PINGS_STORE, "readwrite");
    const store = tx.objectStore(PINGS_STORE);
    store.add({ latitude, longitude, queued_at: new Date().toISOString() });

    tx.oncomplete = async () => {
      // Trim to the cap: drop the oldest entries first if we've grown past it.
      const all = await getQueuedLocationPings();
      if (all.length > MAX_QUEUED_PINGS) {
        const toDrop = all.slice(0, all.length - MAX_QUEUED_PINGS);
        for (const ping of toDrop) await removeLocationPing(ping.id);
      }
      requestBackgroundSync();
      resolve();
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getQueuedLocationPings() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PINGS_STORE, "readonly");
    const request = tx.objectStore(PINGS_STORE).getAll();
    request.onsuccess = () => resolve(request.result.sort((a, b) => a.id - b.id));
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function removeLocationPing(pingId) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PINGS_STORE, "readwrite");
    tx.objectStore(PINGS_STORE).delete(pingId);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
