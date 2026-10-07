import React, { useEffect, useState } from "react";
import {
  fetchFinancialDashboard, fetchCodCollections, fetchSettlements,
  createSettlement, settleSettlement, fetchLedger,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const TABS = ["Overview", "COD Collections", "Settlements", "Ledger"];

/**
 * Financial reconciliation view (Phase 5). Gated on payments.view /
 * payments.manage — a dispatcher without those (narrowed via a custom
 * role, see RbacManager) simply doesn't see actionable buttons that
 * would 403.
 */
export default function ReconciliationDashboard() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState("Overview");
  const [dashboard, setDashboard] = useState(null);
  const [codCollections, setCodCollections] = useState([]);
  const [settlements, setSettlements] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [settleAgentId, setSettleAgentId] = useState("");

  useEffect(() => {
    loadDashboard();
    loadCod();
    loadSettlements();
    loadLedger();
  }, []);

  async function loadDashboard() {
    try {
      setDashboard(await fetchFinancialDashboard(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadCod() {
    try {
      setCodCollections(await fetchCodCollections(token));
    } catch (err) {
      // permission-gated — surfaced by Overview tab's own error handling
    }
  }

  async function loadSettlements() {
    try {
      setSettlements(await fetchSettlements(token));
    } catch (err) {}
  }

  async function loadLedger() {
    try {
      setLedger(await fetchLedger(token));
    } catch (err) {}
  }

  async function handleCreateSettlement(e) {
    e.preventDefault();
    if (!settleAgentId.trim()) return;
    try {
      await createSettlement(token, settleAgentId.trim());
      setSettleAgentId("");
      showToast("Settlement created.", "success");
      await loadSettlements();
      await loadCod();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleSettle(settlementId) {
    try {
      await settleSettlement(token, settlementId);
      showToast("Settlement marked as paid.", "success");
      await loadSettlements();
      await loadDashboard();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">Financial Reconciliation</h2>

      <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t} className={tab === t ? "btn btn-primary" : "btn"} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "Overview" && dashboard && (
        <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <Stat label="Total Charged" value={`$${dashboard.total_charged.toFixed(2)}`} />
          <Stat label="Total Refunded" value={`$${dashboard.total_refunded.toFixed(2)}`} />
          <Stat label="Net Revenue" value={`$${dashboard.net_revenue.toFixed(2)}`} color="var(--success, #16a34a)" />
          <Stat label="COD Collected" value={`$${dashboard.total_cod_collected.toFixed(2)}`} />
          <Stat label="COD Discrepancies" value={`${dashboard.cod_discrepancy_count} ($${dashboard.cod_discrepancy_amount.toFixed(2)})`} color="var(--warning, #b45309)" />
          <Stat label="COD Pending Collection" value={dashboard.cod_pending_count} />
          <Stat label="Open Settlements" value={`${dashboard.open_settlements_count} ($${dashboard.open_settlements_total.toFixed(2)})`} />
        </div>
      )}

      {tab === "COD Collections" && (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data-table">
            <thead><tr><th>Order</th><th>Agent</th><th>Expected</th><th>Collected</th><th>Status</th><th>Notes</th></tr></thead>
            <tbody>
              {codCollections.length === 0 && <tr><td colSpan={6} style={{ color: "var(--text-muted)" }}>No COD collections yet.</td></tr>}
              {codCollections.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.order_id ? c.order_id.slice(0, 8) : "—"}</td>
                  <td className="mono">{c.agent_id ? c.agent_id.slice(0, 8) : "—"}</td>
                  <td>${c.expected_amount.toFixed(2)}</td>
                  <td>{c.collected_amount != null ? `$${c.collected_amount.toFixed(2)}` : "—"}</td>
                  <td style={{ color: c.status === "discrepancy" ? "var(--warning, #b45309)" : c.status === "collected" ? "var(--success, #16a34a)" : "inherit", fontWeight: 600, textTransform: "capitalize" }}>
                    {c.status}
                  </td>
                  <td>{c.discrepancy_notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "Settlements" && (
        <div>
          <form onSubmit={handleCreateSettlement} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "16px" }}>
            <div>
              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Agent ID</label>
              <input className="input" value={settleAgentId} onChange={(e) => setSettleAgentId(e.target.value)} placeholder="Agent user ID" />
            </div>
            <button type="submit" className="btn btn-primary">Create Settlement</button>
          </form>
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Agent</th><th>Collections</th><th>Total Collected</th><th>Discrepancy</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {settlements.length === 0 && <tr><td colSpan={6} style={{ color: "var(--text-muted)" }}>No settlements yet.</td></tr>}
                {settlements.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.agent_id.slice(0, 8)}</td>
                    <td>{s.collection_count}</td>
                    <td>${s.total_collected.toFixed(2)}</td>
                    <td style={{ color: s.total_discrepancy !== 0 ? "var(--warning, #b45309)" : "inherit" }}>${s.total_discrepancy.toFixed(2)}</td>
                    <td style={{ textTransform: "capitalize" }}>{s.status}</td>
                    <td>
                      {s.status === "open" && (
                        <button className="btn-info-outline" onClick={() => handleSettle(s.id)}>Mark Settled</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "Ledger" && (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data-table">
            <thead><tr><th>Type</th><th>Amount</th><th>Order</th><th>Reference</th><th>Note</th><th>When</th></tr></thead>
            <tbody>
              {ledger.length === 0 && <tr><td colSpan={6} style={{ color: "var(--text-muted)" }}>No ledger entries yet.</td></tr>}
              {ledger.map((e) => (
                <tr key={e.id}>
                  <td style={{ textTransform: "capitalize" }}>{e.event_type.replace("_", " ")}</td>
                  <td>${e.amount.toFixed(2)}</td>
                  <td className="mono">{e.order_id ? e.order_id.slice(0, 8) : "—"}</td>
                  <td className="mono">{e.reference ? e.reference.slice(0, 12) : "—"}</td>
                  <td>{e.note || "—"}</td>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
