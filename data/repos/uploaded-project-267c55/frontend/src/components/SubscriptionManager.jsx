import React, { useEffect, useState } from "react";
import {
  fetchMySubscriptions,
  updateSubscription,
  pauseSubscription,
  resumeSubscription,
  cancelSubscription,
  runSubscriptionNow,
  initiateSubscriptionOrderPayment,
  verifyPayment,
} from "../services/api";
import "../styles/auth.css";

/**
 * Loads Razorpay's Checkout.js widget once, only when actually needed -
 * same pattern as Storefront.jsx's loadRazorpayScript (duplicated here
 * rather than imported so this component has no hard dependency on the
 * Storefront module).
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

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

const STATUS_LABELS = { active: "Active", paused: "Paused", cancelled: "Cancelled" };

export default function SubscriptionManager({ token }) {
  const [subscriptions, setSubscriptions] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editInterval, setEditInterval] = useState("");
  const [editAddress, setEditAddress] = useState("");
  const [editCity, setEditCity] = useState("");
  const [editPhone, setEditPhone] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setIsLoading(true);
    try {
      const data = await fetchMySubscriptions(token);
      setSubscriptions(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  function startEdit(sub) {
    setEditingId(sub.id);
    setEditInterval(String(sub.interval_days));
    setEditAddress(sub.address_line);
    setEditCity(sub.city || "");
    setEditPhone(sub.phone);
    setError(null);
  }

  async function saveEdit(subId) {
    const intervalDays = parseInt(editInterval, 10);
    if (!intervalDays || intervalDays < 1) {
      setError("Interval must be at least 1 day.");
      return;
    }
    setBusyId(subId);
    setError(null);
    try {
      await updateSubscription(token, subId, {
        interval_days: intervalDays,
        address_line: editAddress,
        city: editCity,
        phone: editPhone,
      });
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleAction(subId, actionFn, successText) {
    setBusyId(subId);
    setError(null);
    setSuccessMessage(null);
    try {
      await actionFn(token, subId);
      if (successText) setSuccessMessage(successText);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function handlePayPendingOrder(sub) {
    setBusyId(sub.id);
    setError(null);
    setSuccessMessage(null);
    try {
      const resp = await initiateSubscriptionOrderPayment(token, sub.pending_order_id);

      if (resp.payment_method === "cod" || resp.is_test_mode) {
        await verifyPayment(token, { order_id: resp.order_id });
        setSuccessMessage(
          resp.payment_method === "cod"
            ? "Confirmed — you'll pay in cash on delivery."
            : "Confirmed (test mode) — the order is on its way to dispatch."
        );
        await load();
        return;
      }

      const scriptLoaded = await loadRazorpayScript();
      if (!scriptLoaded) {
        setError("Couldn't load the payment widget. Check your connection and try again.");
        setBusyId(null);
        return;
      }
      const razorpay = new window.Razorpay({
        key: resp.razorpay_key_id,
        amount: resp.amount_paise,
        currency: resp.currency,
        name: "Delivery Sync",
        description: "Recurring order",
        order_id: resp.razorpay_order_id,
        handler: async (paymentResponse) => {
          try {
            await verifyPayment(token, {
              order_id: resp.order_id,
              razorpay_payment_id: paymentResponse.razorpay_payment_id,
              razorpay_order_id: paymentResponse.razorpay_order_id,
              razorpay_signature: paymentResponse.razorpay_signature,
            });
            setSuccessMessage("Payment successful! Your recurring order has been placed.");
          } catch (err) {
            setError("Payment succeeded but confirming your order failed: " + err.message);
          } finally {
            await load();
          }
        },
        theme: { color: "#f2a93b" },
      });
      razorpay.open();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (isLoading) return <p>Loading your subscriptions...</p>;

  return (
    <div>
      <h2 style={{ marginBottom: "4px" }}>Recurring Orders</h2>
      <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "16px" }}>
        Reorder automatically every N days — nothing is ever charged without you confirming it first.
      </p>

      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: "12px" }}>{error}</div>}
      {successMessage && (
        <div className="card" style={{ borderColor: "var(--accent)", marginBottom: "12px" }}>{successMessage}</div>
      )}

      {subscriptions.length === 0 && (
        <p style={{ color: "var(--text-muted)" }}>
          You don't have any recurring orders yet. Subscribe to a product from the Shop tab to set one up.
        </p>
      )}

      {subscriptions.map((sub) => (
        <div key={sub.id} className="card" style={{ marginBottom: "14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <strong>Every {sub.interval_days} day{sub.interval_days === 1 ? "" : "s"}</strong>
              <span
                style={{
                  marginLeft: "10px",
                  fontSize: "11px",
                  padding: "2px 8px",
                  borderRadius: "10px",
                  background: sub.status === "active" ? "var(--accent)" : "var(--border)",
                  color: sub.status === "active" ? "#1a1a1a" : "var(--text-muted)",
                }}
              >
                {STATUS_LABELS[sub.status]}
              </span>
              <div style={{ fontSize: "12.5px", color: "var(--text-muted)", marginTop: "4px" }}>
                Next order: {formatDate(sub.next_run_date)}
              </div>
            </div>
          </div>

          <ul style={{ margin: "10px 0", paddingLeft: "18px", fontSize: "13.5px" }}>
            {sub.items.map((item) => (
              <li key={item.product_id}>
                {item.quantity}x {item.product_name || "Item"} {item.unit_price != null && `— ₹${item.unit_price.toFixed(2)} each`}
              </li>
            ))}
          </ul>

          {sub.pending_order_id && (
            <div className="card" style={{ borderColor: "var(--accent)", marginBottom: "10px" }}>
              <strong>Ready to reorder</strong> — ₹{sub.pending_order_total?.toFixed(2)}
              <div style={{ marginTop: "8px" }}>
                <button
                  className="btn btn-primary"
                  disabled={busyId === sub.id}
                  onClick={() => handlePayPendingOrder(sub)}
                >
                  {sub.payment_method === "cod" ? "Confirm Order (Pay on Delivery)" : `Confirm & Pay ₹${sub.pending_order_total?.toFixed(2)}`}
                </button>
              </div>
            </div>
          )}

          {editingId === sub.id ? (
            <div style={{ display: "grid", gap: "8px", marginTop: "8px" }}>
              <div className="auth-field">
                <label htmlFor={`sub-edit-interval-${sub.id}`}>Repeat every (days)</label>
                <input id={`sub-edit-interval-${sub.id}`} className="input" type="number" min="1" value={editInterval} onChange={(e) => setEditInterval(e.target.value)} />
              </div>
              <div className="auth-field">
                <label htmlFor={`sub-edit-address-${sub.id}`}>Address</label>
                <input id={`sub-edit-address-${sub.id}`} className="input" type="text" value={editAddress} onChange={(e) => setEditAddress(e.target.value)} />
              </div>
              <div className="auth-field">
                <label htmlFor={`sub-edit-city-${sub.id}`}>City</label>
                <input id={`sub-edit-city-${sub.id}`} className="input" type="text" value={editCity} onChange={(e) => setEditCity(e.target.value)} />
              </div>
              <div className="auth-field">
                <label htmlFor={`sub-edit-phone-${sub.id}`}>Phone</label>
                <input id={`sub-edit-phone-${sub.id}`} className="input" type="tel" value={editPhone} onChange={(e) => setEditPhone(e.target.value)} />
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button className="btn btn-primary" disabled={busyId === sub.id} onClick={() => saveEdit(sub.id)}>
                  Save
                </button>
                <button className="btn" onClick={() => setEditingId(null)}>Cancel</button>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: "12.5px", color: "var(--text-muted)", marginBottom: "10px" }}>
              Deliver to: {sub.address_line}{sub.city ? `, ${sub.city}` : ""} · {sub.phone} · {sub.payment_method === "cod" ? "Cash on delivery" : "Online payment"}
            </div>
          )}

          {sub.status !== "cancelled" && editingId !== sub.id && (
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <button className="btn" disabled={busyId === sub.id} onClick={() => startEdit(sub)}>Edit</button>
              {sub.status === "active" && !sub.pending_order_id && (
                <button className="btn" disabled={busyId === sub.id} onClick={() => handleAction(sub.id, runSubscriptionNow, "This cycle's order is ready below.")}>
                  Reorder Now
                </button>
              )}
              {sub.status === "active" ? (
                <button className="btn" disabled={busyId === sub.id} onClick={() => handleAction(sub.id, pauseSubscription, "Paused.")}>
                  Pause
                </button>
              ) : (
                <button className="btn" disabled={busyId === sub.id} onClick={() => handleAction(sub.id, resumeSubscription, "Resumed.")}>
                  Resume
                </button>
              )}
              <button
                className="btn"
                style={{ color: "var(--danger)" }}
                disabled={busyId === sub.id}
                onClick={() => {
                  if (window.confirm("Cancel this recurring order? This can't be undone.")) {
                    handleAction(sub.id, cancelSubscription, "Cancelled.");
                  }
                }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
