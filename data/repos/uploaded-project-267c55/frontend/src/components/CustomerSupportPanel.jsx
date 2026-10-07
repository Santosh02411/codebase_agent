import React, { useEffect, useState } from "react";
import {
  createSupportTicket, fetchMySupportTickets, fetchMySupportTicketMessages, replyToMySupportTicket,
} from "../services/api";
import { useCustomerAuth } from "../context/CustomerAuthContext";

const CATEGORY_LABELS = {
  delivery_issue: "Delivery Issue", order_issue: "Order Issue", payment_issue: "Payment Issue",
  product_issue: "Product Issue", account_issue: "Account Issue", other: "Other",
};
const STATUS_LABELS = { open: "Open", in_progress: "In Progress", resolved: "Resolved", closed: "Closed" };

/** Customer support panel (Phase 12) — create a ticket, browse own tickets, reply on the thread. */
export default function CustomerSupportPanel() {
  const { token } = useCustomerAuth();
  const [tickets, setTickets] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState(null);
  const [replyText, setReplyText] = useState("");

  const [showNewForm, setShowNewForm] = useState(false);
  const [newTicket, setNewTicket] = useState({ subject: "", description: "", category: "other" });

  useEffect(() => { loadTickets(); }, []);
  useEffect(() => { if (selectedId) loadMessages(selectedId); }, [selectedId]);

  async function loadTickets() {
    try {
      const data = await fetchMySupportTickets(token);
      setTickets(data);
      if (data.length > 0 && !selectedId) setSelectedId(data[0].id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadMessages(ticketId) {
    try {
      setMessages(await fetchMySupportTicketMessages(token, ticketId));
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    setError(null);
    try {
      const ticket = await createSupportTicket(token, newTicket);
      setNewTicket({ subject: "", description: "", category: "other" });
      setShowNewForm(false);
      await loadTickets();
      setSelectedId(ticket.id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleReply(e) {
    e.preventDefault();
    if (!replyText.trim()) return;
    try {
      await replyToMySupportTicket(token, selectedId, replyText);
      setReplyText("");
      await loadMessages(selectedId);
      await loadTickets();
    } catch (err) {
      setError(err.message);
    }
  }

  const selected = tickets.find((t) => t.id === selectedId);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ margin: 0 }}>Support</h2>
        <button className="btn btn-primary" onClick={() => setShowNewForm(!showNewForm)}>
          {showNewForm ? "Cancel" : "New Ticket"}
        </button>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: "12px" }}>{error}</div>}

      {showNewForm && (
        <form onSubmit={handleCreate} className="card" style={{ marginBottom: "20px" }}>
          <div style={{ marginBottom: "10px" }}>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Category</label>
            <select className="input" value={newTicket.category} onChange={(e) => setNewTicket({ ...newTicket, category: e.target.value })}>
              {Object.keys(CATEGORY_LABELS).map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: "10px" }}>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Subject</label>
            <input className="input" required value={newTicket.subject} onChange={(e) => setNewTicket({ ...newTicket, subject: e.target.value })} />
          </div>
          <div style={{ marginBottom: "10px" }}>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Description</label>
            <textarea className="input" rows={4} required value={newTicket.description} onChange={(e) => setNewTicket({ ...newTicket, description: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-primary">Submit Ticket</button>
        </form>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "16px" }}>
        <div className="card" style={{ padding: 0, maxHeight: "480px", overflowY: "auto" }}>
          {tickets.length === 0 && <div style={{ padding: "16px", color: "var(--text-muted)" }}>No support tickets yet.</div>}
          {tickets.map((t) => (
            <div
              key={t.id}
              onClick={() => setSelectedId(t.id)}
              style={{
                padding: "12px", borderBottom: "1px solid var(--border-color, #eee)", cursor: "pointer",
                background: t.id === selectedId ? "var(--hover-bg, rgba(0,0,0,0.03))" : undefined,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: "14px" }}>{t.subject}</div>
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{STATUS_LABELS[t.status]} · {CATEGORY_LABELS[t.category]}</div>
            </div>
          ))}
        </div>

        {selected && (
          <div className="card">
            <div style={{ marginBottom: "12px" }}>
              <strong>{selected.subject}</strong>
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{STATUS_LABELS[selected.status]} · {CATEGORY_LABELS[selected.category]}</div>
              <p style={{ marginTop: "8px" }}>{selected.description}</p>
            </div>
            <div style={{ borderTop: "1px solid var(--border-color, #eee)", paddingTop: "12px", marginBottom: "12px", maxHeight: "260px", overflowY: "auto" }}>
              {messages.length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No replies yet.</div>}
              {messages.map((m) => (
                <div key={m.id} style={{ marginBottom: "10px" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600 }}>{m.sender_type === "customer" ? "You" : m.sender_display_name}</div>
                  <div style={{ fontSize: "13px" }}>{m.message}</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>{new Date(m.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>
            {selected.status !== "closed" ? (
              <form onSubmit={handleReply} style={{ display: "flex", gap: "8px" }}>
                <input className="input" style={{ flex: 1 }} placeholder="Type a reply..." value={replyText} onChange={(e) => setReplyText(e.target.value)} />
                <button type="submit" className="btn btn-primary">Send</button>
              </form>
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>This ticket is closed.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
