/**
 * Sync engine: sends every locally-queued (offline) status update to
 * the backend's existing POST /sync endpoint, and reconciles the
 * results back into the local cache (./offlineStore.js).
 *
 * Deliberately mirrors frontend/src/services/syncEngine.js's shape
 * closely — same MAX_RETRIES/RETRY_DELAY_MS constants, same
 * describeConflict() wording, same overall runSync() control flow —
 * since it's solving the exact same problem (a batch of offline edits
 * that need to reach the same backend endpoint) with a different
 * local-storage backend (AsyncStorage here vs IndexedDB there) and a
 * different "are we online, and when did that change" signal (no
 * `navigator.onLine`/`window.addEventListener("online", ...)` exist in
 * React Native — see startAutoSync below for what replaces them).
 */

import * as Network from "expo-network";
import { AppState } from "react-native";
import { getPendingDeliveries, markAsSynced } from "./offlineStore";
import { API_BASE_URL } from "./api";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 3000;
const PERIODIC_SYNC_INTERVAL_MS = 15000; // check every 15 seconds while the app is foregrounded

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Same wording as the web app's syncEngine.js — see that file's own
 * docstring for why this exists: a discarded offline change should
 * never vanish with no trace anywhere in the interface. */
export function describeConflict(conflict) {
  const who = conflict.kept_by ? `${conflict.kept_by} already updated it` : "it was already updated";
  return `Order ${conflict.order_id}: your change to "${conflict.your_status}" was overridden — ${who} to "${conflict.kept_status}" more recently, so that's what was kept.`;
}

/**
 * POST /sync is intentionally unauthenticated on the backend (see
 * backend/app/routes/sync.py's own docstring — each record already
 * carries its own agent_id/org_id from when it was cached, and
 * rejecting a whole offline batch over an expired token would strand
 * real data), so this is a plain fetch with no Authorization header,
 * matching exactly how the web app's api.js:syncPendingDeliveries
 * calls the same endpoint.
 */
async function syncPendingDeliveries(records) {
  const response = await fetch(`${API_BASE_URL}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records }),
  });
  if (!response.ok) throw new Error("Sync request failed");
  return response.json();
}

/**
 * Attempts to sync all pending records. Retries on failure up to
 * MAX_RETRIES times with a fixed delay between attempts — identical
 * control flow to the web app's runSync(), see that file for the
 * reasoning (a fixed short retry window covers a brief connectivity
 * blip without the caller needing its own retry logic).
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
 * Sets up automatic syncing in THREE ways — same three as the web
 * app's startAutoSync(), adapted to React Native's actual signals:
 *
 * 1. Runs once immediately on startup, in case there are already
 *    pending records from a previous offline session.
 * 2. Runs again whenever the app is foregrounded (AppState "active") —
 *    React Native's closest equivalent to the browser's "online"
 *    event; there's no reliable cross-platform "connectivity just
 *    came back" push event the way a browser tab gets, but a user
 *    reopening/foregrounding the app after being offline is the
 *    moment that matters in practice, and expo-network's check inside
 *    triggerSync() means a foreground event while STILL offline
 *    correctly does nothing rather than wasting a request.
 * 3. Runs periodically every PERIODIC_SYNC_INTERVAL_MS while the app
 *    is in the foreground, so sync doesn't depend on the agent
 *    manually reopening a screen — same rationale as the web app's
 *    own periodic check.
 *
 * Call this once from App.js after the auth session is restored.
 */
export function startAutoSync(onSyncComplete) {
  let intervalId = null;

  const triggerSync = async () => {
    const netState = await Network.getNetworkStateAsync();
    if (netState.isConnected && netState.isInternetReachable !== false) {
      const result = await runSync();
      if (onSyncComplete) onSyncComplete(result);
    }
  };

  const handleAppStateChange = (nextState) => {
    if (nextState === "active") {
      triggerSync();
    }
  };

  // 1. Try once on startup
  triggerSync();

  // 2. Try again whenever the app comes back to the foreground
  const subscription = AppState.addEventListener("change", handleAppStateChange);

  // 3. Try periodically in the background while foregrounded
  intervalId = setInterval(triggerSync, PERIODIC_SYNC_INTERVAL_MS);

  // Return a cleanup function so the caller can stop auto-sync (e.g.
  // on logout) and avoid duplicate timers/listeners.
  return () => {
    subscription.remove();
    if (intervalId) clearInterval(intervalId);
  };
}
