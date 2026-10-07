/**
 * Service worker: makes the app installable and lets its SHELL (HTML,
 * JS, CSS, fonts) load even with no connection — NOT a replacement for
 * this app's existing offline-data logic (IndexedDB + the sync engine),
 * which already handles actual delivery data completely separately.
 * This only concerns itself with the static files the app is built from.
 *
 * Deliberately uses a RUNTIME caching strategy (cache whatever gets
 * fetched, as it's fetched) rather than a hardcoded list of files to
 * pre-cache on install. A hand-written hardcoded list would go stale the
 * moment Vite's production build renames its output files (they include
 * a content hash, e.g. index-a1b2c3.js) — runtime caching adapts
 * automatically instead of needing to be kept in sync with the build.
 *
 * Explicitly does NOT cache API requests (anything to the FastAPI
 * backend) — that data has its own, more correct offline story already
 * (IndexedDB + conflict-resolved sync), and letting a service worker
 * cache-and-serve stale API responses on top of that would just
 * introduce a second, conflicting source of "offline truth."
 */

const CACHE_NAME = "delivery-sync-shell-v1";
const API_ORIGIN = "http://127.0.0.1:8000";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never intercept API calls — always go straight to the network,
  // exactly as if this service worker didn't exist for these requests.
  if (url.origin === API_ORIGIN) {
    return;
  }

  // Only handle GET requests for same-origin app-shell files
  if (event.request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (event.request.mode === "navigate") {
    // HTML page loads: try the network first (so you always get the
    // latest version while online), falling back to the cached shell
    // if there's no connection.
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request).then((cached) => cached || caches.match("/")))
    );
    return;
  }

  // Static assets (JS, CSS, fonts, images): cache-first, since content-hashed
  // filenames mean a cached copy is always still valid.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      });
    })
  );
});

/**
 * Real Web Push handling. When the backend sends a push (see
 * backend/app/services/push.py), the browser wakes this service worker
 * up — even if the app/tab is completely closed — and this fires,
 * showing a genuine OS-level notification (Windows notification center,
 * macOS Notification Center, Android's notification shade, etc.).
 */
self.addEventListener("push", (event) => {
  let payload = { title: "Delivery Sync", body: "You have an update.", url: "/" };
  try {
    if (event.data) payload = event.data.json();
  } catch (err) {
    // If the payload isn't JSON for some reason, fall back to the default above.
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: payload.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});

/**
 * Real Background Sync — the browser wakes this service worker and
 * fires 'sync' the moment it detects connectivity, even if every tab
 * of the app is closed. Same class of mechanism as the 'push' handler
 * above (service-worker-driven, works with the tab closed), applied to
 * outgoing sync instead of incoming push.
 *
 * This is a plain, unbundled script (see the file-level docstring
 * above), so it can't `import` the app's ES module sync engines
 * (services/syncEngine.js etc.) — those only exist for the main thread.
 * Instead this re-implements the same core replay logic directly with
 * raw IndexedDB + fetch, reading "who's logged in" from the shared
 * context record written by services/backgroundSyncContext.js.
 *
 * If no context is found (nobody's logged in on this device, or the
 * context is stale), this is a no-op — there's nothing it could
 * meaningfully sync without a token.
 */

function swOpenDb(name, version) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, version);
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
    // Deliberately no onupgradeneeded here — this handler only ever
    // reads/writes stores the main thread already created. If the
    // database doesn't exist yet at all, onsuccess still fires (it
    // gets created empty), and the subsequent transaction below will
    // simply find no matching object store and fail gracefully.
  });
}

function swGetSyncContext() {
  return swOpenDb("app_sync_context", 1).then(
    (db) =>
      new Promise((resolve) => {
        if (!db.objectStoreNames.contains("context")) {
          resolve(null);
          return;
        }
        const tx = db.transaction("context", "readonly");
        const request = tx.objectStore("context").get("current");
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => resolve(null);
      })
  ).catch(() => null);
}

function swGetAll(db, storeName) {
  return new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains(storeName)) {
      resolve([]);
      return;
    }
    const tx = db.transaction(storeName, "readonly");
    const request = tx.objectStore(storeName).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

