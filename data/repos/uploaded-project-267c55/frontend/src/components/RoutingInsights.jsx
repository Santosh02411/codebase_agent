import React, { useEffect, useState } from "react";
import { fetchDeliveryHeatmap, optimizeMultiAgentRoutes } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

/**
 * Org-level routing view (Phase 9) — a simple heatmap point list (a
 * full map render would need the Leaflet setup already used elsewhere
 * in this app; kept as a lightweight table here since the underlying
 * data is the real feature) plus a manual multi-agent route
 * optimization trigger.
 */
export default function RoutingInsights() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [heatmap, setHeatmap] = useState([]);
  const [agentStartsJson, setAgentStartsJson] = useState('{\n  "AGENT_ID": {"latitude": 12.9, "longitude": 77.6}\n}');
  const [routes, setRoutes] = useState(null);
  const [isOptimizing, setIsOptimizing] = useState(false);

  useEffect(() => {
    fetchDeliveryHeatmap(token).then(setHeatmap).catch((err) => showToast(err.message, "error"));
  }, []);

  async function handleOptimize(e) {
    e.preventDefault();
    let parsed;
    try {
      parsed = JSON.parse(agentStartsJson);
    } catch {
      showToast("Agent starts must be valid JSON.", "error");
      return;
    }
    setIsOptimizing(true);
    try {
      setRoutes(await optimizeMultiAgentRoutes(token, parsed));
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsOptimizing(false);
    }
  }

  return (
    <div>
      <h2 className="page-title">Routing Insights</h2>

      <h3 style={{ marginBottom: "10px" }}>Delivery Heatmap</h3>
      <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "24px", maxHeight: "280px", overflowY: "auto" }}>
        <table className="data-table">
          <thead><tr><th>Latitude</th><th>Longitude</th><th>Ping Count</th></tr></thead>
          <tbody>
            {heatmap.length === 0 && <tr><td colSpan={3} style={{ color: "var(--text-muted)" }}>No location history yet.</td></tr>}
            {[...heatmap].sort((a, b) => b.count - a.count).map((p, i) => (
              <tr key={i}><td>{p.latitude}</td><td>{p.longitude}</td><td>{p.count}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ marginBottom: "10px" }}>Multi-Agent Route Optimization</h3>
      <form onSubmit={handleOptimize} className="card" style={{ marginBottom: "16px" }}>
        <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Agent starting positions (JSON)</label>
        <textarea className="input" rows={5} value={agentStartsJson} onChange={(e) => setAgentStartsJson(e.target.value)} style={{ fontFamily: "monospace", fontSize: "12px" }} />
        <button type="submit" className="btn btn-primary" style={{ marginTop: "8px" }} disabled={isOptimizing}>
          {isOptimizing ? "Optimizing..." : "Optimize Routes"}
        </button>
      </form>

      {routes && (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data-table">
            <thead><tr><th>Agent</th><th>Stop Order</th></tr></thead>
            <tbody>
              {Object.entries(routes).map(([agentId, stopIds]) => (
                <tr key={agentId}>
                  <td className="mono">{agentId.slice(0, 8)}</td>
                  <td>{stopIds.length === 0 ? "No stops" : stopIds.map((id) => id.slice(0, 8)).join(" -> ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
