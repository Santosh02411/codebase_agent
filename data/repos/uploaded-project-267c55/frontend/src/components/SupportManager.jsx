import React, { useEffect, useState } from "react";
import {
  fetchSupportTickets, fetchSupportTicketMessages, replyToSupportTicket,
  updateSupportTicket, resolveSupportTicket, fetchSupportAnalytics,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const CATEGORY_LABELS = {
  delivery_issue: "Delivery Issue", order_issue: "Order Issue", payment_issue: "Payment Issue",
  product_issue: "Product Issue", account_issue: "Account Issue", other: "Other",
};
const STATUSES = ["open", "in_progress", "resolved", "closed"];
const PRIORITIES = ["low", "normal", "high", "urgent"];

/** Staff-facing support ticket triage (Phase 12): dispatcher/admin only. */
export default function SupportManager() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [tickets, setTickets] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [replyText, setReplyText] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const [resolutionNotes, setResolutionNotes] = useState("");

  useEffect(() => { loadTickets(); loadAnalytics(); }, [statusFilter]);
  useEffect(() => { if (selectedId) loadMessages(selectedId); }, [selectedId]);

  async function loadTickets() {
    try {
      const data = await fetchSupportTickets(token, { status: statusFilter });
      setTickets(data);
      if (data.length > 0 && !selectedId) setSelectedId(data[0].id);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadAnalytics() {
    try {
      setAnalytics(await fetchSupportAnalytics(token));
    } catch (err) {}
  }

  async function loadMessages(ticketId) {
    try {
      setMessages(await fetchSupportTicketMessages(token, ticketId));
    } catch (err) {}
  }

  async function handleReply(e) {
    e.preventDefault();
    if (!replyText.trim()) return;
    try {
      await replyToSupportTicket(token, selectedId, replyText, isInternal);
      setReplyText("");
      setIsInternal(false);
      await loadMessages(selectedId);
      await loadTickets();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleStatusChange(status) {
    try {
      await updateSupportTicket(token, selectedId, { status });
      showToast("Status updated.", "success");
      await loadTickets();
      await loadAnalytics();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handlePriorityChange(priority) {
    try {
      await updateSupportTicket(token, selectedId, { priority });
      await loadTickets();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleResolve(e) {
    e.preventDefault();
    try {
      await resolveSupportTicket(token, selectedId, resolutionNotes);
      showToast("Ticket resolved.", "success");
      setResolutionNotes("");
      await loadTickets();
      await loadAnalytics();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const selected = tickets.find((t) => t.id === selectedId);

  return (
    <div>
      <h2 className="page-title">Customer Support</h2>

      {analytics && (
        <div className="card" style={{ marginBottom: "20px", display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <div><strong>{analytics.total_tickets}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Total Tickets</div></div>
          <div><strong>{analytics.by_status.open || 0}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Open</div></div>
          <div><strong>{analytics.by_status.in_progress || 0}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>In Progress</div></div>
          <div><strong>{analytics.open_disputes}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Open Disputes</div></div>
          <div><strong>{analytics.avg_resolution_hours != null ? `${analytics.avg_resolution_hours}h` : "—"}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Avg Resolution Time</div></div>
        </div>
      )}

      <div style={{ marginBottom: "12px" }}>
        <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: "16px" }}>
        <div className="card" style={{ padding: 0, maxHeight: "560px", overflowY: "auto" }}>
          {tickets.length === 0 && <div style={{ padding: "16px", color: "var(--text-muted)" }}>No tickets.</div>}
          {tickets.map((t) => (
            <div
              key={t.id}
              onClick={() => setSelectedId(t.id)}
              style={{
                padding: "12px", borderBottom: "1px solid var(--border-color, #eee)", cursor: "pointer",
                background: t.id === selectedId ? "var(--hover-bg, rgba(0,0,0,0.03))" : undefined,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: "14px" }}>
                {t.subject} {t.is_dispute && <span style={{ color: "var(--danger, #b91c1c)" }}>· Dispute</span>}
              </div>
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{t.status} · {t.priority} · {CATEGORY_LABELS[t.category]}</div>
            </div>
          ))}
        </div>

        {selected && (
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
              <div>
                <strong>{selected.subject}</strong>
                <p style={{ marginTop: "6px" }}>{selected.description}</p>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <select className="input" value={selected.status} onChange={(e) => handleStatusChange(e.target.value)}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <select className="input" value={selected.priority} onChange={(e) => handlePriorityChange(e.target.value)}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>

            <div style={{ borderTop: "1px solid var(--border-color, #eee)", paddingTop: "12px", marginBottom: "12px", maxHeight: "260px", overflowY: "auto" }}>
              {messages.length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No messages yet.</div>}
              {messages.map((m) => (
                <div key={m.id} style={{ marginBottom: "10px", opacity: m.is_internal_note ? 0.75 : 1 }}>
                  <div style={{ fontSize: "12px", fontWeight: 600 }}>
                    {m.sender_display_name} {m.is_internal_note && <span style={{ color: "var(--warning, #b45309)" }}>(internal note)</span>}
                  </div>
                  <div style={{ fontSize: "13px" }}>{m.message}</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>{new Date(m.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>

            <form onSubmit={handleReply} style={{ display: "flex", gap: "8px", marginBottom: "12px", flexWrap: "wrap" }}>
              <input className="input" style={{ flex: 1 }} placeholder="Reply to customer, or check 'internal note'..." value={replyText} onChange={(e) => setReplyText(e.target.value)} />
              <label style={{ fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}>
                <input type="checkbox" checked={isInternal} onChange={(e) => setIsInternal(e.target.checked)} /> Internal note
              </label>
              <button type="submit" className="btn btn-primary">Send</button>
            </form>

            {selected.status !== "resolved" && selected.status !== "closed" && (
              <form onSubmit={handleResolve} style={{ display: "flex", gap: "8px" }}>
                <input className="input" style={{ flex: 1 }} placeholder="Resolution notes..." required value={resolutionNotes} onChange={(e) => setResolutionNotes(e.target.value)} />
                <button type="submit" className="btn btn-secondary">Resolve</button>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
