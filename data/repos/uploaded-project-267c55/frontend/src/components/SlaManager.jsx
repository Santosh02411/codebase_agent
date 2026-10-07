import React, { useEffect, useState } from "react";
import {
  fetchSlaDashboard,
  fetchSlaAnalytics,
  fetchSlaPolicies,
  createSlaPolicy,
  updateSlaPolicy,
  deleteSlaPolicy,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import StatusBadge from "./StatusBadge";

const SLA_LABELS = { at_risk: "At Risk", breached: "Breached", met: "Met", missed: "Missed", on_track: "On Track" };
const SLA_COLORS = { at_risk: "var(--warning, #b45309)", breached: "var(--danger)", missed: "var(--danger)", met: "var(--success, #16a34a)", on_track: "var(--text-secondary)" };

const EMPTY_POLICY = { name: "", zone: "", delivery_type: "", priority: "", target_minutes: 60, warning_threshold_percent: 80 };

/**
 * SLA view (Phase 2). Dispatchers see the at-risk/breached worklist and
 * analytics; admins additionally get policy CRUD. One component (not
 * split per-role) since dispatchers and admins share the same top two
 * sections and the policy editor is simply hidden for dispatchers,
 * mirroring how AnalyticsDashboard/AdminPanel are already split by
 * what data each role's tokens are even allowed to fetch, not by
 * artificially duplicating markup.
 */
export default function SlaManager() {
  const { token, user } = useAuth();
  const { showToast } = useToast();
  const [dashboard, setDashboard] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [policies, setPolicies] = useState([]);
  const [error, setError] = useState(null);
  const [showPolicyForm, setShowPolicyForm] = useState(false);
  const [editingPolicyId, setEditingPolicyId] = useState(null);
  const [policyDraft, setPolicyDraft] = useState(EMPTY_POLICY);
  const [isSaving, setIsSaving] = useState(false);

  const isAdmin = user.role === "admin";

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    try {
      const [dash, stats] = await Promise.all([fetchSlaDashboard(token), fetchSlaAnalytics(token)]);
      setDashboard(dash);
      setAnalytics(stats);
      if (isAdmin) setPolicies(await fetchSlaPolicies(token));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  function openNewPolicyForm() {
    setPolicyDraft(EMPTY_POLICY);
    setEditingPolicyId(null);
    setShowPolicyForm(true);
  }

  function openEditPolicyForm(policy) {
    setPolicyDraft({
      name: policy.name,
      zone: policy.zone || "",
      delivery_type: policy.delivery_type || "",
      priority: policy.priority || "",
      target_minutes: policy.target_minutes,
      warning_threshold_percent: policy.warning_threshold_percent,
    });
    setEditingPolicyId(policy.id);
    setShowPolicyForm(true);
  }

  async function handleSavePolicy(e) {
    e.preventDefault();
    setIsSaving(true);
    try {
      const payload = {
        name: policyDraft.name.trim(),
        zone: policyDraft.zone.trim() || null,
        delivery_type: policyDraft.delivery_type.trim() || null,
        priority: policyDraft.priority.trim() || null,
        target_minutes: Number(policyDraft.target_minutes),
        warning_threshold_percent: Number(policyDraft.warning_threshold_percent),
      };
      if (editingPolicyId) {
        await updateSlaPolicy(token, editingPolicyId, payload);
        showToast("SLA policy updated.", "success");
      } else {
        await createSlaPolicy(token, payload);
        showToast("SLA policy created.", "success");
      }
      setShowPolicyForm(false);
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeletePolicy(policyId) {
    try {
      await deleteSlaPolicy(token, policyId);
      showToast("SLA policy deleted.", "success");
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleTogglePolicyActive(policy) {
    try {
      await updateSlaPolicy(token, policy.id, { active: !policy.active });
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">SLA Management</h2>
      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {analytics && (
        <div className="card" style={{ marginBottom: "20px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "24px" }}>
            <Stat label="SLA %" value={analytics.sla_percentage != null ? `${analytics.sla_percentage}%` : "—"} />
            <Stat label="Completed (tracked)" value={analytics.completed} />
            <Stat label="Met" value={analytics.met} color="var(--success, #16a34a)" />
            <Stat label="Missed" value={analytics.missed} color="var(--danger)" />
            <Stat label="Avg. Delivery Time" value={analytics.avg_delivery_minutes != null ? `${analytics.avg_delivery_minutes} min` : "—"} />
            <Stat label="Avg. Delay" value={`${analytics.avg_delay_minutes} min`} />
            <Stat label="Currently At Risk" value={analytics.currently_at_risk} color="var(--warning, #b45309)" />
            <Stat label="Currently Breached" value={analytics.currently_breached} color="var(--danger)" />
          </div>

          {analytics.by_agent.length > 0 && (
            <div style={{ marginTop: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>By Agent</h4>
              <BreakdownTable rows={analytics.by_agent} keyField="agent_id" />
            </div>
          )}
          {analytics.by_zone.length > 0 && (
            <div style={{ marginTop: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>By Zone</h4>
              <BreakdownTable rows={analytics.by_zone} keyField="zone" />
            </div>
          )}
        </div>
      )}

      <h3 style={{ marginBottom: "10px" }}>At Risk / Breached Now</h3>
      <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "24px" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Status</th>
              <th>SLA</th>
              <th>Deadline</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.length === 0 && (
              <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>Nothing currently at risk or breached.</td></tr>
            )}
            {dashboard.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.order_id}</td>
                <td><StatusBadge status={d.status} /></td>
                <td>
                  <span style={{ color: SLA_COLORS[d.sla_status], fontWeight: 600 }}>
                    {SLA_LABELS[d.sla_status] || d.sla_status}
                  </span>
                </td>
                <td>{d.sla_target_at ? new Date(d.sla_target_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <h3>SLA Policies</h3>
            <button className="btn btn-primary" onClick={openNewPolicyForm}>+ New Policy</button>
          </div>
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Zone</th>
                  <th>Type</th>
                  <th>Priority</th>
                  <th>Target</th>
                  <th>Warning At</th>
                  <th>Active</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {policies.length === 0 && (
                  <tr><td colSpan={8} style={{ color: "var(--text-muted)" }}>No SLA policies yet — deliveries won't get a deadline until you add one.</td></tr>
                )}
                {policies.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.zone || "Any"}</td>
                    <td>{p.delivery_type || "Any"}</td>
                    <td>{p.priority || "Any"}</td>
                    <td>{p.target_minutes} min</td>
                    <td>{p.warning_threshold_percent}%</td>
                    <td>{p.active ? "Yes" : "No"}</td>
                    <td>
                      <div style={{ display: "flex", gap: "6px" }}>
                        <button className="btn-info-outline" onClick={() => openEditPolicyForm(p)}>Edit</button>
                        <button className="btn-info-outline" onClick={() => handleTogglePolicyActive(p)}>{p.active ? "Deactivate" : "Activate"}</button>
                        <button className="btn-danger-outline" onClick={() => handleDeletePolicy(p.id)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {showPolicyForm && (
        <div className="modal-overlay" onClick={() => setShowPolicyForm(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
            <h3 style={{ marginBottom: "12px" }}>{editingPolicyId ? "Edit" : "New"} SLA Policy</h3>
            <form onSubmit={handleSavePolicy} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Name</label>
                <input className="input" required value={policyDraft.name} onChange={(e) => setPolicyDraft({ ...policyDraft, name: e.target.value })} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Zone (optional)</label>
                  <input className="input" value={policyDraft.zone} onChange={(e) => setPolicyDraft({ ...policyDraft, zone: e.target.value })} placeholder="Any" />
                </div>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Delivery Type (optional)</label>
                  <input className="input" value={policyDraft.delivery_type} onChange={(e) => setPolicyDraft({ ...policyDraft, delivery_type: e.target.value })} placeholder="Any" />
                </div>
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Priority (optional)</label>
                <select className="input" value={policyDraft.priority} onChange={(e) => setPolicyDraft({ ...policyDraft, priority: e.target.value })}>
                  <option value="">Any</option>
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="urgent">Urgent</option>
                </select>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Target (minutes)</label>
                  <input type="number" min={1} className="input" required value={policyDraft.target_minutes} onChange={(e) => setPolicyDraft({ ...policyDraft, target_minutes: e.target.value })} />
                </div>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Warning at (%)</label>
                  <input type="number" min={1} max={99} className="input" required value={policyDraft.warning_threshold_percent} onChange={(e) => setPolicyDraft({ ...policyDraft, warning_threshold_percent: e.target.value })} />
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
                <button type="submit" className="btn btn-primary" disabled={isSaving}>{isSaving ? "Saving..." : "Save"}</button>
                <button type="button" className="btn" onClick={() => setShowPolicyForm(false)}>Cancel</button>
              </div>
            </form>
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

function BreakdownTable({ rows, keyField }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>{keyField === "agent_id" ? "Agent" : "Zone"}</th>
          <th>Total</th>
          <th>Met</th>
          <th>Missed</th>
          <th>SLA %</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r[keyField]}>
            <td>{r[keyField]}</td>
            <td>{r.total}</td>
            <td>{r.met}</td>
            <td>{r.missed}</td>
            <td>{r.sla_percentage != null ? `${r.sla_percentage}%` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
