import React, { useEffect, useState } from "react";
import {
  fetchRtoRequests, approveRto, markRtoInTransit, markRtoReceived, cancelRto,
  fetchRtoAnalytics, fetchRtoSettings, updateRtoSettings,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const STATUS_LABELS = {
  eligible: "Eligible", approved: "Approved", in_transit: "In Transit",
  received_at_origin: "Received", cancelled: "Cancelled",
};
const STATUS_COLORS = {
  eligible: "var(--warning, #b45309)", approved: "var(--accent)", in_transit: "var(--accent)",
  received_at_origin: "var(--success, #16a34a)", cancelled: "var(--text-muted)",
};

const NEXT_ACTION = {
  eligible: { label: "Approve", fn: "approve" },
  approved: { label: "Mark In Transit", fn: "in_transit" },
  in_transit: { label: "Mark Received", fn: "received" },
};

/**
 * RTO (Return-to-Origin) management view (Phase 7). Every action here
 * calls the deliveries.assign-gated endpoints in routes/rto.py — a
 * dispatch-level decision, not something an agent's default
 * permissions include (see services/permissions.py).
 */
export default function RtoManager() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [requests, setRequests] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [analytics, setAnalytics] = useState(null);
  const [maxAttempts, setMaxAttempts] = useState("");

  useEffect(() => {
    loadRequests();
    loadAnalytics();
    loadSettings();
  }, [statusFilter]);

  async function loadRequests() {
    try {
      setRequests(await fetchRtoRequests(token, statusFilter || undefined));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadAnalytics() {
    try {
      setAnalytics(await fetchRtoAnalytics(token));
    } catch (err) {}
  }

  async function loadSettings() {
    try {
      const s = await fetchRtoSettings(token);
      setMaxAttempts(String(s.rto_max_attempts));
    } catch (err) {}
  }

  async function handleSaveSettings(e) {
    e.preventDefault();
    try {
      await updateRtoSettings(token, Number(maxAttempts));
      showToast("RTO settings updated.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAction(rto, actionFn) {
    try {
      if (actionFn === "approve") await approveRto(token, rto.id);
      else if (actionFn === "in_transit") await markRtoInTransit(token, rto.id);
      else if (actionFn === "received") await markRtoReceived(token, rto.id);
      showToast("RTO request updated.", "success");
      await loadRequests();
      await loadAnalytics();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCancel(rto) {
    const note = window.prompt("Reason for cancelling this RTO (e.g. reattempting delivery instead):", "");
    if (note === null) return;
    try {
      await cancelRto(token, rto.id, note || undefined);
      showToast("RTO request cancelled.", "success");
      await loadRequests();
      await loadAnalytics();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">Return to Origin (RTO)</h2>

      {analytics && (
        <div className="card" style={{ marginBottom: "20px", display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <Stat label="Total RTOs" value={analytics.total_rto_requests} />
          <Stat label="Eligible" value={analytics.eligible} color="var(--warning, #b45309)" />
          <Stat label="Approved" value={analytics.approved} />
          <Stat label="In Transit" value={analytics.in_transit} />
          <Stat label="Received" value={analytics.received_at_origin} color="var(--success, #16a34a)" />
          <Stat label="Refunds Issued" value={analytics.refunds_issued} />
          <Stat label="Avg. Resolution" value={analytics.avg_resolution_hours != null ? `${analytics.avg_resolution_hours}h` : "—"} />
        </div>
      )}

      <form onSubmit={handleSaveSettings} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "20px" }}>
        <div>
          <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>RTO after this many failed attempts</label>
          <input type="number" min={1} className="input" style={{ width: "100px" }} value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)} />
        </div>
        <button type="submit" className="btn btn-primary">Save</button>
      </form>

      <div style={{ marginBottom: "12px" }}>
        <select className="input" style={{ width: "200px" }} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {Object.keys(STATUS_LABELS).map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead><tr><th>Order</th><th>Reason</th><th>Status</th><th>Refund</th><th>Actions</th></tr></thead>
          <tbody>
            {requests.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>No RTO requests.</td></tr>}
            {requests.map((r) => {
              const next = NEXT_ACTION[r.status];
              return (
                <tr key={r.id}>
                  <td className="mono">{r.order_id ? r.order_id.slice(0, 8) : "—"}</td>
                  <td>{r.reason_label || "—"}</td>
                  <td style={{ color: STATUS_COLORS[r.status], fontWeight: 600 }}>{STATUS_LABELS[r.status]}</td>
                  <td>{r.refund_issued ? "Yes" : "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: "6px" }}>
                      {next && <button className="btn-info-outline" onClick={() => handleAction(r, next.fn)}>{next.label}</button>}
                      {(r.status === "eligible" || r.status === "approved") && (
                        <button className="btn-danger-outline" onClick={() => handleCancel(r)}>Cancel</button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {analytics && analytics.by_reason.length > 0 && (
        <div style={{ marginTop: "20px" }}>
          <h4 style={{ marginBottom: "8px" }}>By Reason</h4>
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Reason</th><th>Count</th></tr></thead>
              <tbody>
                {analytics.by_reason.map((r) => (
                  <tr key={r.reason}><td>{r.reason}</td><td>{r.count}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: "11px", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontSize: "20px", fontWeight: 700, color: color || "inherit" }}>{value}</div>
    </div>
  );
}
