import React, { useEffect, useState } from "react";
import {
  fetchPublicStores,
  fetchStoreProducts,
  verifyPayment,
  checkoutCart,
  validateCoupon,
  fetchDeliverySlots,
  fetchMyCustomerAddresses,
  createSubscription,
  API_BASE_URL,
} from "../services/api";
import {
  cachePublicStores,
  getCachedPublicStores,
  cacheStoreProducts,
  getCachedStoreProducts,
  getLocalCart,
  addToLocalCart,
  updateLocalCartQuantity,
  removeFromLocalCart,
  clearLocalCart,
  setPendingCheckout,
  getPendingCheckout,
  clearPendingCheckout,
} from "../services/customerOfflineStore";
import { startCartAutoSync } from "../services/cartSyncEngine";
import "../styles/auth.css";

/**
 * Loads Razorpay's real Checkout.js widget from their own CDN, once,
 * the first time it's actually needed — not on every render, and not
 * unconditionally on page load for customers who never shop.
 */
function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (window.Razorpay) {
      resolve(true);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

// The local cart's line shape is { product_id, org_id, product, quantity }.
function cartSubtotal(items) {
  return items.reduce((sum, line) => sum + line.product.price * line.quantity, 0);
}

// Mirrors the backend's exact pricing formula (routes/checkout.py) so the
// cart can show a live preview before the checkout API call happens.
function computeBreakdownPreview(subtotal, appliedCoupon, store) {
  const discountAmount = appliedCoupon ? appliedCoupon.discount_amount : 0;
  const deliveryFee = store?.delivery_fee || 0;
  const taxRatePercent = store?.tax_rate_percent || 0;
  const taxableAmount = Math.max(subtotal - discountAmount, 0);
  const taxAmount = Math.round(taxableAmount * (taxRatePercent / 100) * 100) / 100;
  const total = Math.round((taxableAmount + taxAmount + deliveryFee) * 100) / 100;
  return { subtotal, discountAmount, deliveryFee, taxAmount, taxRatePercent, total };
}

// image_url from the backend is a relative path like "/uploads/products/xyz.jpg" —
// resolve it against the API host so <img> tags actually load it.
function resolveImageUrl(imageUrl) {
  if (!imageUrl) return null;
  if (/^https?:\/\//i.test(imageUrl)) return imageUrl;
  return `${API_BASE_URL}${imageUrl}`;
}

export default function Storefront({ token, onOrderPlaced }) {
  const [stores, setStores] = useState([]);
  const [selectedStore, setSelectedStore] = useState(null);
  const [products, setProducts] = useState([]);
  const [cartItems, setCartItems] = useState([]);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const [addressLine, setAddressLine] = useState("");
  const [city, setCity] = useState("");
  const [phone, setPhone] = useState("");
  const [couponCode, setCouponCode] = useState("");
  const [appliedCoupon, setAppliedCoupon] = useState(null);
  const [isApplyingCoupon, setIsApplyingCoupon] = useState(false);
  const [couponError, setCouponError] = useState(null);
  const [availableDates, setAvailableDates] = useState([]);
  const [selectedSlotDate, setSelectedSlotDate] = useState(null);
  const [slotOptions, setSlotOptions] = useState([]);
  const [selectedSlotStart, setSelectedSlotStart] = useState(null);
  const [isLoadingSlots, setIsLoadingSlots] = useState(false);
  const [slotError, setSlotError] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState("online"); // "online" | "cod"
  const [savedAddresses, setSavedAddresses] = useState([]);
  const [selectedAddressId, setSelectedAddressId] = useState("new"); // "new" or a saved address's id
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isOffline, setIsOffline] = useState(false);
  const [pendingCheckout, setPendingCheckoutState] = useState(null);
  const [subscribingProduct, setSubscribingProduct] = useState(null);
  const [subscribeInterval, setSubscribeInterval] = useState("7");
  const [subscribeQuantity, setSubscribeQuantity] = useState(1);
  const [subscribeAddress, setSubscribeAddress] = useState("");
  const [subscribeCity, setSubscribeCity] = useState("");
  const [subscribePhone, setSubscribePhone] = useState("");
  const [subscribePaymentMethod, setSubscribePaymentMethod] = useState("online");
  const [isCreatingSubscription, setIsCreatingSubscription] = useState(false);
  const [subscribeError, setSubscribeError] = useState(null);
  const [subscribeSuccess, setSubscribeSuccess] = useState(null);
  const [storeSearch, setStoreSearch] = useState("");
  const [storeCategory, setStoreCategory] = useState("");

  useEffect(() => {
    loadStores();
    loadLocalCart();
    checkPendingCheckout();
    loadSavedAddresses();

    const stopCartSync = startCartAutoSync(token, (result) => {
      if (result.completed) {
        setSuccessMessage(
          result.testMode
            ? "Your queued order was placed automatically once you were back online! (Test mode)"
            : result.codMode
            ? "Your queued order was placed automatically once you were back online! Pay in cash when it arrives."
            : "Your queued order was placed automatically once you were back online!"
        );
        setPendingCheckoutState(null);
        loadLocalCart();
        if (onOrderPlaced) onOrderPlaced();
      } else if (result.readyToPay) {
        checkPendingCheckout();
      } else if (result.failed) {
        setError(`Your queued order couldn't be placed: ${result.message}`);
        setPendingCheckoutState(null);
      }
    });

    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);
    setIsOffline(!navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      stopCartSync();
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  async function checkPendingCheckout() {
    const pending = await getPendingCheckout();
    setPendingCheckoutState(pending);
  }

  async function loadSavedAddresses() {
    try {
      const addresses = await fetchMyCustomerAddresses(token);
      setSavedAddresses(addresses);
      // Prefill from the default address (or the only one, if there's
      // just one) so a returning customer doesn't have to retype it —
      // still fully editable, and still overridable via the dropdown.
      const preferred = addresses.find((a) => a.is_default) || (addresses.length === 1 ? addresses[0] : null);
      if (preferred) {
        applySavedAddress(preferred);
      }
    } catch (err) {
      console.warn("Could not load saved addresses:", err.message);
    }
  }

  function applySavedAddress(address) {
    setSelectedAddressId(address.id);
    setAddressLine(address.address_line);
    setCity(address.city || "");
    if (address.phone) setPhone(address.phone);
  }

  function handleAddressSelectChange(e) {
    const value = e.target.value;
    setSelectedAddressId(value);
    if (value === "new") {
      setAddressLine("");
      setCity("");
      return;
    }
    const address = savedAddresses.find((a) => a.id === value);
    if (address) applySavedAddress(address);
  }

  async function loadStores() {
    try {
      const data = await fetchPublicStores();
      setStores(data);
      await cachePublicStores(data);
    } catch (err) {
      // Offline / unreachable — fall back to whatever was cached last time.
      const cached = await getCachedPublicStores();
      setStores(cached);
    }
  }

  async function loadLocalCart() {
    const items = await getLocalCart();
    setCartItems(items);
  }

  async function openStore(store) {
    setSelectedStore(store);
    setError(null);
    try {
      const data = await fetchStoreProducts(store.id);
      setProducts(data);
      await cacheStoreProducts(store.id, data);
    } catch (err) {
      const cached = await getCachedStoreProducts(store.id);
      setProducts(cached);
      if (cached.length === 0) setError("No cached products for this store, and you're offline.");
    }

    // Delivery slot picker: next 7 days (today included), default to today.
    const dates = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      dates.push(d.toISOString().slice(0, 10));
    }
    setAvailableDates(dates);
    setSelectedSlotDate(dates[0]);
    setSelectedSlotStart(null);
    await loadSlotsForDate(store.id, dates[0]);
  }

  async function loadSlotsForDate(orgId, dateStr) {
    setIsLoadingSlots(true);
    setSlotError(null);
    try {
      setSlotOptions(await fetchDeliverySlots(orgId, dateStr));
    } catch (err) {
      setSlotOptions([]);
      setSlotError(err instanceof TypeError ? "Delivery slots need a connection to load." : err.message);
    } finally {
      setIsLoadingSlots(false);
    }
  }

  function handleSlotDateChange(dateStr) {
    setSelectedSlotDate(dateStr);
    setSelectedSlotStart(null);
    loadSlotsForDate(selectedStore.id, dateStr);
  }

  function formatSlotTime(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function formatSlotDateLabel(dateStr) {
    const d = new Date(dateStr + "T00:00:00");
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    if (dateStr === today) return "Today";
    if (dateStr === tomorrow) return "Tomorrow";
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  }

  async function handleAddToCart(product) {
    setError(null);
    await addToLocalCart(product, 1);
    await loadLocalCart();
  }

  async function handleUpdateQuantity(productId, quantity) {
    const line = cartItems.find((l) => l.product_id === productId);
    if (line && line.product.stock_quantity !== null && line.product.stock_quantity !== undefined && quantity > line.product.stock_quantity) {
      setError(`Only ${line.product.stock_quantity} left of "${line.product.name}".`);
      return;
    }
    setError(null);
    await updateLocalCartQuantity(productId, quantity);
    await loadLocalCart();
  }

  async function handleRemoveItem(productId) {
    await removeFromLocalCart(productId);
    await loadLocalCart();
  }

  async function completeRealPayment(checkoutResp) {
    const scriptLoaded = await loadRazorpayScript();
    if (!scriptLoaded) {
      setError("Couldn't load the payment widget. Check your connection and try again.");
      return;
    }

    const razorpay = new window.Razorpay({
      key: checkoutResp.razorpay_key_id,
      amount: checkoutResp.amount_paise,
      currency: checkoutResp.currency,
      name: "Delivery Sync",
      description: selectedStore?.name || "Order",
      order_id: checkoutResp.razorpay_order_id,
      handler: async (response) => {
        try {
          await verifyPayment(token, {
            order_id: checkoutResp.order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_signature: response.razorpay_signature,
          });
          setSuccessMessage("Payment successful! Your order has been placed.");
          await clearPendingCheckout();
          setPendingCheckoutState(null);
          await clearLocalCart();
          await loadLocalCart();
          setIsCartOpen(false);
          if (onOrderPlaced) onOrderPlaced();
        } catch (err) {
          setError("Payment succeeded but confirming your order failed: " + err.message);
        }
      },
      prefill: { contact: phone },
      theme: { color: "#f2a93b" },
    });
    razorpay.open();
  }

  function openSubscribeForm(product) {
    setSubscribingProduct(product);
    setSubscribeInterval("7");
    setSubscribeQuantity(1);
    setSubscribeAddress(addressLine || "");
    setSubscribeCity(city || "");
    setSubscribePhone(phone || "");
    setSubscribePaymentMethod("online");
    setSubscribeError(null);
  }

  async function handleCreateSubscription(e) {
    e.preventDefault();
    if (!subscribingProduct || !selectedStore) return;
    const intervalDays = parseInt(subscribeInterval, 10);
    if (!intervalDays || intervalDays < 1) {
      setSubscribeError("Interval must be at least 1 day.");
      return;
    }
    if (!subscribeAddress.trim() || !subscribePhone.trim()) {
      setSubscribeError("Address and phone are required.");
      return;
    }
    setIsCreatingSubscription(true);
    setSubscribeError(null);
    try {
      await createSubscription(token, {
        org_id: selectedStore.id,
        items: [{ product_id: subscribingProduct.id, quantity: subscribeQuantity }],
        interval_days: intervalDays,
        address_line: subscribeAddress.trim(),
        city: subscribeCity.trim() || null,
        phone: subscribePhone.trim(),
        payment_method: subscribePaymentMethod,
      });
      setSubscribeSuccess(`Subscribed! "${subscribingProduct.name}" will reorder every ${intervalDays} day(s).`);
      setSubscribingProduct(null);
    } catch (err) {
      setSubscribeError(err.message);
    } finally {
      setIsCreatingSubscription(false);
    }
  }

  async function handleApplyCoupon(e) {
    e.preventDefault();
    if (!couponCode.trim()) return;
    setCouponError(null);
    setIsApplyingCoupon(true);
    try {
      const result = await validateCoupon(token, couponCode.trim());
      setAppliedCoupon(result);
    } catch (err) {
      setAppliedCoupon(null);
      setCouponError(err.message);
    } finally {
      setIsApplyingCoupon(false);
    }
  }

  function handleRemoveCoupon() {
    setAppliedCoupon(null);
    setCouponCode("");
    setCouponError(null);
  }

  async function handleCheckout(e) {
    e.preventDefault();
    setError(null);
    setIsCheckingOut(true);

    const details = {
      address_line: addressLine.trim(),
      city: city.trim(),
      phone: phone.trim(),
      coupon_code: appliedCoupon ? appliedCoupon.code : null,
      slot_start: selectedSlotStart,
      payment_method: paymentMethod,
    };

    try {
      if (!navigator.onLine) {
        // Can't reach the server at all with no connection — queue the
        // intent instead of failing outright. The cart stays exactly
        // as-is locally; the sync engine will pick this up and complete
        // the order (or prompt for payment) automatically once back online.
        await setPendingCheckout(details);
        setPendingCheckoutState(await getPendingCheckout());
        setError(null);
        setSuccessMessage("You're offline — your order is queued and will be placed automatically once you're back online.");
        return;
      }

      const checkoutResp = await checkoutCart(
        token, details.address_line, details.city, details.phone, details.coupon_code, details.slot_start, details.payment_method
      );

      if (checkoutResp.is_test_mode || checkoutResp.payment_method === "cod") {
        // Neither of these needs the Razorpay widget: test-mode is a
        // local stand-in, and cash-on-delivery has nothing to charge
        // right now at all — both just confirm the order immediately.
        await verifyPayment(token, { order_id: checkoutResp.order_id });
        setSuccessMessage(
          checkoutResp.payment_method === "cod"
            ? `Order placed! Pay ₹${checkoutResp.total.toFixed(2)} in cash when it arrives.`
            : "Order placed! (Test mode — no real payment gateway is connected yet.)"
        );
        await clearLocalCart();
        await loadLocalCart();
        setIsCartOpen(false);
        setAppliedCoupon(null);
        setCouponCode("");
        setSelectedSlotStart(null);
        if (onOrderPlaced) onOrderPlaced();
        return;
      }

      await completeRealPayment(checkoutResp);
    } catch (err) {
      // A TypeError from fetch() means the request never reached the
      // server at all (connection actually dropped) — that's the only
      // case that should be silently queued as "offline". Any other
      // error is a REAL response from the server (e.g. a bad Razorpay
      // key pair, a validation error) and must be shown as what it
      // actually is — treating every failure as "you're offline" hides
      // real problems (like a backend crash) behind a falsely
      // reassuring message.
      if (err instanceof TypeError && !navigator.onLine) {
        await setPendingCheckout(details);
        setPendingCheckoutState(await getPendingCheckout());
        setSuccessMessage("You're offline — your order is queued and will be placed automatically once you're back online.");
      } else if (err instanceof TypeError) {
        setError("Couldn't reach the server. Check that the backend is running, then try again.");
      } else {
        setError(err.message);
      }
    } finally {
      setIsCheckingOut(false);
    }
  }

  async function handlePayNow() {
    setError(null);
    setIsCheckingOut(true);
    try {
      const checkoutResp = await checkoutCart(
        token, pendingCheckout.address_line, pendingCheckout.city, pendingCheckout.phone,
        pendingCheckout.coupon_code, pendingCheckout.slot_start, pendingCheckout.payment_method || "online"
      );
      if (checkoutResp.is_test_mode || checkoutResp.payment_method === "cod") {
        await verifyPayment(token, { order_id: checkoutResp.order_id });
        setSuccessMessage(
          checkoutResp.payment_method === "cod"
            ? `Order placed! Pay ₹${checkoutResp.total.toFixed(2)} in cash when it arrives.`
            : "Order placed! (Test mode)"
        );
        await clearPendingCheckout();
        setPendingCheckoutState(null);
        await clearLocalCart();
        await loadLocalCart();
        if (onOrderPlaced) onOrderPlaced();
      } else {
        await completeRealPayment(checkoutResp);
      }
    } catch (err) {
      setError(err instanceof TypeError ? "Couldn't reach the server. Check that the backend is running, then try again." : err.message);
    } finally {
      setIsCheckingOut(false);
    }
  }

  const subtotal = cartSubtotal(cartItems);

  if (successMessage) {
    return (
      <div className="card" style={{ maxWidth: "480px", margin: "24px auto", textAlign: "center" }}>
        <div style={{ fontSize: "32px", marginBottom: "8px" }}>✅</div>
        <p style={{ fontSize: "14px" }}>{successMessage}</p>
        <button className="btn btn-primary" onClick={() => { setSuccessMessage(null); setSelectedStore(null); }}>
          Continue Shopping
        </button>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h3 style={{ margin: 0, fontSize: "16px" }}>
          {selectedStore ? selectedStore.name : "Browse Stores"}
        </h3>
        <button className="btn" onClick={() => setIsCartOpen(!isCartOpen)}>
          🛒 Cart {cartItems.length > 0 && `(${cartItems.length})`}
        </button>
      </div>

      {isOffline && (
        <div className="connectivity-banner offline" style={{ marginBottom: "16px" }}>
          Offline — browsing cached products. Your cart still works; checkout will complete once you're back online.
        </div>
      )}

      {pendingCheckout && (
        <div className="card" style={{ marginBottom: "16px", borderColor: "var(--accent)" }}>
          <strong style={{ fontSize: "13px" }}>Order queued while offline</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "4px 0" }}>
            Queued at {new Date(pendingCheckout.queued_at).toLocaleString()} — deliver to {pendingCheckout.address_line}
          </p>
          {navigator.onLine && (
            <button className="btn btn-primary" style={{ fontSize: "12px" }} onClick={handlePayNow} disabled={isCheckingOut}>
              {isCheckingOut ? "Processing..." : "Complete Payment Now"}
            </button>
          )}
        </div>
      )}

      {error && <p style={{ color: "var(--danger)", fontSize: "12.5px" }}>{error}</p>}

      {isCartOpen && (
        <div className="card" style={{ marginBottom: "16px" }}>
          <strong style={{ fontSize: "13.5px" }}>Your Cart</strong>
          {cartItems.length === 0 && (
            <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>Your cart is empty.</p>
          )}
          {cartItems.map((line) => (
            <div key={line.product_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--border-color)" }}>
              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                {line.product.image_url && (
                  <img
                    src={resolveImageUrl(line.product.image_url)}
                    alt={line.product.name}
                    style={{ width: "36px", height: "36px", objectFit: "cover", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)" }}
                  />
                )}
                <div>
                  <div style={{ fontSize: "13px" }}>{line.product.name}</div>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>₹{line.product.price.toFixed(2)} each</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button className="btn" style={{ padding: "2px 8px", fontSize: "12px" }} onClick={() => handleUpdateQuantity(line.product_id, line.quantity - 1)}>-</button>
                <span style={{ fontSize: "13px" }}>{line.quantity}</span>
                <button className="btn" style={{ padding: "2px 8px", fontSize: "12px" }} onClick={() => handleUpdateQuantity(line.product_id, line.quantity + 1)}>+</button>
                <button className="btn" style={{ padding: "2px 8px", fontSize: "11px", color: "var(--danger)" }} onClick={() => handleRemoveItem(line.product_id)}>✕</button>
              </div>
            </div>
          ))}
          {cartItems.length > 0 && (
            <>
              <div style={{ marginTop: "12px" }}>
                {!appliedCoupon ? (
                  <form onSubmit={handleApplyCoupon} style={{ display: "flex", gap: "6px" }}>
                    <input
                      className="input"
                      type="text"
                      placeholder="Coupon code"
                      value={couponCode}
                      onChange={(e) => setCouponCode(e.target.value)}
                      style={{ flex: 1 }}
                    />
                    <button type="submit" className="btn" style={{ fontSize: "12px" }} disabled={isApplyingCoupon || !couponCode.trim()}>
                      {isApplyingCoupon ? "Checking..." : "Apply"}
                    </button>
                  </form>
                ) : (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12.5px", color: "var(--accent)" }}>
                    <span>"{appliedCoupon.code}" applied — ₹{appliedCoupon.discount_amount.toFixed(2)} off</span>
                    <button className="btn" style={{ fontSize: "11px", padding: "2px 6px" }} onClick={handleRemoveCoupon}>Remove</button>
                  </div>
                )}
                {couponError && <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "4px" }}>{couponError}</p>}
              </div>

              {(() => {
                const breakdown = computeBreakdownPreview(subtotal, appliedCoupon, selectedStore);
                return (
                  <div style={{ marginTop: "12px", fontSize: "13px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>Subtotal</span>
                      <span>₹{breakdown.subtotal.toFixed(2)}</span>
                    </div>
                    {breakdown.discountAmount > 0 && (
                      <div style={{ display: "flex", justifyContent: "space-between", color: "var(--accent)" }}>
                        <span>Discount</span>
                        <span>-₹{breakdown.discountAmount.toFixed(2)}</span>
                      </div>
                    )}
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>Delivery fee</span>
                      <span>₹{breakdown.deliveryFee.toFixed(2)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>GST ({breakdown.taxRatePercent}%)</span>
                      <span>₹{breakdown.taxAmount.toFixed(2)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600, fontSize: "14px", marginTop: "6px", paddingTop: "6px", borderTop: "1px solid var(--border-color)" }}>
                      <span>Total</span>
                      <span>₹{breakdown.total.toFixed(2)}</span>
                    </div>
                  </div>
                );
              })()}

              <form onSubmit={handleCheckout} style={{ marginTop: "12px" }}>
                <div className="auth-field">
                  <label>Delivery Window (optional — leave unset for ASAP)</label>
                  <div style={{ display: "flex", gap: "6px", overflowX: "auto", paddingBottom: "4px", marginBottom: "8px" }}>
                    {availableDates.map((d) => (
                      <button
                        type="button"
                        key={d}
                        className="btn"
                        style={{
                          fontSize: "11.5px",
                          padding: "4px 8px",
                          flexShrink: 0,
                          background: selectedSlotDate === d ? "var(--accent)" : undefined,
                          color: selectedSlotDate === d ? "white" : undefined,
                        }}
                        onClick={() => handleSlotDateChange(d)}
                      >
                        {formatSlotDateLabel(d)}
                      </button>
                    ))}
                  </div>
                  {isLoadingSlots ? (
                    <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Loading slots...</p>
                  ) : slotError ? (
                    <p style={{ fontSize: "12px", color: "var(--danger)" }}>{slotError}</p>
                  ) : slotOptions.length === 0 ? (
                    <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No delivery windows left for this day.</p>
                  ) : (
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {slotOptions.map((s) => (
                        <button
                          type="button"
                          key={s.start}
                          className="btn"
                          disabled={!s.available}
                          title={s.available ? `${s.remaining} of ${s.capacity} left` : "Full"}
                          style={{
                            fontSize: "11.5px",
                            padding: "4px 8px",
                            opacity: s.available ? 1 : 0.4,
                            background: selectedSlotStart === s.start ? "var(--accent)" : undefined,
                            color: selectedSlotStart === s.start ? "white" : undefined,
                          }}
                          onClick={() => setSelectedSlotStart(selectedSlotStart === s.start ? null : s.start)}
                        >
                          {formatSlotTime(s.start)}–{formatSlotTime(s.end)}
                        </button>
                      ))}
                    </div>
                  )}
                  {selectedSlotStart && (
                    <p style={{ fontSize: "11.5px", color: "var(--accent)", marginTop: "4px" }}>
                      Delivering {formatSlotDateLabel(selectedSlotDate)}, {formatSlotTime(selectedSlotStart)}
                    </p>
                  )}
                </div>
                <div className="auth-field">
                  <label>Delivery Address</label>
                  {savedAddresses.length > 0 && (
                    <select
                      className="input"
                      value={selectedAddressId}
                      onChange={handleAddressSelectChange}
                      style={{ marginBottom: "6px" }}
                    >
                      {savedAddresses.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.label}{a.is_default ? " (default)" : ""} — {a.address_line}
                        </option>
                      ))}
                      <option value="new">Enter a new address...</option>
                    </select>
                  )}
                  <input className="input" type="text" value={addressLine} onChange={(e) => { setAddressLine(e.target.value); setSelectedAddressId("new"); }} required />
                </div>
                <div className="auth-field">
                  <label>City</label>
                  <input className="input" type="text" value={city} onChange={(e) => { setCity(e.target.value); setSelectedAddressId("new"); }} />
                </div>
                <div className="auth-field">
                  <label>Phone</label>
                  <input className="input" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required />
                </div>
                <div className="auth-field">
                  <label>Payment Method</label>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      type="button"
                      className="btn"
                      style={
                        paymentMethod === "online"
                          ? { background: "var(--accent)", color: "white", flex: 1 }
                          : { flex: 1 }
                      }
                      onClick={() => setPaymentMethod("online")}
                    >
                      💳 Pay Online
                    </button>
                    <button
                      type="button"
                      className="btn"
                      style={
                        paymentMethod === "cod"
                          ? { background: "var(--accent)", color: "white", flex: 1 }
                          : { flex: 1 }
                      }
                      onClick={() => setPaymentMethod("cod")}
                    >
                      💵 Cash on Delivery
                    </button>
                  </div>
                </div>
                <button type="submit" className="btn btn-primary" disabled={isCheckingOut}>
                  {isCheckingOut
                    ? "Processing..."
                    : !navigator.onLine
                    ? `Place Order (₹${computeBreakdownPreview(subtotal, appliedCoupon, selectedStore).total.toFixed(2)}, will complete when online)`
                    : paymentMethod === "cod"
                    ? `Confirm Order — Pay ₹${computeBreakdownPreview(subtotal, appliedCoupon, selectedStore).total.toFixed(2)} on Delivery`
                    : `Pay ₹${computeBreakdownPreview(subtotal, appliedCoupon, selectedStore).total.toFixed(2)}`}
                </button>
              </form>
            </>
          )}
        </div>
      )}

      {!selectedStore && (
        <div>
          {stores.length > 0 && (
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px", flexWrap: "wrap" }}>
              <input
                className="input"
                type="text"
                placeholder="Search stores..."
                value={storeSearch}
                onChange={(e) => setStoreSearch(e.target.value)}
                style={{ flex: "1 1 180px" }}
              />
              <select
                className="input"
                value={storeCategory}
                onChange={(e) => setStoreCategory(e.target.value)}
                style={{ flex: "0 1 160px" }}
              >
                <option value="">All categories</option>
                {[...new Set(stores.map((s) => s.category).filter(Boolean))].sort().map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
          )}
          <div style={{ display: "grid", gap: "10px" }}>
            {stores
              .filter((store) => !storeSearch || store.name.toLowerCase().includes(storeSearch.toLowerCase()))
              .filter((store) => !storeCategory || store.category === storeCategory)
              .map((store) => (
                <div
                  key={store.id}
                  className="card card-clickable"
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                  onClick={() => openStore(store)}
                >
                  <div>
                    <strong style={{ fontSize: "14.5px" }}>{store.name}</strong>
                    {store.category && (
                      <span style={{ marginLeft: "8px", fontSize: "11px", color: "var(--text-muted)", border: "1px solid var(--border-color)", borderRadius: "10px", padding: "1px 7px" }}>
                        {store.category}
                      </span>
                    )}
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                      {store.description || "Tap to browse products"}
                    </div>
                  </div>
                  <span style={{ color: "var(--text-muted)", fontSize: "16px" }} aria-hidden="true">→</span>
                </div>
              ))}
            {stores.length === 0 && (
              <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>No stores are open for shopping yet.</p>
            )}
            {stores.length > 0 &&
              stores.filter((store) => !storeSearch || store.name.toLowerCase().includes(storeSearch.toLowerCase()))
                .filter((store) => !storeCategory || store.category === storeCategory).length === 0 && (
                <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>No stores match that search.</p>
              )}
          </div>
        </div>
      )}

      {selectedStore && (
        <div>
          <button className="btn" style={{ marginBottom: "12px", fontSize: "12px" }} onClick={() => setSelectedStore(null)}>
            ← All Stores
          </button>
          <div style={{ display: "grid", gap: "10px" }}>
            {products.map((product) => {
              const inCartQty = cartItems.find((l) => l.product_id === product.id)?.quantity || 0;
              const isOutOfStock = product.stock_quantity !== null && product.stock_quantity !== undefined && product.stock_quantity <= 0;
              const isAtStockLimit = product.stock_quantity !== null && product.stock_quantity !== undefined && inCartQty >= product.stock_quantity;
              return (
                <div key={product.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", opacity: isOutOfStock ? 0.6 : 1 }}>
                  <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                    {product.image_url ? (
                      <img
                        src={resolveImageUrl(product.image_url)}
                        alt={product.name}
                        style={{ width: "56px", height: "56px", objectFit: "cover", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)", flexShrink: 0 }}
                      />
                    ) : (
                      <div style={{ width: "56px", height: "56px", borderRadius: "var(--radius-sm)", border: "1px dashed var(--border-color)", flexShrink: 0 }} />
                    )}
                    <div>
                      <strong style={{ fontSize: "14px" }}>{product.name}</strong>
                      {product.description && (
                        <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{product.description}</div>
                      )}
                      <div style={{ fontSize: "13px", color: "var(--accent)", fontWeight: 600 }}>₹{product.price.toFixed(2)}</div>
                      {product.review_count > 0 ? (
                        <div style={{ fontSize: "11.5px", color: "var(--text-secondary)" }}>
                          ★ {product.average_rating} ({product.review_count} review{product.review_count === 1 ? "" : "s"})
                        </div>
                      ) : (
                        <div style={{ fontSize: "11.5px", color: "var(--text-muted)" }}>No reviews yet</div>
                      )}
                      {isOutOfStock ? (
                        <div style={{ fontSize: "11.5px", color: "var(--danger)", fontWeight: 600 }}>Out of stock</div>
                      ) : product.stock_quantity !== null && product.stock_quantity !== undefined && product.stock_quantity <= 5 ? (
                        <div style={{ fontSize: "11.5px", color: "var(--danger)" }}>Only {product.stock_quantity} left</div>
                      ) : null}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end" }}>
                    <button
                      className="btn btn-primary"
                      style={{ fontSize: "12px" }}
                      onClick={() => handleAddToCart(product)}
                      disabled={isOutOfStock || isAtStockLimit}
                    >
                      {isOutOfStock ? "Sold out" : isAtStockLimit ? "Max in cart" : "Add"}
                    </button>
                    {!isOutOfStock && (
                      <button
                        className="btn"
                        style={{ fontSize: "11px", padding: "2px 8px" }}
                        onClick={() => openSubscribeForm(product)}
                        title="Set up a recurring order for this item"
                      >
                        ⟳ Subscribe
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {products.length === 0 && (
              <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>No products available right now.</p>
            )}
          </div>
        </div>
      )}

      {subscribeSuccess && (
        <div className="card" style={{ borderColor: "var(--accent)", margin: "16px 0" }}>
          {subscribeSuccess}
          <div style={{ marginTop: "8px" }}>
            <button className="btn" style={{ fontSize: "12px" }} onClick={() => setSubscribeSuccess(null)}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {subscribingProduct && (
        <div
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: "16px",
          }}
          onClick={() => setSubscribingProduct(null)}
        >
          <div className="card" style={{ maxWidth: "420px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Subscribe to "{subscribingProduct.name}"</h3>
            <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>
              We'll get an order ready for you every N days — you confirm and pay each time, nothing is ever
              charged automatically.
            </p>
            {subscribeError && (
              <div className="card" style={{ borderColor: "var(--danger)", marginBottom: "10px", fontSize: "13px" }}>
                {subscribeError}
              </div>
            )}
            <form onSubmit={handleCreateSubscription} style={{ display: "grid", gap: "10px" }}>
              <div className="auth-field">
                <label>Repeat every (days)</label>
                <input
                  className="input" type="number" min="1" value={subscribeInterval}
                  onChange={(e) => setSubscribeInterval(e.target.value)} required
                />
              </div>
              <div className="auth-field">
                <label>Quantity</label>
                <input
                  className="input" type="number" min="1" value={subscribeQuantity}
                  onChange={(e) => setSubscribeQuantity(parseInt(e.target.value, 10) || 1)} required
                />
              </div>
              <div className="auth-field">
                <label>Delivery address</label>
                <input className="input" type="text" value={subscribeAddress} onChange={(e) => setSubscribeAddress(e.target.value)} required />
              </div>
              <div className="auth-field">
                <label>City</label>
                <input className="input" type="text" value={subscribeCity} onChange={(e) => setSubscribeCity(e.target.value)} />
              </div>
              <div className="auth-field">
                <label>Phone</label>
                <input className="input" type="tel" value={subscribePhone} onChange={(e) => setSubscribePhone(e.target.value)} required />
              </div>
              <div className="auth-field">
                <label>Payment</label>
                <select className="input" value={subscribePaymentMethod} onChange={(e) => setSubscribePaymentMethod(e.target.value)}>
                  <option value="online">Online (pay each cycle)</option>
                  <option value="cod">Cash on delivery</option>
                </select>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button type="submit" className="btn btn-primary" disabled={isCreatingSubscription}>
                  {isCreatingSubscription ? "Setting up..." : "Start Subscription"}
                </button>
                <button type="button" className="btn" onClick={() => setSubscribingProduct(null)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
