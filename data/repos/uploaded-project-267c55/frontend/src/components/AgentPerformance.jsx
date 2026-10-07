import React, { useEffect, useState } from "react";
import { getAllLocalDeliveries } from "../services/indexedDb";

function startOfWeek(date) {
  const d = new Date(date);
  const day = d.getDay(); // 0 = Sunday
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Shows the logged-in agent their own performance: how many deliveries
 * they've completed today and this week, plus a breakdown of their
 * current workload. Computed from the same local IndexedDB data the
 * "My Deliveries" view uses — this is the agent's own device-local view
 * of their work, not a separate server round-trip.
 */
export default function AgentPerformance() {
  const [deliveries, setDeliveries] = useState([]);

  useEffect(() => {
    loadDeliveries();
  }, []);

  async function loadDeliveries() {
    const records = await getAllLocalDeliveries();
    setDeliveries(records);
  }

  const today = new Date().toDateString();
  const weekStart = startOfWeek(new Date());

  let completedToday = 0;
  let completedThisWeek = 0;
  let failedAttempts = 0;
  let inProgress = 0;

  for (const d of deliveries) {
    const updated = new Date(d.updated_at);
    if (d.status === "delivered") {
      if (updated.toDateString() === today) completedToday += 1;
      if (updated >= weekStart) completedThisWeek += 1;
    }
    if (d.status === "failed_attempt") failedAttempts += 1;
    if (d.status === "picked_up" || d.status === "out_for_delivery") inProgress += 1;
  }

  const totalAssigned = deliveries.length;
  const completionRate =
    totalAssigned > 0
      ? Math.round((deliveries.filter((d) => d.status === "delivered").length / totalAssigned) * 100)
      : 0;

  return (
    <div>
      <h2 className="page-title">Performance</h2>

      <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "24px" }}>
        <div className="stat-card">
          <div className="stat-card-value">{completedToday}</div>
          <div className="stat-card-label">Completed Today</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{completedThisWeek}</div>
          <div className="stat-card-label">Completed This Week</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{inProgress}</div>
          <div className="stat-card-label">In Progress</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{failedAttempts}</div>
          <div className="stat-card-label">Failed Attempts</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{completionRate}%</div>
          <div className="stat-card-label">Completion Rate</div>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: "12px" }}>About These Numbers</h3>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px", lineHeight: 1.6 }}>
          These stats are calculated from deliveries stored on this device
          ({totalAssigned} total assigned). "This week" starts on Sunday.
          Completion rate is delivered ÷ total assigned, across everything
          currently on this device — including any not yet synced.
        </p>
      </div>
    </div>
  );
}
