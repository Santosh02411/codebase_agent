import React, { useEffect, useState } from "react";
import {
  updateOrgBranding, updateOrgLocale, fetchOrgUsage, suspendOrg, reactivateOrg, exportOrgData,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

/** Enterprise organization management (Phase 16): admin-only. Branding, locale, usage, suspension, data export. */
export default function OrganizationSettings() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [usage, setUsage] = useState(null);
  const [org, setOrg] = useState(null);
  const [brandingForm, setBrandingForm] = useState({ logo_url: "", brand_color: "" });
  const [localeForm, setLocaleForm] = useState({ timezone: "", currency_code: "", currency_symbol: "" });
  const [suspendReason, setSuspendReason] = useState("");

  useEffect(() => { loadUsage(); }, []);

  async function loadUsage() {
    try {
      setUsage(await fetchOrgUsage(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleUpdateBranding(e) {
    e.preventDefault();
    try {
      const updated = await updateOrgBranding(token, {
        logo_url: brandingForm.logo_url || undefined, brand_color: brandingForm.brand_color || undefined,
      });
      setOrg(updated);
      showToast("Branding updated.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleUpdateLocale(e) {
    e.preventDefault();
    try {
      const updated = await updateOrgLocale(token, {
        timezone: localeForm.timezone || undefined,
        currency_code: localeForm.currency_code || undefined,
        currency_symbol: localeForm.currency_symbol || undefined,
      });
      setOrg(updated);
      showToast("Locale updated.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleSuspend(e) {
    e.preventDefault();
    if (!window.confirm("Suspend this organization? New signups and checkouts will be blocked until you reactivate.")) return;
    try {
      const updated = await suspendOrg(token, suspendReason);
      setOrg(updated);
      setSuspendReason("");
      showToast("Organization suspended.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleReactivate() {
    try {
      const updated = await reactivateOrg(token);
      setOrg(updated);
      showToast("Organization reactivated.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleExport() {
    try {
      const data = await exportOrgData(token);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `org-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const isSuspended = org ? org.is_suspended : false;

  return (
    <div>
      <h2 className="page-title">Organization</h2>

      {isSuspended && (
        <div className="card" style={{ marginBottom: "20px", borderLeft: "3px solid var(--danger, #b91c1c)" }}>
          <strong>This organization is suspended.</strong>
          <div style={{ fontSize: "13px", marginTop: "4px" }}>{org.suspended_reason}</div>
          <button className="btn btn-primary" style={{ marginTop: "8px" }} onClick={handleReactivate}>Reactivate</button>
        </div>
      )}

      {usage && (
        <div className="card" style={{ marginBottom: "20px", display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <div><strong>{usage.staff_count}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Staff</div></div>
          <div><strong>{usage.agent_count}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Agents</div></div>
          <div><strong>{usage.total_deliveries}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Deliveries</div></div>
          <div><strong>{usage.total_orders}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Orders</div></div>
          <div><strong>{usage.unique_customers}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Customers</div></div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <form onSubmit={handleUpdateBranding} className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Branding</strong>
          <input className="input" placeholder="Logo URL" style={{ marginBottom: "8px", width: "100%" }} value={brandingForm.logo_url} onChange={(e) => setBrandingForm({ ...brandingForm, logo_url: e.target.value })} />
          <input className="input" placeholder="Brand color (#2563eb)" style={{ marginBottom: "8px", width: "100%" }} value={brandingForm.brand_color} onChange={(e) => setBrandingForm({ ...brandingForm, brand_color: e.target.value })} />
          <button type="submit" className="btn btn-primary">Save</button>
        </form>

        <form onSubmit={handleUpdateLocale} className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Locale</strong>
          <input className="input" placeholder="Timezone (e.g. Asia/Kolkata)" style={{ marginBottom: "8px", width: "100%" }} value={localeForm.timezone} onChange={(e) => setLocaleForm({ ...localeForm, timezone: e.target.value })} />
          <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
            <input className="input" placeholder="Currency code (INR)" style={{ flex: 1 }} value={localeForm.currency_code} onChange={(e) => setLocaleForm({ ...localeForm, currency_code: e.target.value })} />
            <input className="input" placeholder="Symbol (₹)" style={{ width: "80px" }} value={localeForm.currency_symbol} onChange={(e) => setLocaleForm({ ...localeForm, currency_symbol: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-primary">Save</button>
        </form>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        {!isSuspended && (
          <form onSubmit={handleSuspend} className="card">
            <strong style={{ display: "block", marginBottom: "8px" }}>Pause Operations</strong>
            <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "8px" }}>
              Blocks new staff signups and new checkouts. Existing staff can still log in and manage things.
            </p>
            <input className="input" placeholder="Reason" required style={{ marginBottom: "8px", width: "100%" }} value={suspendReason} onChange={(e) => setSuspendReason(e.target.value)} />
            <button type="submit" className="btn-danger-outline">Suspend</button>
          </form>
        )}

        <div className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Data Export</strong>
          <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "8px" }}>
            Download organization settings, staff roster, and delivery/order summary as JSON.
          </p>
          <button className="btn-info-outline" onClick={handleExport}>Export</button>
        </div>
      </div>
    </div>
  );
}
