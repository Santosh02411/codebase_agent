/**
 * Sync engine: runs when the app comes online, sends all pending
 * (unsynced) records to the backend's /sync endpoint, and reconciles
 * the results back into IndexedDB.
 *
 * Includes basic retry logic for when a sync attempt fails (e.g.
 * connectivity drops mid-sync).
 */

import { getPendingDeliveries, markAsSynced } from "./indexedDb";
import { syncPendingDeliveries } from "./api";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 3000;
const PERIODIC_SYNC_INTERVAL_MS = 15000; // check every 15 seconds while online

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Turns one backend conflict record (see services/conflict_resolver.py)
 * into a plain-English sentence for the UI — this is the whole point of
 * conflict-visibility: previously a discarded offline change vanished
 * with no trace anywhere in the interface.
 */
export function describeConflict(conflict) {
  const who = conflict.kept_by ? `${conflict.kept_by} already updated it` : "it was already updated";
  return `Order ${conflict.order_id}: your change to "${conflict.your_status}" was overridden — ${who} to "${conflict.kept_status}" more recently, so that's what was kept.`;
}

/**
 * Attempts to sync all pending records. Retries on failure up to
 * MAX_RETRIES times with a fixed delay between attempts.
 *
 * Returns { success: boolean, syncedCount: number, error?: string }
 */
export async function runSync() {
  const pending = await getPendingDeliveries();

  if (pending.length === 0) {
    return { success: true, syncedCount: 0 };
  }

  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    try {
      const response = await syncPendingDeliveries(pending);

      // Reconcile: update each local record with the server's resolved version
      for (const resolvedRecord of response.resolved_records) {
        await markAsSynced(resolvedRecord.id, resolvedRecord);
      }

      const errorCount = response.errors ? response.errors.length : 0;
      return {
        success: true,
        syncedCount: response.resolved_records.length,
        errorCount,
        errors: response.errors || [],
        conflicts: response.conflicts || [],
      };
    } catch (error) {
      attempt += 1;
      if (attempt >= MAX_RETRIES) {
        return { success: false, syncedCount: 0, error: error.message };
      }
      await wait(RETRY_DELAY_MS);
    }
  }
}

/**
 * Sets up automatic syncing in THREE ways:
 * 1. Runs once immediately on startup, in case there are already pending records
 * 2. Runs again whenever the browser's "online" event fires (e.g. wifi reconnects)
 * 3. Runs periodically every PERIODIC_SYNC_INTERVAL_MS while online, so sync
 *    doesn't depend on the component remounting (e.g. switching views or
 *    refreshing the page) — this is what makes the "Online — changes will
 *    sync automatically" banner text actually true at all times.
 *
 * Call this once when the app loads.
 */
export function startAutoSync(onSyncComplete) {
  const triggerSync = async () => {
    if (navigator.onLine) {
      const result = await runSync();
      if (onSyncComplete) onSyncComplete(result);
    }
  };

  // 1. Try once on startup
  triggerSync();

  // 2. Try again whenever connectivity is restored
  window.addEventListener("online", triggerSync);

  // 3. Try periodically in the background while online
  const intervalId = setInterval(triggerSync, PERIODIC_SYNC_INTERVAL_MS);

  // Return a cleanup function so the caller can stop auto-sync
  // (e.g. if the component unmounts) and avoid memory leaks / duplicate timers
  return () => {
    window.removeEventListener("online", triggerSync);
    clearInterval(intervalId);
  };
}
