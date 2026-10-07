/**
 * Replays queued offline chat messages (see chatOfflineQueue.js) the
 * moment connectivity returns — same online/interval trigger pattern
 * as every other sync engine in this app.
 */

import { getAllQueuedChatMessages, removeQueuedChatMessage } from "./chatOfflineQueue";
import { sendDeliveryMessage } from "./api";

const PERIODIC_SYNC_INTERVAL_MS = 15000;

export async function runChatSync(token) {
  const queued = await getAllQueuedChatMessages();
  let syncedCount = 0;
  const syncedDeliveryIds = new Set();

  for (const item of queued) {
    try {
      await sendDeliveryMessage(token, item.delivery_id, item.message);
      await removeQueuedChatMessage(item.id);
      syncedCount += 1;
      syncedDeliveryIds.add(item.delivery_id);
    } catch (err) {
      const isNetworkError = err instanceof TypeError;
      if (!isNetworkError) {
        // A real rejection (e.g. no longer authorized for this delivery)
        // — won't succeed on retry, drop it rather than queue forever.
        await removeQueuedChatMessage(item.id);
      }
      // Network errors: leave it queued, keep trying the rest — a later
      // message failing to send shouldn't block an earlier one that can.
    }
  }

  return { syncedCount, syncedDeliveryIds };
}

export function startChatAutoSync(token, onSyncComplete) {
  const trigger = async () => {
    if (!navigator.onLine) return;
    try {
      const result = await runChatSync(token);
      if (result.syncedCount > 0 && onSyncComplete) onSyncComplete(result);
    } catch (err) {
      console.warn("Chat sync failed:", err.message);
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
