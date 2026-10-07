/**
 * Replays an agent's queued live-location pings (see
 * services/indexedDb.js's queueLocationPing) once connectivity returns.
 * Mirrors the same online/interval trigger pattern as the other sync
 * engines in this app (services/syncEngine.js, customerSyncEngine.js).
 *
 * Pings are replayed oldest-first and removed from the queue as each
 * one succeeds. If one fails (still offline), the loop stops there —
 * the remaining queued pings stay put and get retried on the next
 * trigger, rather than being attempted out of order.
 */

import { getQueuedLocationPings, removeLocationPing } from "./indexedDb";
import { updateMyAgentLocation } from "./api";

const PERIODIC_SYNC_INTERVAL_MS = 15000;

export async function runLocationPingSync(token) {
  const queued = await getQueuedLocationPings();
  let syncedCount = 0;

  for (const ping of queued) {
    try {
      await updateMyAgentLocation(token, ping.latitude, ping.longitude);
      await removeLocationPing(ping.id);
      syncedCount += 1;
    } catch (err) {
      break; // still offline (or a transient failure) — stop, retry the rest next time
    }
  }

  return { syncedCount };
}

export function startLocationPingAutoSync(token) {
  const trigger = async () => {
    if (!navigator.onLine) return;
    try {
      await runLocationPingSync(token);
    } catch (err) {
      console.warn("Location ping sync failed:", err.message);
    }
  };

  trigger();
  window.addEventListener("online", trigger);
  const intervalId = setInterval(trigger, PERIODIC_SYNC_INTERVAL_MS);

  return () => {
    window.removeEventListener("online", trigger);
    clearInterval(intervalId);
  };
}
