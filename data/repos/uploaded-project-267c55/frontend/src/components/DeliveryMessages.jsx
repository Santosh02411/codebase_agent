import React, { useEffect, useState, useRef } from "react";
import { fetchDeliveryMessages, sendDeliveryMessage, fetchMessageTemplates } from "../services/api";
import { useAuth } from "../context/AuthContext";
import {
  setActiveChatUser,
  queueChatMessage,
  getQueuedChatMessages,
} from "../services/chatOfflineQueue";
import { startChatAutoSync } from "../services/chatSyncEngine";
import { writeSyncContext } from "../services/backgroundSyncContext";
import { API_BASE_URL } from "../services/api";
import { connectWebSocket } from "../services/websocket";

/**
 * A simple chat thread for one delivery, between the assigned agent and
 * their organization's dispatchers/admins. Separate from the delivery's
 * "notes" field (a single current-state note) and from the status
 * history log (an automatic audit trail) — this is an actual
 * back-and-forth conversation.
 *
 * Offline-first: sending with no connection queues the message locally
 * (shown immediately, tagged "queued offline") instead of failing, and
 * it's sent automatically the moment connectivity returns — the same
 * pattern already used for delivery status updates.
 *
 * New messages arrive over a live WebSocket connection (routes/websockets.py)
 * instead of polling — the other person's reply shows up the moment
 * they send it, with no 5-second lag and no wasted requests while the
 * thread just sits idle.
 */
export default function DeliveryMessages({ deliveryId, isSyncedToServer }) {
  const { token, user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [queuedMessages, setQueuedMessages] = useState([]);
  const [newMessage, setNewMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState(null);
  const [templates, setTemplates] = useState([]);
  const threadEndRef = useRef(null);

  useEffect(() => {
    fetchMessageTemplates(token).then(setTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    if (!isSyncedToServer) return; // no server-side id to attach messages to yet

    setActiveChatUser(user.id);
    writeSyncContext({ userId: user.id, token, role: user.role, apiBaseUrl: API_BASE_URL });
    loadMessages();
    loadQueuedMessages();

    const socket = connectWebSocket(
      `/ws/deliveries/${deliveryId}/messages?token=${encodeURIComponent(token)}`,
      {
        onMessage: (data) => {
          if (data.event !== "new_message") return;
          setMessages((prev) => {
            if (prev.some((m) => m.id === data.message.id)) return prev; // already have it (e.g. we sent it ourselves)
            return [...prev, data.message];
          });
        },
      }
    );
    const stopChatSync = startChatAutoSync(token, () => {
      loadMessages();
      loadQueuedMessages();
    });

    return () => {
      socket.close();
      stopChatSync();
    };
  }, [deliveryId, isSyncedToServer]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, queuedMessages.length]);

  async function loadMessages() {
    try {
      const data = await fetchDeliveryMessages(token, deliveryId);
      setMessages(data);
      setError(null);
    } catch (err) {
      // Offline or unreachable — keep showing whatever's already loaded
      // (plus locally queued messages below) instead of clearing the thread.
      if (!(err instanceof TypeError)) setError(err.message);
    }
  }

  async function loadQueuedMessages() {
    const queued = await getQueuedChatMessages(deliveryId);
    setQueuedMessages(queued);
  }

  async function handleSend(e) {
    e.preventDefault();
    const text = newMessage.trim();
    if (!text) return;

    setIsSending(true);
    setNewMessage("");
    try {
      await sendDeliveryMessage(token, deliveryId, text);
      await loadMessages();
    } catch (err) {
      if (err instanceof TypeError) {
        // No connection — queue it. It'll show up immediately below
        // (tagged "queued offline") and send automatically once online.
        await queueChatMessage(deliveryId, text, user.display_name, user.role);
        await loadQueuedMessages();
      } else {
        setError(err.message);
        setNewMessage(text); // restore what they typed so it isn't lost on a real error
      }
    } finally {
      setIsSending(false);
    }
  }

  if (!isSyncedToServer) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: "13px" }}>
        This delivery hasn't synced to the server yet, so messaging isn't
        available until it does.
      </p>
    );
  }

  // Merge server messages with locally-queued-but-unsent ones into a
  // single chronological thread, so a queued message appears exactly
  // where it belongs rather than in a separate disconnected list.
  const combinedThread = [
    ...messages.map((m) => ({ ...m, _pending: false, _sortKey: m.created_at })),
    ...queuedMessages.map((m) => ({
      id: `queued-${m.id}`,
      sender_id: user.id,
      sender_display_name: m.sender_display_name,
      sender_role: m.sender_role,
      message: m.message,
      created_at: m.queued_at,
      _pending: true,
      _sortKey: m.queued_at,
    })),
  ].sort((a, b) => new Date(a._sortKey) - new Date(b._sortKey));

  return (
    <div>
      <div
        style={{
          maxHeight: "220px",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          marginBottom: "10px",
        }}
      >
        {combinedThread.length === 0 && (
          <p style={{ color: "var(--text-muted)", fontSize: "13px" }}>
            No messages yet. Say something below.
          </p>
        )}
        {combinedThread.map((m) => {
          const isMine = m.sender_id === user.id;
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
                opacity: m._pending ? 0.65 : 1,
              }}
            >
              <div style={{ fontSize: "11px", fontWeight: 600, opacity: 0.85, marginBottom: "2px" }}>
                {m.sender_display_name} · {m.sender_role}
              </div>
              <div style={{ fontSize: "13.5px" }}>{m.message}</div>
              <div style={{ fontSize: "10.5px", opacity: 0.7, marginTop: "3px" }}>
                {m._pending ? "Queued offline — will send when back online" : new Date(m.created_at).toLocaleString()}
              </div>
            </div>
          );
        })}
        <div ref={threadEndRef} />
      </div>

      {error && <p style={{ color: "var(--danger)", fontSize: "12.5px" }}>{error}</p>}

      {templates.length > 0 && (
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "8px" }}>
          {templates.map((t) => (
            <button
              key={t}
              type="button"
              className="btn-info-outline"
              style={{ fontSize: "11.5px" }}
              onClick={() => setNewMessage(t)}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={handleSend} style={{ display: "flex", gap: "8px" }}>
        <input
          className="input"
          type="text"
          value={newMessage}
          onChange={(e) => setNewMessage(e.target.value)}
          placeholder="Type a message..."
          style={{ flexGrow: 1 }}
        />
        <button type="submit" className="btn btn-primary" disabled={isSending || !newMessage.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
