import React, { useEffect, useState } from "react";
import {
  fetchApiKeys, createApiKey, rotateApiKey, revokeApiKey,
  fetchWebhooks, createWebhook, updateWebhook, deleteWebhook,
  fetchWebhookDeliveries, replayWebhookDelivery,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const API_SCOPES = ["deliveries:read", "deliveries:write", "orders:read", "webhooks:manage"];
const WEBHOOK_EVENTS = [
  "delivery.created", "delivery.assigned", "delivery.picked_up", "delivery.out_for_delivery",
  "delivery.delivered", "delivery.failed", "order.created", "order.paid", "order.cancelled",
  "refund.created", "return.created",
];

/** Staff-facing API keys & webhooks admin (Phase 14): dispatcher/admin only. */
export default function ApiWebhooksManager() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [keys, setKeys] = useState([]);
  const [webhooks, setWebhooks] = useState([]);
  const [selectedWebhookId, setSelectedWebhookId] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  const [revealedKey, setRevealedKey] = useState(null); // { name, raw_key } shown once after create/rotate

  const [keyForm, setKeyForm] = useState({ name: "", scopes: [] });
  const [webhookForm, setWebhookForm] = useState({ url: "", subscribed_events: [] });

  useEffect(() => { loadKeys(); loadWebhooks(); }, []);
  useEffect(() => { if (selectedWebhookId) loadDeliveries(selectedWebhookId); }, [selectedWebhookId]);

  async function loadKeys() {
    try {
      setKeys(await fetchApiKeys(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadWebhooks() {
    try {
      const data = await fetchWebhooks(token);
      setWebhooks(data);
      if (data.length > 0 && !selectedWebhookId) setSelectedWebhookId(data[0].id);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadDeliveries(webhookId) {
    try {
      setDeliveries(await fetchWebhookDeliveries(token, webhookId));
    } catch (err) {}
  }

  function toggleScope(scope) {
    setKeyForm((f) => ({
      ...f, scopes: f.scopes.includes(scope) ? f.scopes.filter((s) => s !== scope) : [...f.scopes, scope],
    }));
  }

  function toggleEvent(evt) {
    setWebhookForm((f) => ({
      ...f, subscribed_events: f.subscribed_events.includes(evt) ? f.subscribed_events.filter((e) => e !== evt) : [...f.subscribed_events, evt],
    }));
  }

  async function handleCreateKey(e) {
    e.preventDefault();
    try {
      const created = await createApiKey(token, keyForm);
      setRevealedKey({ name: created.name, raw_key: created.raw_key });
      setKeyForm({ name: "", scopes: [] });
      await loadKeys();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleRotate(keyId) {
    try {
      const rotated = await rotateApiKey(token, keyId);
      setRevealedKey({ name: rotated.name, raw_key: rotated.raw_key });
      await loadKeys();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleRevoke(keyId) {
    if (!window.confirm("Revoke this API key? Any integration using it will stop working immediately.")) return;
    try {
      await revokeApiKey(token, keyId);
      showToast("API key revoked.", "success");
      await loadKeys();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCreateWebhook(e) {
    e.preventDefault();
    try {
      await createWebhook(token, webhookForm);
      showToast("Webhook created.", "success");
      setWebhookForm({ url: "", subscribed_events: [] });
      await loadWebhooks();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleToggleWebhookActive(webhookId, isActive) {
    try {
      await updateWebhook(token, webhookId, { is_active: isActive });
      await loadWebhooks();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleDeleteWebhook(webhookId) {
    if (!window.confirm("Delete this webhook?")) return;
    try {
      await deleteWebhook(token, webhookId);
      showToast("Webhook deleted.", "success");
      setSelectedWebhookId(null);
      await loadWebhooks();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleReplay(deliveryId) {
    try {
      await replayWebhookDelivery(token, deliveryId);
      showToast("Replay attempted.", "success");
      await loadDeliveries(selectedWebhookId);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const selectedWebhook = webhooks.find((w) => w.id === selectedWebhookId);

  return (
    <div>
      <h2 className="page-title">Public API & Webhooks</h2>

      {revealedKey && (
        <div className="card" style={{ marginBottom: "20px", borderLeft: "3px solid var(--warning, #b45309)" }}>
          <strong>Copy this key now — it won't be shown again:</strong>
          <div className="mono" style={{ marginTop: "6px", wordBreak: "break-all", padding: "8px", background: "var(--code-bg, #f5f5f5)" }}>
            {revealedKey.raw_key}
          </div>
          <button className="btn-info-outline" style={{ marginTop: "8px" }} onClick={() => setRevealedKey(null)}>Dismiss</button>
        </div>
      )}

      {/* ---------- API Keys ---------- */}
      <h3>API Keys</h3>
      <form onSubmit={handleCreateKey} className="card" style={{ marginBottom: "12px" }}>
        <input className="input" placeholder="Key name" required style={{ marginBottom: "8px", width: "100%" }} value={keyForm.name} onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "8px" }}>
          {API_SCOPES.map((s) => (
            <label key={s} style={{ fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}>
              <input type="checkbox" checked={keyForm.scopes.includes(s)} onChange={() => toggleScope(s)} /> {s}
            </label>
          ))}
        </div>
        <button type="submit" className="btn btn-primary">Create Key</button>
      </form>

      <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "24px" }}>
        <table className="data-table">
          <thead><tr><th>Name</th><th>Prefix</th><th>Scopes</th><th>Status</th><th>Last Used</th><th></th></tr></thead>
          <tbody>
            {keys.length === 0 && <tr><td colSpan={6} style={{ color: "var(--text-muted)" }}>No API keys.</td></tr>}
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td className="mono">{k.key_prefix}...</td>
                <td style={{ fontSize: "12px" }}>{k.scopes}</td>
                <td>{k.is_active ? "Active" : "Revoked"}</td>
                <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "Never"}</td>
                <td>
                  {k.is_active && (
                    <div style={{ display: "flex", gap: "6px" }}>
                      <button className="btn-info-outline" onClick={() => handleRotate(k.id)}>Rotate</button>
                      <button className="btn-danger-outline" onClick={() => handleRevoke(k.id)}>Revoke</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ---------- Webhooks ---------- */}
      <h3>Webhooks</h3>
      <form onSubmit={handleCreateWebhook} className="card" style={{ marginBottom: "12px" }}>
        <input className="input" placeholder="https://your-server.com/webhook" required style={{ marginBottom: "8px", width: "100%" }} value={webhookForm.url} onChange={(e) => setWebhookForm({ ...webhookForm, url: e.target.value })} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "8px" }}>
          {WEBHOOK_EVENTS.map((evt) => (
            <label key={evt} style={{ fontSize: "12px", display: "flex", alignItems: "center", gap: "4px" }}>
              <input type="checkbox" checked={webhookForm.subscribed_events.includes(evt)} onChange={() => toggleEvent(evt)} /> {evt}
            </label>
          ))}
        </div>
        <button type="submit" className="btn btn-primary">Add Webhook</button>
      </form>

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "16px" }}>
        <div className="card" style={{ padding: 0, maxHeight: "420px", overflowY: "auto" }}>
          {webhooks.length === 0 && <div style={{ padding: "16px", color: "var(--text-muted)" }}>No webhooks.</div>}
          {webhooks.map((w) => (
            <div
              key={w.id}
              onClick={() => setSelectedWebhookId(w.id)}
              style={{
                padding: "12px", borderBottom: "1px solid var(--border-color, #eee)", cursor: "pointer",
                background: w.id === selectedWebhookId ? "var(--hover-bg, rgba(0,0,0,0.03))" : undefined,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: "13px", wordBreak: "break-all" }}>{w.url}</div>
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{w.is_active ? "Active" : "Inactive"} · {w.subscribed_events.split(",").length} events</div>
            </div>
          ))}
        </div>

        {selectedWebhook && (
          <div className="card">
            <div style={{ marginBottom: "10px" }}>
              <div className="mono" style={{ fontSize: "12px", wordBreak: "break-all" }}>Secret: {selectedWebhook.secret}</div>
              <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>Events: {selectedWebhook.subscribed_events}</div>
              <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                <button className="btn-info-outline" onClick={() => handleToggleWebhookActive(selectedWebhook.id, !selectedWebhook.is_active)}>
                  {selectedWebhook.is_active ? "Deactivate" : "Activate"}
                </button>
                <button className="btn-danger-outline" onClick={() => handleDeleteWebhook(selectedWebhook.id)}>Delete</button>
              </div>
            </div>

            <div style={{ borderTop: "1px solid var(--border-color, #eee)", paddingTop: "10px" }}>
              <strong style={{ fontSize: "13px" }}>Delivery Log</strong>
              <table className="data-table" style={{ marginTop: "8px" }}>
                <thead><tr><th>Event</th><th>Status</th><th>Attempts</th><th>Response</th><th></th></tr></thead>
                <tbody>
                  {deliveries.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>No deliveries yet.</td></tr>}
                  {deliveries.map((d) => (
                    <tr key={d.id}>
                      <td>{d.event_type}</td>
                      <td>{d.status}</td>
                      <td>{d.attempt_count}</td>
                      <td>{d.response_status_code || "—"}</td>
                      <td>
                        {d.status !== "success" && (
                          <button className="btn-info-outline" onClick={() => handleReplay(d.id)}>Replay</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
