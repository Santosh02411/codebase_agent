import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { fetchReturnRequests, approveReturnRequest, rejectReturnRequest } from "../services/api";

/**
 * Dispatcher/admin review queue for return/exchange requests. Approving
 * creates a real pickup delivery (shows up in the normal unassigned
 * queue right after) — this panel doesn't handle the pickup itself,
 * just the request decision. See models/return_request.py for the full
 * workflow this is one half of.
 */
export default function ReturnRequestsPanel() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [requests, setRequests] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("requested");
  const [noteByRequest, setNoteByRequest] = useState({});
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    load();
  }, [statusFilter]);

  async function load() {
    setIsLoading(true);
    try {
      setRequests(await fetchReturnRequests(token, statusFilter || undefined));
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleApprove(requestId) {
    setBusyId(requestId);
    try {
      await approveReturnRequest(token, requestId, noteByRequest[requestId]);
      showToast("Approved — a pickup delivery was created.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(requestId) {
    setBusyId(requestId);
    try {
      await rejectReturnRequest(token, requestId, noteByRequest[requestId]);
      showToast("Request rejected.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  if (isLoading) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ margin: 0 }}>Returns & Exchanges</h2>
        <select className="input" style={{ width: "auto", fontSize: "13px" }} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="requested">Awaiting review</option>
          <option value="approved">Approved (pickup in progress)</option>
          <option value="completed">Completed</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>

      {requests.length === 0 && (
        <p style={{ color: "var(--text-secondary)" }}>Nothing here right now.</p>
      )}

      <div style={{ display: "grid", gap: "12px" }}>
        {requests.map((req) => (
          <div key={req.id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <strong style={{ fontSize: "14px", textTransform: "capitalize" }}>{req.request_type}</strong>
                {" — "}
                <span className="mono" style={{ fontSize: "13px" }}>{req.order_id}</span>
                <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginTop: "4px" }}>
                  Reason: {req.reason}
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                  Requested {new Date(req.requested_at).toLocaleString()}
                </div>
                {req.resolution_note && (
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                    Note: {req.resolution_note}
                  </div>
                )}
              </div>
              <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                {req.status}
              </span>
            </div>

            {req.status === "requested" && (
              <div style={{ marginTop: "10px" }}>
                <input
                  className="input"
                  type="text"
                  placeholder="Optional note"
                  style={{ marginBottom: "8px" }}
                  value={noteByRequest[req.id] || ""}
                  onChange={(e) => setNoteByRequest({ ...noteByRequest, [req.id]: e.target.value })}
                />
                <div style={{ display: "flex", gap: "8px" }}>
                  <button className="btn btn-primary" onClick={() => handleApprove(req.id)} disabled={busyId === req.id}>
                    {busyId === req.id ? "Working..." : "Approve — Schedule Pickup"}
                  </button>
                  <button className="btn-danger-outline" onClick={() => handleReject(req.id)} disabled={busyId === req.id}>
                    Reject
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
