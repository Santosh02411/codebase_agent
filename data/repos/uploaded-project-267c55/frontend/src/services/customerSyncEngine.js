/**
 * Replays a customer's queued offline actions (Cancel / Reorder) against
 * the real API the moment connectivity returns. Mirrors the structure
 * of services/syncEngine.js (the agent's sync engine) — same
 * once-on-load + 'online' event + periodic-interval trigger pattern —
 * but calls the customer-specific endpoints directly instead of the
 * generic /sync batch endpoint, since Cancel/Reorder aren't delivery-
 * status field edits, they're distinct actions.
 */

import { getPendingCustomerActions, removeCustomerAction } from "./customerOfflineStore";
import { cancelCustomerDelivery, reorderCustomerDelivery } from "./api";

const PERIODIC_SYNC_INTERVAL_MS = 15000;

/**
 * Attempts to replay every queued action once. An action that fails
 * (still offline, or a genuine server rejection) is left in the queue
 * to retry on the next trigger — except a rejection that will never
 * succeed (e.g. "already assigned, can't cancel"), which is also
 * removed so it doesn't retry forever; the error is reported back via
 * the returned `failed` list either way so the UI can inform the user.
 */
export async function runCustomerActionSync(token) {
  const pending = await getPendingCustomerActions();
  if (pending.length === 0) {
    return { syncedCount: 0, failed: [] };
  }

  let syncedCount = 0;
  const failed = [];

  for (const action of pending) {
    try {
      if (action.type === "cancel") {
        await cancelCustomerDelivery(token, action.delivery_id);
      } else if (action.type === "reorder") {
        await reorderCustomerDelivery(token, action.delivery_id);
      }
      await removeCustomerAction(action.id);
      syncedCount += 1;
    } catch (error) {
      const isNetworkError = error instanceof TypeError; // fetch() throws TypeError when offline/unreachable
      if (!isNetworkError) {
        // A real server rejection (e.g. delivery no longer eligible) —
        // won't succeed on retry, so drop it and surface the reason.
        await removeCustomerAction(action.id);
        failed.push({ action, message: error.message });
      }
      // Network errors are left queued silently — still offline, try again next trigger.
    }
  }

  return { syncedCount, failed };
}

export function startCustomerActionAutoSync(token, onSyncComplete) {
  const trigger = async () => {
    if (navigator.onLine) {
      const result = await runCustomerActionSync(token);
      if (onSyncComplete && (result.syncedCount > 0 || result.failed.length > 0)) {
        onSyncComplete(result);
      }
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
