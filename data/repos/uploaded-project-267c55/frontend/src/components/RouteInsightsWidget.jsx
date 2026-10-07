import React, { useEffect, useState } from "react";
import { fetchDynamicEta, fetchRouteDeviation, fetchRouteEfficiency } from "../services/api";
import { useAuth } from "../context/AuthContext";

/**
 * Shown on a delivery's detail view (Phase 9) — renders nothing if
 * none of the three signals are available yet (no live agent
 * location, no destination coordinates, or not enough location
 * history), since that's the common case for a delivery that hasn't
 * gone out for delivery yet.
 */
export default function RouteInsightsWidget({ deliveryId }) {
  const { token } = useAuth();
  const [eta, setEta] = useState(null);
  const [deviation, setDeviation] = useState(null);
  const [efficiency, setEfficiency] = useState(null);

  useEffect(() => {
    fetchDynamicEta(token, deliveryId).then(setEta).catch(() => {});
    fetchRouteDeviation(token, deliveryId).then(setDeviation).catch(() => {});
    fetchRouteEfficiency(token, deliveryId).then(setEfficiency).catch(() => {});
  }, [deliveryId]);

  const hasAnything = eta || (deviation && deviation.deviated) || efficiency;
  if (!hasAnything) return null;

  return (
    <div style={{ padding: "10px", background: "var(--bg-secondary, #f8fafc)", borderRadius: "var(--radius-sm)", marginBottom: "10px" }}>
      <div style={{ fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>Live Routing</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "16px", fontSize: "12.5px" }}>
        {eta && (
          <div>
            <div style={{ color: "var(--text-secondary)" }}>ETA</div>
            <div>{eta.duration_min} min ({eta.distance_km} km)</div>
          </div>
        )}
        {efficiency && (
          <div>
            <div style={{ color: "var(--text-secondary)" }}>Distance Traveled</div>
            <div>{efficiency.distance_traveled_km} km {efficiency.efficiency_ratio != null && `(${Math.round(efficiency.efficiency_ratio * 100)}% efficient)`}</div>
          </div>
        )}
        {efficiency && (
          <div>
            <div style={{ color: "var(--text-secondary)" }}>Time in Transit</div>
            <div>{Math.round(efficiency.time_spent_minutes)} min</div>
          </div>
        )}
      </div>
      {deviation && deviation.deviated && (
        <div style={{ marginTop: "6px", color: "var(--warning, #b45309)", fontWeight: 600, fontSize: "12.5px" }}>
          Route deviation detected — agent is {deviation.current_distance_km} km from destination (closest approach was {deviation.closest_approach_km} km).
        </div>
      )}
    </div>
  );
}
