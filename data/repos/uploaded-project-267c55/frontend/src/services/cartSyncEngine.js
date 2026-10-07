/**
 * Keeps the server-side cart in sync with the local-first cart, and
 * completes a checkout that was queued while offline.
 *
 * Cart sync strategy: the local cart is the source of truth (see
 * customerOfflineStore.js's module docstring), so syncing simply mirrors
 * it onto the server exactly — clear the server cart, then add each
 * local line — rather than diffing. This is safe here because a single
 * customer is expected to shop from one device at a time; it trades
 * away multi-device-simultaneous-editing correctness for simplicity,
 * which is the right tradeoff for what this cart actually needs to do.
 *
 * Checkout: payment genuinely cannot happen with no connection, so a
 * checkout attempted offline is queued (see setPendingCheckout) instead
 * of failing. Once online:
 *   - If the order is TEST MODE (no Razorpay account configured — see
 *     backend/app/services/payment.py) or CASH ON DELIVERY (nothing to
 *     charge right now at all), the whole purchase completes
 *     automatically with no user interaction needed, since neither has
 *     a real payment widget to open.
 *   - If a REAL online gateway payment is needed, opening Razorpay's
 *     Checkout.js from a background timer would be blocked by most
 *     browsers as an unsolicited popup — payment needs a user gesture.
 *     So instead this surfaces the order as "ready — tap to pay" and
 *     lets Storefront.jsx prompt the customer to complete it with one tap.
 */

import {
  isCartDirty,
  markCartClean,
  getLocalCart,
  getPendingCheckout,
  clearPendingCheckout,
} from "./customerOfflineStore";
import { clearCart as clearServerCart, addToCart, checkoutCart, verifyPayment } from "./api";

const PERIODIC_SYNC_INTERVAL_MS = 15000;

async function pushCartToServer(token) {
  const dirty = await isCartDirty();
  if (!dirty) return;

  const localItems = await getLocalCart();
  await clearServerCart(token);
  for (const item of localItems) {
    await addToCart(token, item.product_id, item.quantity);
  }
  await markCartClean();
}

/**
 * Returns one of:
 *   - null                         — nothing pending
 *   - { completed: true, ... }     — test-mode checkout completed automatically
 *   - { readyToPay: true, ... }    — real gateway; caller should prompt the customer to pay
 *   - { failed: true, message }    — the queued checkout could not be completed (e.g. cart is now empty)
 */
async function processPendingCheckout(token) {
  const pending = await getPendingCheckout();
  if (!pending) return null;

  try {
    const checkoutResp = await checkoutCart(
      token, pending.address_line, pending.city, pending.phone, pending.coupon_code, pending.slot_start, pending.payment_method || "online"
    );

    if (checkoutResp.is_test_mode || checkoutResp.payment_method === "cod") {
      // Neither needs the Razorpay widget — test-mode is a local
      // stand-in, and COD has nothing to charge right now at all — so
      // both complete automatically the moment connectivity returns,
      // same as before.
      await verifyPayment(token, { order_id: checkoutResp.order_id });
      await clearPendingCheckout();
      return { completed: true, testMode: checkoutResp.is_test_mode, codMode: checkoutResp.payment_method === "cod" };
    }

    // Real gateway — leave it queued (don't clear it) so Storefront can
    // still find it and prompt for payment; just hand back what's needed.
    return { readyToPay: true, checkoutResp };
  } catch (err) {
    const isNetworkError = err instanceof TypeError;
    if (isNetworkError) return null; // still offline, try again next trigger
    await clearPendingCheckout();
    return { failed: true, message: err.message };
  }
}

export function startCartAutoSync(token, onEvent) {
  const trigger = async () => {
    if (!navigator.onLine) return;
    try {
      await pushCartToServer(token);
      const checkoutResult = await processPendingCheckout(token);
      if (checkoutResult && onEvent) onEvent(checkoutResult);
    } catch (err) {
      console.warn("Cart sync failed:", err.message);
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
