import React, { useEffect, useState } from "react";
import { fetchNotificationTemplates, updateNotificationTemplate, resetNotificationTemplate } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const EVENT_LABELS = {
  refund_processed: "Refund Processed",
  return_approved: "Return Approved",
  agent_nearby: "Agent Nearby",
  delivery_reminder: "Delivery Reminder",
  subscription_reminder: "Subscription Reminder",
};

/**
 * Notification template settings (Phase 10). Every event starts as a
 * built-in default (is_default: true) - editing and saving customizes
 * it for this org; "Reset to Default" removes the customization.
 */
export default function NotificationTemplateManager() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [templates, setTemplates] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [savingEvent, setSavingEvent] = useState(null);

  useEffect(() => {
    loadTemplates();
  }, []);

  async function loadTemplates() {
    try {
      const data = await fetchNotificationTemplates(token);
      setTemplates(data);
      const nextDrafts = {};
      data.forEach((t) => { nextDrafts[t.event_type] = { ...t }; });
      setDrafts(nextDrafts);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function updateDraft(eventType, field, value) {
    setDrafts((prev) => ({ ...prev, [eventType]: { ...prev[eventType], [field]: value } }));
  }

  async function handleSave(eventType) {
    setSavingEvent(eventType);
    try {
      const draft = drafts[eventType];
      await updateNotificationTemplate(token, eventType, {
        subject: draft.subject, body: draft.body,
        email_enabled: draft.email_enabled, sms_enabled: draft.sms_enabled, whatsapp_enabled: draft.whatsapp_enabled,
      });
      showToast("Template saved.", "success");
      await loadTemplates();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setSavingEvent(null);
    }
  }

  async function handleReset(eventType) {
    try {
      await resetNotificationTemplate(token, eventType);
      showToast("Reverted to default.", "success");
      await loadTemplates();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">Notification Templates</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: "13px", marginBottom: "16px" }}>
        Customize the wording customers see for these notifications, and which channels each one uses. Use <code>{"{order_id}"}</code> to insert the order number.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
        {templates.map((t) => {
          const draft = drafts[t.event_type] || t;
          return (
            <div key={t.event_type} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <h4 style={{ margin: 0 }}>{EVENT_LABELS[t.event_type] || t.event_type}</h4>
                {!t.is_default && (
                  <button className="btn-danger-outline" onClick={() => handleReset(t.event_type)}>Reset to Default</button>
                )}
                {t.is_default && <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Using default</span>}
              </div>

              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Subject (email)</label>
              <input className="input" value={draft.subject} onChange={(e) => updateDraft(t.event_type, "subject", e.target.value)} style={{ marginBottom: "8px" }} />

              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Message</label>
              <textarea className="input" rows={2} value={draft.body} onChange={(e) => updateDraft(t.event_type, "body", e.target.value)} style={{ marginBottom: "8px" }} />

              <div style={{ display: "flex", gap: "14px", marginBottom: "8px" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "12.5px" }}>
                  <input type="checkbox" checked={draft.email_enabled} onChange={(e) => updateDraft(t.event_type, "email_enabled", e.target.checked)} /> Email
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "12.5px" }}>
                  <input type="checkbox" checked={draft.sms_enabled} onChange={(e) => updateDraft(t.event_type, "sms_enabled", e.target.checked)} /> SMS
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "12.5px" }}>
                  <input type="checkbox" checked={draft.whatsapp_enabled} onChange={(e) => updateDraft(t.event_type, "whatsapp_enabled", e.target.checked)} /> WhatsApp
                </label>
              </div>

              <button className="btn btn-primary" onClick={() => handleSave(t.event_type)} disabled={savingEvent === t.event_type}>
                {savingEvent === t.event_type ? "Saving..." : "Save"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
