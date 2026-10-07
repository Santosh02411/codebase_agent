/**
 * AsyncStorage-based local delivery cache — the mobile equivalent of
 * the web app's frontend/src/services/indexedDb.js, same conceptual
 * model, different storage API (React Native has no IndexedDB):
 *
 * - Every delivery successfully fetched from the server is cached here
 *   with sync_status "synced", so the delivery list/detail screens can
 *   still show *something* real when offline, instead of a blank
 *   error screen.
 * - A status update made while offline (or one whose network request
 *   just failed) is applied to the LOCAL cached copy immediately
 *   (sync_status "pending") so the UI reflects the change right away,
 *   and queued for the sync engine (./offlineSync.js) to actually send
 *   once connectivity returns.
 *
 * Same per-user scoping rationale as indexedDb.js's setActiveUser: if
 * two different agents ever log into the same physical device, agent
 * B must never see agent A's leftover cached/pending deliveries the
 * moment they log in — the storage key itself is scoped to the
 * logged-in user's id.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

let activeUserId = null;

export function setActiveUser(userId) {
  activeUserId = userId;
}

function storageKey() {
  if (!activeUserId) {
    throw new Error("setActiveUser() must be called before using offline storage.");
  }
  return `delivery_sync_deliveries_${activeUserId}`;
}

async function readAll() {
  if (!activeUserId) return {};
  const raw = await AsyncStorage.getItem(storageKey());
  return raw ? JSON.parse(raw) : {};
}

async function writeAll(recordsById) {
  await AsyncStorage.setItem(storageKey(), JSON.stringify(recordsById));
}

/**
 * Bulk-caches a freshly-fetched list of deliveries as "synced" —
 * called after every successful GET /deliveries/mine or GET
 * /deliveries/{id}, so the most recent known-good server state is
 * always available locally. Never overwrites a "pending" local
 * record with server data for the SAME id — that would silently
 * discard an offline edit that hasn't synced yet (the same "local
 * pending change wins until synced" rule indexedDb.js's own
 * saveDeliveryLocally already applies).
 */
export async function cacheDeliveries(deliveries) {
  const existing = await readAll();
  for (const delivery of deliveries) {
    const current = existing[delivery.id];
    if (current && current.sync_status === "pending") continue;
    existing[delivery.id] = { ...delivery, sync_status: "synced" };
  }
  await writeAll(existing);
}

export async function getCachedDeliveries() {
  const all = await readAll();
  return Object.values(all);
}

export async function getCachedDelivery(id) {
  const all = await readAll();
  return all[id] || null;
}

/**
 * Applies a status change to the local cached copy and marks it
 * "pending" — called when an authenticated PATCH /deliveries/{id}
 * request fails due to no connectivity (see api.js's
 * updateDeliveryStatus). The full existing cached record is required
 * as a base because the eventual sync to POST /sync needs a complete
 * record (agent_id, org_id, created_at, zone, etc. — see
 * backend/app/routes/sync.py's SyncRecordIn), not just the one
 * changed field.
 */
export async function queueStatusUpdate(deliveryId, patch) {
  const all = await readAll();
  const current = all[deliveryId];
  if (!current) {
    throw new Error("Can't queue an offline update for a delivery that was never cached.");
  }
  const updated = { ...current, ...patch, sync_status: "pending" };
  all[deliveryId] = updated;
  await writeAll(all);
  return updated;
}

export async function getPendingDeliveries() {
  const all = await readAll();
  return Object.values(all).filter((d) => d.sync_status === "pending");
}

export async function getPendingCount() {
  const pending = await getPendingDeliveries();
  return pending.length;
}

/**
 * Reconciles a local record with the server's final resolved version
 * after a successful sync — same role as indexedDb.js's markAsSynced.
 * Stores the SERVER's version, not the locally-queued one: if a
 * conflict was resolved server-side in favor of someone else's more
 * recent change, the local cache must reflect that, not keep pretending
 * the device's own offline edit is still current.
 */
export async function markAsSynced(id, resolvedRecord) {
  const all = await readAll();
  all[id] = { ...resolvedRecord, sync_status: "synced" };
  await writeAll(all);
  return all[id];
}

/** Wiped on logout — see AuthContext.js's logout(). */
export async function clearAll() {
  if (!activeUserId) return;
  await AsyncStorage.removeItem(storageKey());
}
