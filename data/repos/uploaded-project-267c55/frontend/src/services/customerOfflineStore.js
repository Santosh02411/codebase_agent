/**
 * Read-cache + offline action queue for the Customer dashboard.
 *
 * Mirrors the same two ideas already used elsewhere in this app:
 *   - a read cache (like services/dispatcherCache.js), so the customer's
 *     order list survives connectivity drops instead of going blank
 *   - a local-first pending-action queue (like services/indexedDb.js's
 *     "pending" records), so tapping Cancel/Reorder while offline isn't
 *     lost — it's queued and replayed by services/customerSyncEngine.js
 *     the moment connectivity returns.
 *
 * Scoped per customer (see setActiveCustomer) for the same shared-device
 * reason the agent and dispatcher stores are scoped per user.
 */

const DB_VERSION = 2;
const DELIVERIES_STORE = "deliveries";
const META_STORE = "meta";
const ACTIONS_STORE = "pending_actions";
const STORES_STORE = "cached_stores";

import { requestBackgroundSync } from "./backgroundSync";
const PRODUCTS_STORE = "cached_products";
const CART_STORE = "local_cart";
const LAST_SYNCED_KEY = "last_synced_at";
const CART_DIRTY_KEY = "cart_dirty";
const PENDING_CHECKOUT_KEY = "pending_checkout";

let activeDbName = null;

export function setActiveCustomer(customerId) {
  activeDbName = `customer_cache_${customerId}`;
}

function openDb() {
  if (!activeDbName) {
    return Promise.reject(new Error("setActiveCustomer() must be called before using the customer offline store."));
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(activeDbName, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(DELIVERIES_STORE)) {
        db.createObjectStore(DELIVERIES_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(META_STORE)) {
        db.createObjectStore(META_STORE, { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains(ACTIONS_STORE)) {
        db.createObjectStore(ACTIONS_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(STORES_STORE)) {
        db.createObjectStore(STORES_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(PRODUCTS_STORE)) {
        const productsStore = db.createObjectStore(PRODUCTS_STORE, { keyPath: "id" });
        productsStore.createIndex("org_id", "org_id", { unique: false });
      }
      if (!db.objectStoreNames.contains(CART_STORE)) {
        db.createObjectStore(CART_STORE, { keyPath: "product_id" });
      }
    };

    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

// ---------- Read cache ----------

export async function cacheCustomerDeliveries(records) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([DELIVERIES_STORE, META_STORE], "readwrite");
    const deliveryStore = tx.objectStore(DELIVERIES_STORE);
    const metaStore = tx.objectStore(META_STORE);

    deliveryStore.clear();
    for (const record of records) {
      deliveryStore.put(record);
    }
    metaStore.put({ key: LAST_SYNCED_KEY, value: new Date().toISOString() });

    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getCachedCustomerDeliveries() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DELIVERIES_STORE, "readonly");
    const request = tx.objectStore(DELIVERIES_STORE).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function getCustomerLastSyncedAt() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readonly");
    const request = tx.objectStore(META_STORE).get(LAST_SYNCED_KEY);
    request.onsuccess = () => resolve(request.result ? request.result.value : null);
    request.onerror = (event) => reject(event.target.error);
  });
}

// ---------- Pending action queue (Cancel / Reorder while offline) ----------

/**
 * Queues an action taken while offline. `type` is "cancel" or "reorder";
 * `deliveryId` and `orderLabel` (the human-readable order_id, purely for
 * display in the pending-actions list) identify what it applies to.
 */
export async function queueCustomerAction(type, deliveryId, orderLabel) {
  const db = await openDb();
  const action = {
    id: `${type}_${deliveryId}_${Date.now()}`,
    type,
    delivery_id: deliveryId,
    order_label: orderLabel,
    queued_at: new Date().toISOString(),
  };
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readwrite");
    tx.objectStore(ACTIONS_STORE).put(action);
    tx.oncomplete = () => {
      requestBackgroundSync();
      resolve(action);
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getPendingCustomerActions() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readonly");
    const request = tx.objectStore(ACTIONS_STORE).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function removeCustomerAction(actionId) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ACTIONS_STORE, "readwrite");
    tx.objectStore(ACTIONS_STORE).delete(actionId);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

// ---------- Storefront cache: stores list + product catalogs ----------
// Same idea as the delivery read-cache above — mirror every successful
// fetch locally, so browsing still works when offline. This is what
// makes the storefront "offline-first" rather than just "online with a
// spinner": Storefront.jsx reads from these caches first/as a fallback,
// not the live API directly.

export async function cachePublicStores(stores) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORES_STORE, "readwrite");
    const store = tx.objectStore(STORES_STORE);
    store.clear();
    for (const s of stores) store.put(s);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getCachedPublicStores() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORES_STORE, "readonly");
    const request = tx.objectStore(STORES_STORE).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function cacheStoreProducts(orgId, products) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PRODUCTS_STORE, "readwrite");
    const store = tx.objectStore(PRODUCTS_STORE);
    const index = store.index("org_id");
    const cursorRequest = index.openCursor(IDBKeyRange.only(orgId));
    cursorRequest.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        cursor.delete(); // clear this store's previously-cached products before writing the fresh set
        cursor.continue();
      } else {
        for (const p of products) store.put(p);
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getCachedStoreProducts(orgId) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(PRODUCTS_STORE, "readonly");
    const index = tx.objectStore(PRODUCTS_STORE).index("org_id");
    const request = index.getAll(IDBKeyRange.only(orgId));
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

// ---------- Local-first cart ----------
// The cart itself is local-first: every add/update/remove writes here
// FIRST (instant UI update, works with zero connectivity), and
// services/cartSyncEngine.js mirrors this to the server's cart in the
// background whenever it's online — the server cart is a synced copy,
// not the source of truth, matching the same "local write wins, syncs
// later" pattern the agent's delivery-status store already uses.

async function markCartDirty(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).put({ key: CART_DIRTY_KEY, value: true });
    tx.oncomplete = () => {
      requestBackgroundSync();
      resolve();
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function isCartDirty() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readonly");
    const request = tx.objectStore(META_STORE).get(CART_DIRTY_KEY);
    request.onsuccess = () => resolve(!!(request.result && request.result.value));
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function markCartClean() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).put({ key: CART_DIRTY_KEY, value: false });
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getLocalCart() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CART_STORE, "readonly");
    const request = tx.objectStore(CART_STORE).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Adds a product to the local cart (or increments quantity if already
 * present). Enforces the same "one store at a time" rule as the server
 * cart — adding from a different org clears the existing local cart
 * first, so the two never disagree about which store the cart belongs to.
 */
