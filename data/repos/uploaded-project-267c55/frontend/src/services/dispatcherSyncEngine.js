/**
 * Replays a dispatcher's queued offline actions — creating a delivery,
 * assigning an agent, or managing the product catalog — the moment
 * connectivity returns. Same online/interval trigger pattern as every
 * other sync engine in this app.
 */

import { getQueuedDispatcherActions, removeQueuedDispatcherAction } from "./dispatcherCache";
import {
  createDeliveryOnServer,
  assignAgentToDelivery,
  createProduct,
  updateProduct,
  deleteProduct,
} from "./api";

const PERIODIC_SYNC_INTERVAL_MS = 15000;

async function replayAction(token, action) {
  switch (action.type) {
    case "create_delivery":
      return createDeliveryOnServer(token, action.payload);
    case "assign_agent":
      return assignAgentToDelivery(token, action.payload.delivery_id, action.payload.agent_id);
    case "create_product":
      return createProduct(token, action.payload);
    case "update_product":
      return updateProduct(token, action.payload.product_id, action.payload.updates);
    case "delete_product":
      return deleteProduct(token, action.payload.product_id);
    default:
      throw new Error(`Unknown queued dispatcher action type: ${action.type}`);
  }
}

/**
 * Attempts to replay every queued action, oldest first, stopping the
 * moment one fails due to being offline (the rest stay queued for next
 * time) — but a real server rejection (e.g. an agent that no longer
 * exists) is dropped rather than retried forever, and reported back via
 * the `failed` list so the UI can tell the dispatcher what didn't go
 * through and why.
 */
export async function runDispatcherActionSync(token) {
  const pending = await getQueuedDispatcherActions();
  if (pending.length === 0) {
    return { syncedCount: 0, failed: [] };
  }

  let syncedCount = 0;
  const failed = [];

  for (const action of pending) {
    try {
      await replayAction(token, action);
      await removeQueuedDispatcherAction(action.id);
      syncedCount += 1;
    } catch (error) {
      const isNetworkError = error instanceof TypeError;
      if (!isNetworkError) {
        await removeQueuedDispatcherAction(action.id);
        failed.push({ action, message: error.message });
      }
      // Network errors: leave it queued, stop here — later actions may
      // depend on this one's server-side effect (e.g. a delivery must
      // exist before it can be assigned), so don't skip ahead out of order.
      if (isNetworkError) break;
    }
  }

  return { syncedCount, failed };
}

export function startDispatcherActionAutoSync(token, onSyncComplete) {
  const trigger = async () => {
    if (!navigator.onLine) return;
    const result = await runDispatcherActionSync(token);
    if (onSyncComplete && (result.syncedCount > 0 || result.failed.length > 0)) {
      onSyncComplete(result);
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