function swDelete(db, storeName, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

function swPut(db, storeName, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).put(value);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

async function backgroundSyncDeliveries(context) {
  const db = await swOpenDb(`delivery_sync_db_${context.userId}`, 2);
  const all = await swGetAll(db, "deliveries");
  const pending = all.filter((r) => r.sync_status === "pending");
  if (pending.length === 0) return 0;

  const response = await fetch(`${context.apiBaseUrl}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records: pending }),
  });
  if (!response.ok) throw new Error("Background delivery sync failed");
  const result = await response.json();

  for (const resolved of result.resolved_records || []) {
    await swPut(db, "deliveries", { ...resolved, sync_status: "synced" });
  }
  return (result.resolved_records || []).length;
}

async function backgroundSyncLocationPings(context) {
  const db = await swOpenDb(`delivery_sync_db_${context.userId}`, 2);
  const pings = (await swGetAll(db, "location_pings")).sort((a, b) => a.id - b.id);
  let syncedCount = 0;

  for (const ping of pings) {
    const response = await fetch(`${context.apiBaseUrl}/users/me/location`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${context.token}`,
      },
      body: JSON.stringify({ latitude: ping.latitude, longitude: ping.longitude }),
    });
    if (!response.ok) break; // still offline or a real failure — stop, retry the rest next time
    await swDelete(db, "location_pings", ping.id);
    syncedCount += 1;
  }
  return syncedCount;
}

async function backgroundSyncChatMessages(context) {
  const db = await swOpenDb(`chat_queue_${context.userId}`, 1);
  const messages = (await swGetAll(db, "pending_messages")).sort((a, b) => a.id - b.id);
  let syncedCount = 0;

  for (const msg of messages) {
    const response = await fetch(`${context.apiBaseUrl}/deliveries/${msg.delivery_id}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${context.token}`,
      },
      body: JSON.stringify({ message: msg.message }),
    });
    if (response.ok) {
      await swDelete(db, "pending_messages", msg.id);
      syncedCount += 1;
    } else if (response.status !== 401 && response.status !== 403) {
      // A transient/server error on this one message shouldn't block
      // ones after it in the queue — skip and keep going. Auth failures
      // (401/403) mean the token is stale; stop entirely, nothing else
      // in this queue will succeed either.
      continue;
    } else {
      break;
    }
  }
  return syncedCount;
}

