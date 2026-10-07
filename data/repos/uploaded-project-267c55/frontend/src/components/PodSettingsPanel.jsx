import React, { useEffect, useState } from "react";
import { fetchPodSettings, updatePodSettings, exportPodReportCSV } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const FIELDS = [
  { key: "pod_require_recipient_name", label: "Require recipient name", help: "Agent must record who received the delivery." },
  { key: "pod_require_signature_or_photo", label: "Require signature or photo", help: "Agent must capture a signature or a photo of the delivery." },
  { key: "pod_require_otp", label: "Require recipient OTP verification", help: "Agent must send and confirm a one-time code with the recipient." },
  { key: "pod_require_gps", label: "Require GPS location", help: "Agent's device location must be captured at the moment of delivery." },
];

/**
 * Admin-only settings for what proof of delivery must include before a
 * delivery can be marked "Delivered" (Phase 1). All four toggles
 * default OFF — an org that never visits this page sees no change in
 * behavior. Also offers the downloadable POD CSV report.
 */
export default function PodSettingsPanel() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [settings, setSettings] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [isExporting, setIsExporting] = useState(false);

  useEffect(() => {
    fetchPodSettings(token).then(setSettings).catch((err) => showToast(err.message, "error"));
  }, []);

  async function handleToggle(key) {
    const updated = { ...settings, [key]: !settings[key] };
    setSettings(updated); // optimistic
    setIsSaving(true);
    try {
      const saved = await updatePodSettings(token, {
        pod_require_recipient_name: updated.pod_require_recipient_name,
        pod_require_signature_or_photo: updated.pod_require_signature_or_photo,
        pod_require_otp: updated.pod_require_otp,
        pod_require_gps: updated.pod_require_gps,
      });
      setSettings(saved);
    } catch (err) {
      showToast(err.message, "error");
      setSettings(settings); // revert
    } finally {
      setIsSaving(false);
    }
  }

  async function handleExport() {
    setIsExporting(true);
    try {
      const blob = await exportPodReportCSV(token, dateFrom || undefined, dateTo || undefined);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "proof_of_delivery_report.csv";
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsExporting(false);
    }
  }

  if (!settings) return null;

  return (
    <div>
      <h2 className="page-title">Proof of Delivery Settings</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: "13px", marginBottom: "16px" }}>
        Choose what agents must capture before a delivery can be marked "Delivered". Nothing is required by default.
      </p>

      <div className="card" style={{ marginBottom: "20px" }}>
        {FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", alignItems: "flex-start", gap: "10px", padding: "10px 0", borderBottom: "1px solid var(--border-color)", cursor: "pointer" }}>
            <input type="checkbox" checked={!!settings[f.key]} onChange={() => handleToggle(f.key)} disabled={isSaving} style={{ marginTop: "3px" }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: "14px" }}>{f.label}</div>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{f.help}</div>
            </div>
          </label>
        ))}
      </div>

      <h3 style={{ marginBottom: "10px" }}>Export POD Report</h3>
      <div className="card" style={{ display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap" }}>
        <div>
          <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>From</label>
          <input type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>To</label>
          <input type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={handleExport} disabled={isExporting}>
          {isExporting ? "Exporting..." : "Download CSV"}
        </button>
      </div>
    </div>
  );
}
