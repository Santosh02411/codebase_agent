import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { fetchAnalytics } from "../services/api";

const STATUS_LABELS = {
  pending: "Pending Assignment",
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  failed_attempt: "Failed Attempt",
  cancelled: "Cancelled",
};

const STATUS_COLORS = {
  pending: "#94a3b8",
  picked_up: "#60a5fa",
  out_for_delivery: "#f59e0b",
  delivered: "#22c55e",
  failed_attempt: "#ef4444",
  cancelled: "#a3a3a3",
};

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

function RevenueBarChart({ data }) {
  const max = Math.max(...data.map((d) => d.revenue), 1);
  const labelEvery = data.length > 31 ? Math.ceil(data.length / 20) : Math.max(1, Math.floor(data.length / 10));

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: "2px", height: "160px", padding: "8px 0", overflowX: "auto" }}>
      {data.map((d, i) => (
        <div key={d.date} title={`${d.date}: ${formatMoney(d.revenue)} (${d.order_count} order${d.order_count === 1 ? "" : "s"})`} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: "1 0 auto", minWidth: "6px" }}>
          <div
            style={{
              width: "100%",
              minWidth: "4px",
              height: `${Math.max((d.revenue / max) * 130, d.revenue > 0 ? 3 : 1)}px`,
              background: d.revenue > 0 ? "var(--accent)" : "var(--border-color)",
              borderRadius: "2px 2px 0 0",
            }}
          />
          {i % labelEvery === 0 && (
            <div style={{ fontSize: "9px", color: "var(--text-muted)", marginTop: "4px", whiteSpace: "nowrap" }}>
              {d.date.slice(5)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function StatusBreakdownBar({ breakdown }) {
  const total = Object.values(breakdown).reduce((sum, n) => sum + n, 0);
  if (total === 0) {
    return <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No deliveries yet.</p>;
  }
  return (
    <div>
      <div style={{ display: "flex", height: "20px", borderRadius: "4px", overflow: "hidden" }}>
        {Object.entries(breakdown).map(([status, count]) =>
          count > 0 ? (
            <div
              key={status}
              title={`${STATUS_LABELS[status]}: ${count}`}
              style={{ width: `${(count / total) * 100}%`, background: STATUS_COLORS[status] }}
            />
          ) : null
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginTop: "10px" }}>
        {Object.entries(breakdown).map(([status, count]) => (
          <div key={status} style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "11.5px" }}>
            <span style={{ width: "9px", height: "9px", borderRadius: "2px", background: STATUS_COLORS[status], display: "inline-block" }} />
            {STATUS_LABELS[status]}: <strong>{count}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AnalyticsDashboard() {
  const { token } = useAuth();
  const [days, setDays] = useState(30);
  const [analytics, setAnalytics] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    load();
  }, [days]);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      setAnalytics(await fetchAnalytics(token, days));
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  if (isLoading && !analytics) return <p style={{ padding: "20px" }}>Loading analytics...</p>;
  if (error) return <p style={{ padding: "20px", color: "var(--danger)" }}>{error}</p>;
  if (!analytics) return null;

  return (
    <div style={{ padding: "0 4px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "10px" }}>
        <h2 style={{ margin: 0, fontSize: "18px" }}>Analytics</h2>
        <div style={{ display: "flex", gap: "6px" }}>
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              className="btn"
              style={{ fontSize: "12px", fontWeight: days === d ? 700 : 400, background: days === d ? "var(--accent)" : undefined, color: days === d ? "white" : undefined }}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="Revenue" value={formatMoney(analytics.total_revenue)} sub={`${analytics.total_orders} order${analytics.total_orders === 1 ? "" : "s"}`} />
        <StatCard label="Avg. Order Value" value={formatMoney(analytics.average_order_value)} />
        <StatCard label="Delivery Fees" value={formatMoney(analytics.total_delivery_fees_collected)} />
        <StatCard label="Tax (GST) Collected" value={formatMoney(analytics.total_tax_collected)} />
        <StatCard label="Discounts Given" value={formatMoney(analytics.total_discount_given)} />
        <StatCard
          label="Refunded"
          value={formatMoney(analytics.total_refunded)}
          sub={analytics.refunded_order_count > 0 ? `${analytics.refunded_order_count} order${analytics.refunded_order_count === 1 ? "" : "s"}` : null}
        />
      </div>

      <div className="card" style={{ marginBottom: "16px" }}>
        <strong style={{ fontSize: "13.5px" }}>Revenue — last {days} days</strong>
        <RevenueBarChart data={analytics.revenue_by_day} />
      </div>

      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        <div className="card" style={{ flex: "1 1 320px" }}>
          <strong style={{ fontSize: "13.5px" }}>Delivery Status Breakdown</strong>
          <div style={{ marginTop: "10px" }}>
            <StatusBreakdownBar breakdown={analytics.delivery_status_breakdown} />
          </div>
        </div>

        <div className="card" style={{ flex: "1 1 320px" }}>
          <strong style={{ fontSize: "13.5px" }}>Top Products by Revenue</strong>
          <div style={{ marginTop: "10px" }}>
            {analytics.top_products.length === 0 ? (
              <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No sales in this period yet.</p>
            ) : (
              analytics.top_products.map((p, i) => (
                <div key={p.product_id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: i < analytics.top_products.length - 1 ? "1px solid var(--border-color)" : "none", fontSize: "13px" }}>
                  <span>{i + 1}. {p.product_name} <span style={{ color: "var(--text-secondary)", fontSize: "11.5px" }}>× {p.quantity_sold}</span></span>
                  <strong>{formatMoney(p.revenue)}</strong>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {analytics.low_stock_products.length > 0 && (
        <div className="card" style={{ marginTop: "16px", borderColor: "var(--danger)" }}>
          <strong style={{ fontSize: "13.5px", color: "var(--danger)" }}>Low Stock Alerts</strong>
          <div style={{ marginTop: "10px" }}>
            {analytics.low_stock_products.map((p) => (
              <div key={p.id} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                <span>{p.name}</span>
                <strong style={{ color: p.stock_quantity === 0 ? "var(--danger)" : undefined }}>
                  {p.stock_quantity === 0 ? "Out of stock" : `${p.stock_quantity} left`}
                </strong>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