export async function addToLocalCart(product, quantity = 1) {
  const db = await openDb();
  const existing = await getLocalCart();

  return new Promise((resolve, reject) => {
    const tx = db.transaction(CART_STORE, "readwrite");
    const store = tx.objectStore(CART_STORE);

    if (existing.length > 0 && existing[0].org_id !== product.org_id) {
      store.clear();
    }

    const currentQty = existing.find((i) => i.product_id === product.id && i.org_id === product.org_id)?.quantity || 0;
    store.put({
      product_id: product.id,
      org_id: product.org_id,
      product,
      quantity: currentQty + quantity,
    });

    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  }).then(() => markCartDirty(db));
}

export async function updateLocalCartQuantity(productId, quantity) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CART_STORE, "readwrite");
    const store = tx.objectStore(CART_STORE);
    if (quantity <= 0) {
      store.delete(productId);
    } else {
      const getRequest = store.get(productId);
      getRequest.onsuccess = () => {
        const existing = getRequest.result;
        if (existing) store.put({ ...existing, quantity });
      };
    }
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  }).then(() => markCartDirty(db));
}

export async function removeFromLocalCart(productId) {
  return updateLocalCartQuantity(productId, 0);
}

export async function clearLocalCart() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CART_STORE, "readwrite");
    tx.objectStore(CART_STORE).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  }).then(() => markCartDirty(db));
}

// ---------- Pending checkout ----------
// A checkout attempted while offline can't be paid for offline (there's
// no way to reach a payment gateway with no connection) — but the
// customer's intent (address/phone + "please place this order") IS
// captured immediately and replayed automatically once online, same as
// the pending-action queue above.

export async function setPendingCheckout(details) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).put({ key: PENDING_CHECKOUT_KEY, value: { ...details, queued_at: new Date().toISOString() } });
    tx.oncomplete = () => {
      requestBackgroundSync();
      resolve();
    };
    tx.onerror = (event) => reject(event.target.error);
  });
}

export async function getPendingCheckout() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readonly");
    const request = tx.objectStore(META_STORE).get(PENDING_CHECKOUT_KEY);
    request.onsuccess = () => resolve(request.result ? request.result.value : null);
    request.onerror = (event) => reject(event.target.error);
  });
}

export async function clearPendingCheckout() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).delete(PENDING_CHECKOUT_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = (event) => reject(event.target.error);
  });
}
