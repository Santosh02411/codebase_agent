import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { fetchActiveFailedDeliveryReasons } from "../services/api";

const STATUS_OPTIONS = [
  { value: "picked_up", label: "Picked Up" },
  { value: "out_for_delivery", label: "Out for Delivery" },
  { value: "delivered", label: "Delivered" },
  { value: "failed_attempt", label: "Failed Attempt" },
];

/**
 * Lets the agent change a delivery's status and add an optional note.
 * Calls `onUpdate` with the new status/notes/extras — the parent
 * component (AgentDeliveryList) is responsible for actually saving it
 * to IndexedDB.
 *
 * Two status choices need extra info before they can go through:
 * - "Failed Attempt" requires picking a standardized reason code (see
 *   models/failed_delivery_reason.py) — enforced server-side too, but
 *   gated here first so an agent isn't surprised by a rejected sync
 *   later.
 * - "Delivered" offers an optional "Partially delivered" toggle with
 *   its own notes field, for when not everything ordered actually got
 *   handed over.
 */
export default function DeliveryStatusUpdater({ deliveryId, currentStatus, onUpdate }) {
  const { token } = useAuth();
  const [notes, setNotes] = useState("");
  const [reasonCodes, setReasonCodes] = useState([]);
  const [pendingFailure, setPendingFailure] = useState(false);
  const [selectedReasonId, setSelectedReasonId] = useState("");
  const [pendingDelivery, setPendingDelivery] = useState(false);
  const [isPartial, setIsPartial] = useState(false);
  const [partialNotes, setPartialNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (navigator.onLine) {
      fetchActiveFailedDeliveryReasons(token)
        .then((reasons) => {
          if (!cancelled) setReasonCodes(reasons);
        })
        .catch(() => {
          /* offline or request failed — reason picker just stays empty; the
             agent can still pick "Other" once connectivity returns */
        });
    }
    return () => {
      cancelled = true;
    };
  }, [token]);

  const resetPickers = () => {
    setPendingFailure(false);
    setSelectedReasonId("");
    setPendingDelivery(false);
    setIsPartial(false);
    setPartialNotes("");
    setNotes("");
  };

  const handleStatusClick = (newStatus) => {
    if (newStatus === "failed_attempt") {
      setPendingFailure(true);
      setPendingDelivery(false);
      return;
    }
    if (newStatus === "delivered") {
      setPendingDelivery(true);
      setPendingFailure(false);
      return;
    }
    onUpdate(deliveryId, newStatus, notes, {});
    resetPickers();
  };

  const confirmFailure = () => {
    if (!selectedReasonId) return;
    onUpdate(deliveryId, "failed_attempt", notes, { reason_code_id: selectedReasonId });
    resetPickers();
  };

  const confirmDelivered = () => {
    onUpdate(deliveryId, "delivered", notes, {
      is_partial: isPartial,
      partial_notes: isPartial ? partialNotes : null,
    });
    resetPickers();
  };

  return (
    <div style={{ marginTop: "12px" }}>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
        {STATUS_OPTIONS.map((option) => {
          const isCurrent = option.value === currentStatus;
          return (
            <button
              key={option.value}
              onClick={() => handleStatusClick(option.value)}
              disabled={isCurrent}
              className={isCurrent ? "btn" : "btn btn-primary"}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      {!pendingFailure && !pendingDelivery && (
        <input
          type="text"
          className="input"
          placeholder="Optional note (e.g. customer not available)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          style={{ marginTop: "10px", width: "100%" }}
        />
      )}

      {pendingFailure && (
        <div style={{ marginTop: "10px", padding: "10px", border: "1px solid var(--border)", borderRadius: "8px" }}>
          <label style={{ fontSize: "13px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
            Why did this attempt fail?
          </label>
          <select
            className="input"
            value={selectedReasonId}
            onChange={(e) => setSelectedReasonId(e.target.value)}
            style={{ width: "100%" }}
          >
            <option value="">Select a reason…</option>
            {reasonCodes.map((r) => (
              <option key={r.id} value={r.id}>{r.label}</option>
            ))}
          </select>
          {reasonCodes.length === 0 && (
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "6px" }}>
              No reason codes loaded — check your connection, or ask an admin to add some.
            </p>
          )}
          <input
            type="text"
            className="input"
            placeholder="Additional details (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{ marginTop: "8px", width: "100%" }}
          />
          <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
            <button className="btn btn-primary" onClick={confirmFailure} disabled={!selectedReasonId}>
              Confirm Failed Attempt
            </button>
            <button className="btn" onClick={resetPickers}>Cancel</button>
          </div>
        </div>
      )}

      {pendingDelivery && (
        <div style={{ marginTop: "10px", padding: "10px", border: "1px solid var(--border)", borderRadius: "8px" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
            <input type="checkbox" checked={isPartial} onChange={(e) => setIsPartial(e.target.checked)} />
            Only part of the order was delivered
          </label>
          {isPartial && (
            <input
              type="text"
              className="input"
              placeholder="What's missing? (e.g. 1 of 3 items not on vehicle)"
              value={partialNotes}
              onChange={(e) => setPartialNotes(e.target.value)}
              style={{ marginTop: "8px", width: "100%" }}
            />
          )}
          <input
            type="text"
            className="input"
            placeholder="Optional note"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{ marginTop: "8px", width: "100%" }}
          />
          <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
            <button className="btn btn-primary" onClick={confirmDelivered}>
              Confirm Delivered
            </button>
            <button className="btn" onClick={resetPickers}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
