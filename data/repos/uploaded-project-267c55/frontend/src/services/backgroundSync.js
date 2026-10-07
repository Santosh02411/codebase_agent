/**
 * Requests a real Background Sync event — the browser will wake the
 * service worker and fire 'sync' (see public/sw.js) the moment it
 * detects connectivity, even if every tab of this app is closed. This
 * is the same mechanism class as the Web Push notifications already in
 * this app (service-worker-driven, works with the tab closed) applied
 * to outgoing sync instead of incoming push.
 *
 * Feature-detected: Safari and Firefox don't implement the Background
 * Sync API at all. On those browsers this silently no-ops — the
 * existing interval + 'online'-event sync engines (syncEngine.js,
 * locationSyncEngine.js, chatSyncEngine.js, etc.) remain the fallback
 * exactly as they worked before this feature existed, so nothing
 * regresses on unsupported browsers; they just don't get the
 * "syncs even with every tab closed" upgrade.
 */
export async function requestBackgroundSync(tag = "delivery-sync-background-sync") {
  if (!("serviceWorker" in navigator) || !("SyncManager" in window)) {
    return false; // unsupported browser — the interval-based sync engines still cover it
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    if (!registration.sync) return false;
    await registration.sync.register(tag);
    return true;
  } catch (err) {
    // Registration can fail for reasons outside our control (e.g. the
    // user denied background permissions) — never let this break the
    // calling code's own local queueing, which already succeeded.
    console.warn("Background sync registration failed:", err.message);
    return false;
  }
}
