import React, { useEffect, useState, useRef } from "react";
import { fetchCustomerMessages, sendCustomerMessage } from "../services/api";
import { useCustomerAuth } from "../context/CustomerAuthContext";
import { connectWebSocket } from "../services/websocket";

const POLL_INTERVAL_MS = 8000; // fallback if the socket drops — mirrors DeliveryMessages.jsx's tolerance for being offline/unreachable

/**
 * Customer side of the Phase 6 chat thread — reads/writes the exact
 * same delivery_messages rows as the staff-side DeliveryMessages.jsx,
 * via the customer-scoped endpoints in routes/customer_messages.py.
 * Live updates over the same WebSocket room
 * (routes/websockets.py's chat_websocket now accepts a customer token
 * too), with periodic polling as a fallback for the same reasons the
 * staff side already tolerates being offline.
 */
export default function CustomerDeliveryMessages({ deliveryId }) {
  const { token, customer } = useCustomerAuth();
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState(null);
  const threadEndRef = useRef(null);

  useEffect(() => {
    loadMessages();

    const socket = connectWebSocket(`/ws/deliveries/${deliveryId}/messages?token=${encodeURIComponent(token)}`, {
      onMessage: (data) => {
        if (data.event !== "new_message") return;
        setMessages((prev) => (prev.some((m) => m.id === data.message.id) ? prev : [...prev, data.message]));
      },
    });
    const pollId = setInterval(loadMessages, POLL_INTERVAL_MS);

    return () => {
      socket.close();
      clearInterval(pollId);
    };
  }, [deliveryId]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function loadMessages() {
    try {
      const data = await fetchCustomerMessages(token, deliveryId);
      setMessages(data);
      setError(null);
    } catch (err) {
      if (!(err instanceof TypeError)) setError(err.message);
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    const text = newMessage.trim();
    if (!text) return;
    setIsSending(true);
    setNewMessage("");
    try {
      await sendCustomerMessage(token, deliveryId, text);
      await loadMessages();
    } catch (err) {
      setError(err.message);
      setNewMessage(text);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div>
      <div style={{ maxHeight: "220px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "8px", marginBottom: "10px" }}>
        {messages.length === 0 && (
          <p style={{ color: "var(--text-muted)", fontSize: "13px" }}>No messages yet. Ask a question about your delivery below.</p>
        )}
        {messages.map((m) => {
          const isMine = m.sender_role === "customer";
          return (
            <div
              key={m.id}
              style={{
                alignSelf: isMine ? "flex-end" : "flex-start",
                maxWidth: "80%",
                backgroundColor: isMine ? "var(--accent)" : "var(--bg-input)",
                color: isMine ? "var(--accent-text-on)" : "var(--text-primary)",
                padding: "8px 12px",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <div style={{ fontSize: "11px", fontWeight: 600, opacity: 0.85, marginBottom: "2px" }}>
                {isMine ? "You" : m.sender_display_name}
              </div>
              <div style={{ fontSize: "13.5px" }}>{m.message}</div>
              <div style={{ fontSize: "10.5px", opacity: 0.7, marginTop: "3px" }}>{new Date(m.created_at).toLocaleString()}</div>
            </div>
          );
        })}
        <div ref={threadEndRef} />
      </div>

      {error && <p style={{ color: "var(--danger)", fontSize: "12.5px" }}>{error}</p>}

      <form onSubmit={handleSend} style={{ display: "flex", gap: "8px" }}>
        <input
          className="input"
          type="text"
          value={newMessage}
          onChange={(e) => setNewMessage(e.target.value)}
          placeholder="Ask about your delivery..."
          style={{ flexGrow: 1 }}
        />
        <button type="submit" className="btn btn-primary" disabled={isSending || !newMessage.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
