import React, { useEffect, useState } from "react";
import { fetchAdvancedAnalytics } from "../services/api";
import { useAuth } from "../context/AuthContext";

function formatMoney(n) {
  return `\u20B9${(n ?? 0).toFixed(2)}`;
}

function StatCard({ label, value, sub }) {
  return (
    <div className="card" style={{ flex: "1 1 160px", minWidth: "150px" }}>
      <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{label}</div>
      <div style={{ fontSize: "22px", fontWeight: 700, marginTop: "4px" }}>{value}</div>
      {sub && <div style={{ fontSize: "11.5px", color: "var(--text-muted)", marginTop: "2px" }}>{sub}</div>}
    </div>
  );
}

/** Advanced analytics (Phase 15): agent productivity, failures, returns/cancellations, retention, revenue breakdowns, margin, trend. Admin-only. */
export default function AdvancedAnalyticsPanel() {
  const { token } = useAuth();
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState(null);

  useEffect(() => { load(); }, [days]);

  async function load() {
    try {
      setData(await fetchAdvancedAnalytics(token, days));
    } catch (err) {
      setError(err.message);
    }
  }

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <div style={{ color: "var(--text-muted)" }}>Loading...</div>;

  const trend = data.trend_and_forecast;
  const margin = data.profit_margin;
  const retention = data.customer_retention;
  const failed = data.failed_delivery_analytics;
  const returns = data.return_and_cancellation_analytics;
  const revenue = data.revenue_breakdowns;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ margin: 0 }}>Advanced Analytics</h2>
        <select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="Revenue Trend" value={trend.change_percent != null ? `${trend.change_percent > 0 ? "+" : ""}${trend.change_percent}%` : "—"} sub="vs prior period" />
        <StatCard label="7-Day Forecast" value={formatMoney(trend.naive_7_day_forecast)} sub="naive projection" />
        <StatCard label="Repeat Order Rate" value={`${retention.repeat_order_rate_percent}%`} sub={`${retention.repeat_customers} of ${retention.unique_customers} customers`} />
        <StatCard label="Cancellation Rate" value={`${returns.cancellation_rate_percent}%`} sub={`${returns.total_cancelled} cancelled`} />
        <StatCard label="Failure Rate" value={`${failed.failure_rate_percent}%`} sub={`${failed.total_failed} failed`} />
        <StatCard
          label="Profit Margin"
          value={margin.margin_percent != null ? `${margin.margin_percent}%` : "—"}
          sub={margin.products_missing_cost_price > 0 ? `${margin.products_missing_cost_price} product(s) missing cost price` : formatMoney(margin.profit)}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <div className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Revenue by Category</strong>
          {Object.keys(revenue.by_category).length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No data yet.</div>}
          {Object.entries(revenue.by_category).map(([cat, amt]) => (
            <div key={cat} style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "4px 0" }}>
              <span>{cat}</span><span>{formatMoney(amt)}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Revenue by Payment Method</strong>
          {Object.keys(revenue.by_payment_method).length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No data yet.</div>}
          {Object.entries(revenue.by_payment_method).map(([method, amt]) => (
            <div key={method} style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "4px 0" }}>
              <span style={{ textTransform: "capitalize" }}>{method}</span><span>{formatMoney(amt)}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <div className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Failed Delivery Reasons</strong>
          {Object.keys(failed.by_reason).length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No failed deliveries.</div>}
          {Object.entries(failed.by_reason).map(([reason, count]) => (
            <div key={reason} style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "4px 0" }}>
              <span>{reason}</span><span>{count}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Return Requests</strong>
          {returns.total_return_requests === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No return requests.</div>}
          {Object.entries(returns.by_type).map(([type, count]) => (
            <div key={type} style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "4px 0" }}>
              <span style={{ textTransform: "capitalize" }}>{type}</span><span>{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <strong style={{ display: "block", padding: "12px" }}>Agent Productivity</strong>
        <table className="data-table">
          <thead><tr><th>Agent</th><th>Delivered</th><th>Failed</th><th>On-Time Rate</th></tr></thead>
          <tbody>
            {data.agent_productivity.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No agents yet.</td></tr>}
            {data.agent_productivity.map((a) => (
              <tr key={a.agent_id}>
                <td>{a.agent_name}</td>
                <td>{a.delivered_count}</td>
                <td>{a.failed_count}</td>
                <td>{a.on_time_rate != null ? `${a.on_time_rate}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
