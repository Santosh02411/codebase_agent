/**
 * Offline queue for per-delivery chat messages (DeliveryMessages.jsx).
 * Same write-local-first pattern as services/indexedDb.js (delivery
 * status) and the other offline queues in this app — sending a message
 * with no signal queues it instead of failing, and
 * services/chatSyncEngine.js replays it once connectivity returns.
 *
 * Deliberately its own small database rather than piggybacking on the
 * agent-only delivery store (services/indexedDb.js) or the dispatcher-
 * only cache (services/dispatcherCache.js) — chat is used by BOTH
 * agents and dispatchers/admins (see DeliveryDetailModal.jsx, rendered
 * from both AgentDeliveryList and DispatcherTable), so it's scoped by
 * whichever user is logged in, independent of role.
 */

const DB_VERSION = 1;
const STORE_NAME = "pending_messages";

import { requestBackgroundSync } from "./backgroundSync";

let activeDbName = null;

export function setActiveChatUser(userId) {
  activeDbName = `chat_queue_${userId}`;
}

function openDb() {
  if (!activeDbName) {
    return Promise.reject(new Error("setActiveChatUser() must be called before using the chat offline queue."));
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(activeDbName, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
        store.createIndex("delivery_id", "delivery_id", { unique: false });
      }
    };

    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function queueChatMessage(deliveryId, message, senderDisplayName, senderRole) {
  const db = await openDb();
  const record = {
    delivery_id: deliveryId,
    message,
    sender_display_name: senderDisplayName,
    sender_role: senderRole,
    queued_at: new Date().toISOString(),
  };
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const request = tx.objectStore(STORE_NAME).add(record);
    request.onsuccess = () => {
      requestBackgroundSync();
      resolve({ ...record, id: request.result });
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getQueuedChatMessages(deliveryId) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const index = tx.objectStore(STORE_NAME).index("delivery_id");
    const request = index.getAll(IDBKeyRange.only(deliveryId));
    request.onsuccess = () => resolve(request.result.sort((a, b) => a.id - b.id));
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function getAllQueuedChatMessages() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve(request.result.sort((a, b) => a.id - b.id));
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function removeQueuedChatMessage(id) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
