import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  fetchFailedDeliveryReasons,
  createFailedDeliveryReason,
  updateFailedDeliveryReason,
  deleteFailedDeliveryReason,
} from "../services/api";

/**
 * Admin management of an org's standardized failed-delivery reason
 * codes (see backend/app/models/failed_delivery_reason.py). These
 * aren't just labels — PATCH /deliveries/{id} rejects a failed_attempt
 * update that doesn't reference one of these (active-only), so this
 * page is where an admin controls exactly what an agent is allowed to
 * pick when a delivery fails.
 */
export default function FailedDeliveryReasonManager() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [reasons, setReasons] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setIsLoading(true);
    try {
      const data = await fetchFailedDeliveryReasons(token);
      setReasons(data);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    setIsCreating(true);
    try {
      await createFailedDeliveryReason(token, { code: code.trim(), label: label.trim(), description: description.trim() || null });
      showToast("Reason code created.", "success");
      setCode("");
      setLabel("");
      setDescription("");
      setShowCreateForm(false);
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleToggleActive(reason) {
    try {
      await updateFailedDeliveryReason(token, reason.id, { active: !reason.active });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleDelete(reason) {
    try {
      await deleteFailedDeliveryReason(token, reason.id);
      showToast("Reason code deleted.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  if (isLoading) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ margin: 0 }}>Failed-Delivery Reason Codes</h2>
        <button className="btn btn-primary" onClick={() => setShowCreateForm(!showCreateForm)}>
          {showCreateForm ? "Cancel" : "+ New Reason Code"}
        </button>
      </div>
      <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "16px" }}>
        Agents can only mark a delivery "Failed Attempt" by picking one of your active reason codes here —
        this keeps the failure log standardized instead of free-text guesses. Deactivating a code hides it
        from the picker without breaking past attempts that already used it.
      </p>

      {showCreateForm && (
        <form onSubmit={handleCreate} className="card" style={{ marginBottom: "20px", maxWidth: "480px" }}>
          <div className="auth-field">
            <label htmlFor="fdr-code">Code</label>
            <input
              id="fdr-code"
              className="input"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. customer_unavailable"
              required
            />
          </div>
          <div className="auth-field">
            <label htmlFor="fdr-label">Label (shown to agents)</label>
            <input
              id="fdr-label"
              className="input"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Customer unavailable"
              required
            />
          </div>
          <div className="auth-field">
            <label htmlFor="fdr-description">Description (optional)</label>
            <input id="fdr-description" className="input" type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary" disabled={isCreating || !code.trim() || !label.trim()}>
            {isCreating ? "Creating..." : "Create Reason Code"}
          </button>
        </form>
      )}

      {reasons.length === 0 && !showCreateForm && (
        <p style={{ color: "var(--text-secondary)" }}>
          No reason codes yet — agents won't be able to mark a delivery failed until you add at least one.
        </p>
      )}

      <div style={{ display: "grid", gap: "10px" }}>
        {reasons.map((reason) => (
          <div key={reason.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong style={{ fontSize: "14px" }}>{reason.label}</strong>
              <span className="mono" style={{ fontSize: "11px", color: "var(--text-muted)", marginLeft: "8px" }}>
                {reason.code}
              </span>
              {!reason.active && (
                <span style={{ fontSize: "11px", color: "var(--text-muted)", marginLeft: "8px" }}>(inactive)</span>
              )}
              {reason.description && (
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>{reason.description}</div>
              )}
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button className="btn" onClick={() => handleToggleActive(reason)}>
                {reason.active ? "Deactivate" : "Activate"}
              </button>
              <button className="btn-danger-outline" onClick={() => handleDelete(reason)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
