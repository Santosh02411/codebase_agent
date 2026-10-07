/**
 * Offline queue for Proof of Delivery submissions (Phase 1).
 *
 * Deliberately its OWN small IndexedDB database (not a new object store
 * bolted onto indexedDb.js's existing per-user delivery DB) — POD
 * submissions are a fire-and-forget authenticated POST to
 * /deliveries/{id}/pod, nothing like the last-write-wins delivery
 * record sync that database's schema/versioning is built around.
 * Keeping this isolated means Phase 1 can't accidentally break that
 * existing DB_VERSION/upgrade path.
 *
 * Flow: ProofOfDeliveryModal calls queuePod() with whatever it captured
 * (works identically online or offline — it always queues first). A
 * retry loop (started once via startPodSync()) then attempts each
 * queued item's submitProofOfDelivery() call; success removes it from
 * the queue, failure leaves it for the next tick. Same
 * MAX_RETRIES/backoff shape as services/syncEngine.js.
 *
 * IMPORTANT ordering note (see services/conflict_resolver.py's Phase 1
 * enforcement): if the org requires POD before a delivery can be
 * marked "delivered", the delivery's own status-change sync
 * (syncEngine.js) will keep failing with a clear "proof of delivery is
 * required" error — and retry, same as any other sync failure — until
 * this queue's matching POD submission has gone through. No explicit
 * coordination between the two queues is needed: both already retry on
 * their own interval, so the system self-heals within a sync cycle or two.
 */

import { submitProofOfDelivery } from "./api";

const DB_NAME = "delivery_sync_pod_queue";
const DB_VERSION = 1;
const STORE_NAME = "pending_pod";
const MAX_RETRIES = 5;
const RETRY_DELAY_MS = 4000;
const PERIODIC_SYNC_INTERVAL_MS = 15000;

function openQueueDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "queueId", autoIncrement: true });
      }
    };
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Queues a POD payload for delivery `deliveryId`. Always call this
 * (never submitProofOfDelivery() directly from a component) so capture
 * behaves identically whether the agent is online or offline —
 * queueing first and letting the retry loop pick it up immediately
 * when online is simpler and more robust than branching on
 * navigator.onLine at capture time.
 */
export async function queuePod(deliveryId, payload) {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).add({
      deliveryId,
      payload: { ...payload, captured_offline: !navigator.onLine },
      attempts: 0,
      queuedAt: new Date().toISOString(),
    });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function getAllQueued() {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

async function removeQueued(queueId) {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(queueId);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** How many POD submissions are still waiting to sync — for a small "N pending" badge in the UI. */
export async function countQueuedPod() {
  const all = await getAllQueued();
  return all.length;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Attempts to flush every queued POD submission for the given token.
 * Each item retries independently up to MAX_RETRIES before being left
 * in the queue for the next periodic tick (never dropped — a POD
 * capture is exactly the kind of record that must not silently
 * disappear).
 */
export async function runPodSync(token) {
  const queued = await getAllQueued();
  if (queued.length === 0) return { synced: 0 };

  let synced = 0;
  for (const item of queued) {
    let attempt = 0;
    let ok = false;
    while (attempt < MAX_RETRIES && !ok) {
      try {
        await submitProofOfDelivery(token, item.deliveryId, item.payload);
        ok = true;
      } catch (error) {
        attempt += 1;
        if (attempt >= MAX_RETRIES) break;
        await wait(RETRY_DELAY_MS);
      }
    }
    if (ok) {
      await removeQueued(item.queueId);
      synced += 1;
    }
  }
  return { synced };
}

let intervalHandle = null;

/** Call once after login (mirrors syncEngine.js's startAutoSync). */
export function startPodSync(getToken) {
  const attempt = () => {
    const token = getToken();
    if (token && navigator.onLine) runPodSync(token).catch(() => {});
  };
  attempt();
  window.addEventListener("online", attempt);
  intervalHandle = setInterval(attempt, PERIODIC_SYNC_INTERVAL_MS);
  return () => {
    window.removeEventListener("online", attempt);
    if (intervalHandle) clearInterval(intervalHandle);
  };
}