async function backgroundSyncCart(context) {
  const db = await swOpenDb(`customer_cache_${context.userId}`, 2);
  let actionsCount = 0;
  const authHeaders = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${context.token}`,
  };

  // 1. Push the local-first cart to the server if it's been changed
  // since the last successful sync (mirrors cartSyncEngine.js's
  // pushCartToServer: clear the server cart, then re-add each local
  // line — correct because the local cart is the source of truth).
  const metaRows = await swGetAll(db, "meta");
  const dirtyRow = metaRows.find((r) => r.key === "cart_dirty");
  if (dirtyRow && dirtyRow.value) {
    const localItems = await swGetAll(db, "local_cart");
    await fetch(`${context.apiBaseUrl}/customer/cart/`, { method: "DELETE", headers: authHeaders });
    for (const item of localItems) {
      await fetch(`${context.apiBaseUrl}/customer/cart/`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ product_id: item.product_id, quantity: item.quantity }),
      });
    }
    await swPut(db, "meta", { key: "cart_dirty", value: false });
    actionsCount += 1;
  }

  // 2. Complete a checkout that was queued while offline — but ONLY
  // when it's test-mode (no real payment gateway to open a widget for).
  // A real-gateway checkout needs a foreground tab and a user gesture to
  // open Razorpay's Checkout.js, which a background sync firing with
  // every tab closed genuinely cannot do — so it's deliberately left
  // queued for Storefront.jsx to prompt "Complete Payment Now" the next
  // time the app is opened, exactly like cartSyncEngine.js's
  // processPendingCheckout already handles this same case.
  const pendingRow = metaRows.find((r) => r.key === "pending_checkout");
  if (pendingRow && pendingRow.value) {
    const details = pendingRow.value;
    try {
      const checkoutResp = await fetch(`${context.apiBaseUrl}/customer/checkout`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ address_line: details.address_line, city: details.city, phone: details.phone }),
      }).then((r) => r.json());

      if (checkoutResp.is_test_mode) {
        await fetch(`${context.apiBaseUrl}/customer/checkout/verify`, {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify({ order_id: checkoutResp.order_id }),
        });
        await swDelete(db, "meta", "pending_checkout");
        const cartItems = await swGetAll(db, "local_cart");
        for (const item of cartItems) await swDelete(db, "local_cart", item.product_id);
        actionsCount += 1;
      }
      // else: real gateway, checkout order created server-side but left
      // unpaid — pending_checkout stays queued so the app can prompt
      // for payment next time it's opened.
    } catch (err) {
      // Still offline (or the request itself failed) — leave it queued, try again next sync.
    }
  }

  return actionsCount;
}

async function backgroundSyncCustomerActions(context) {
  const db = await swOpenDb(`customer_cache_${context.userId}`, 2);
  const actions = (await swGetAll(db, "pending_actions")).sort((a, b) => (a.queued_at > b.queued_at ? 1 : -1));
  let syncedCount = 0;
  const authHeaders = { Authorization: `Bearer ${context.token}` };

  for (const action of actions) {
    const endpoint =
      action.type === "cancel"
        ? `/customer/deliveries/${action.delivery_id}/cancel`
        : `/customer/deliveries/${action.delivery_id}/reorder`;
    try {
      const response = await fetch(`${context.apiBaseUrl}${endpoint}`, {
        method: "POST",
        headers: authHeaders,
      });
      if (response.ok) {
        await swDelete(db, "pending_actions", action.id);
        syncedCount += 1;
      } else {
        // A real rejection (e.g. order no longer eligible) — won't
        // succeed on retry, drop it rather than queue forever.
        await swDelete(db, "pending_actions", action.id);
      }
    } catch (err) {
      break; // network error — still offline, stop here and retry the rest next time
    }
  }

  return syncedCount;
}

async function backgroundSyncDispatcherActions(context) {
  const db = await swOpenDb(`dispatcher_cache_${context.userId}`, 2);
  const actions = (await swGetAll(db, "pending_actions")).sort((a, b) => a.id - b.id);
  let syncedCount = 0;
  const authHeaders = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${context.token}`,
  };

  for (const action of actions) {
    try {
      let response;
      if (action.type === "create_delivery") {
        response = await fetch(`${context.apiBaseUrl}/deliveries/`, {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify(action.payload),
        });
      } else if (action.type === "assign_agent") {
        response = await fetch(`${context.apiBaseUrl}/deliveries/${action.payload.delivery_id}/assign-agent`, {
          method: "PATCH",
          headers: authHeaders,
          body: JSON.stringify({ agent_id: action.payload.agent_id }),
        });
      } else if (action.type === "create_product") {
        response = await fetch(`${context.apiBaseUrl}/admin/products/`, {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify(action.payload),
        });
      } else if (action.type === "update_product") {
        response = await fetch(`${context.apiBaseUrl}/admin/products/${action.payload.product_id}`, {
          method: "PATCH",
          headers: authHeaders,
          body: JSON.stringify(action.payload.updates),
        });
      } else if (action.type === "delete_product") {
        response = await fetch(`${context.apiBaseUrl}/admin/products/${action.payload.product_id}`, {
          method: "DELETE",
          headers: authHeaders,
        });
      } else {
        await swDelete(db, "pending_actions", action.id); // unrecognized type — drop rather than get stuck on it forever
        continue;
      }

      if (response.ok) {
        await swDelete(db, "pending_actions", action.id);
        syncedCount += 1;
      } else {
        // A real rejection — won't succeed on retry, drop it. Later
        // actions may depend on this one though (e.g. assigning an
        // agent to a delivery that failed to create), so stop here
        // rather than attempting the rest out of order.
        await swDelete(db, "pending_actions", action.id);
        break;
      }
    } catch (err) {
      break; // network error — still offline, stop and retry the rest next time
    }
  }

  return syncedCount;
}

async function runBackgroundSync() {
  const context = await swGetSyncContext();
  if (!context || !context.userId || !context.apiBaseUrl) return;

  // Each piece is independent — one failing (e.g. this account has no
  // delivery queue at all, so that DB genuinely doesn't exist) must not
  // stop the others from being attempted.
  const results = await Promise.allSettled([
    backgroundSyncDeliveries(context),
    backgroundSyncLocationPings(context),
    backgroundSyncChatMessages(context),
    backgroundSyncCart(context),
    backgroundSyncCustomerActions(context),
    backgroundSyncDispatcherActions(context),
  ]);

  const totalSynced = results
    .filter((r) => r.status === "fulfilled")
    .reduce((sum, r) => sum + (r.value || 0), 0);

  if (totalSynced > 0) {
    const clients = await self.clients.matchAll({ type: "window" });
    for (const client of clients) {
      client.postMessage({ type: "background-sync-complete", syncedCount: totalSynced });
    }
  }
}

self.addEventListener("sync", (event) => {
  if (event.tag === "delivery-sync-background-sync") {
    event.waitUntil(runBackgroundSync());
  }
});
