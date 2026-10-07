import React, { useState } from "react";
import { buildSuggestedRoute } from "../services/routeOptimizer";
import { optimizeRouteOnServer } from "../services/api";
import StatusBadge from "./StatusBadge";

/**
 * Shows the agent's active (not-delivered) deliveries, ordered for an
 * efficient run. Tries REAL route optimization first — a backend call
 * (services/routing.py, an actual TSP-approximation via OSRM/Google,
 * not hand-rolled nearest-neighbor) using real road distances. If that
 * doesn't succeed (no coordinates on enough deliveries, or no routing
 * provider reachable), falls back to the original client-side
 * nearest-neighbor-by-zone heuristic (services/routeOptimizer.js) —
 * every agent always gets SOME ordering, real routing or not.
 *
 * Uses the browser's geolocation API (with the agent's permission) as
 * the starting point either way. If permission is denied or
 * geolocation isn't available, falls back to (0, 0) as a starting
 * point for the client-side heuristic — the ordering is still
 * internally consistent, just not anchored to the agent's real
 * position. This is disclosed in the UI rather than silently guessing.
 */
export default function SuggestedRoute({ deliveries, token }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [startPoint, setStartPoint] = useState(null);
  const [locationStatus, setLocationStatus] = useState("idle"); // idle | requesting | granted | denied | unavailable
  const [serverOrder, setServerOrder] = useState(null); // ordered delivery ids from real routing, or null if not yet tried/unavailable
  const [isOptimizing, setIsOptimizing] = useState(false);

  const activeDeliveries = deliveries.filter(
    (d) => d.status === "picked_up" || d.status === "out_for_delivery"
  );

  function requestLocation() {
    if (!navigator.geolocation) {
      setLocationStatus("unavailable");
      tryServerOptimization(null);
      return;
    }

    setLocationStatus("requesting");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const point = { lat: position.coords.latitude, lon: position.coords.longitude };
        setStartPoint(point);
        setLocationStatus("granted");
        tryServerOptimization(point);
      },
      () => {
        setLocationStatus("denied");
        setStartPoint({ lat: 0, lon: 0 });
        tryServerOptimization(null);
      },
      { timeout: 8000 }
    );
  }

  async function tryServerOptimization(point) {
    if (!token) return;
    setIsOptimizing(true);
    try {
      const result = await optimizeRouteOnServer(
        token,
        activeDeliveries.map((d) => d.id),
        point ? point.lat : undefined,
        point ? point.lon : undefined
      );
      setServerOrder(result.used_real_routing ? result.ordered_delivery_ids : null);
    } catch (err) {
      setServerOrder(null); // network hiccup, etc. — client-side fallback below covers it
    } finally {
      setIsOptimizing(false);
    }
  }

  function handleToggleExpand() {
    if (!isExpanded && !startPoint) {
      requestLocation();
    }
    setIsExpanded(!isExpanded);
  }

  if (activeDeliveries.length === 0) {
    return null; // nothing active to route — don't show an empty widget
  }

  const orderedByServer = serverOrder
    ? serverOrder.map((id) => activeDeliveries.find((d) => d.id === id)).filter(Boolean)
    : null;
  const route = !orderedByServer && startPoint ? buildSuggestedRoute(activeDeliveries, startPoint) : [];
  const anyHasCoords = activeDeliveries.some((d) => d.latitude && d.longitude);

  return (
    <div className="card" style={{ marginBottom: "20px" }}>
      <div
        onClick={handleToggleExpand}
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
      >
        <h3 style={{ margin: 0 }}>Suggested Route ({activeDeliveries.length} active)</h3>
        <span style={{ color: "var(--accent)", fontSize: "13px" }}>
          {isExpanded ? "Hide" : "Show"}
        </span>
      </div>

      {isExpanded && (
        <div style={{ marginTop: "14px" }}>
          {locationStatus === "requesting" && (
            <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
              Requesting your location to order nearby deliveries first...
            </p>
          )}

          {isOptimizing && (
            <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
              Calculating the best route...
            </p>
          )}

          {locationStatus === "denied" && (
            <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>
              Location permission wasn't granted, so the route below isn't anchored
              to your current position.
            </p>
          )}

          {locationStatus === "unavailable" && (
            <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>
              Location isn't available on this device/browser, so the route below
              isn't anchored to your current position.
            </p>
          )}

          {!anyHasCoords && (
            <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>
              None of your active deliveries have coordinates yet, so they're
              shown in the order they were assigned. Ask your
              dispatcher to add coordinates for a precisely-ordered route.
            </p>
          )}

          {orderedByServer && (
            <>
              <div style={{ fontSize: "11px", color: "var(--accent)", fontWeight: 600, marginBottom: "8px" }}>
                ⬡ Optimized using real road distance
              </div>
              {orderedByServer.map((d, index) => (
                <div
                  key={d.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "8px 10px",
                    borderRadius: "var(--radius-sm)",
                    backgroundColor: "var(--bg-input)",
                    marginBottom: "6px",
                  }}
                >
                  <span>
                    <strong className="mono">{index + 1}.</strong>{" "}
                    <span className="mono">{d.order_id}</span>
                  </span>
                  <StatusBadge status={d.status} />
                </div>
              ))}
            </>
          )}

          {!orderedByServer && route.map((zoneGroup) => (
            <div key={zoneGroup.zone} style={{ marginTop: "14px" }}>
              <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: "6px" }}>
                {zoneGroup.zone}
              </div>
              {zoneGroup.deliveries.map((d, index) => (
                <div
                  key={d.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "8px 10px",
                    borderRadius: "var(--radius-sm)",
                    backgroundColor: "var(--bg-input)",
                    marginBottom: "6px",
                  }}
                >
                  <span>
                    <strong className="mono">{index + 1}.</strong>{" "}
                    <span className="mono">{d.order_id}</span>
                  </span>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    {d._distanceFromPreviousKm !== undefined && (
                      <span style={{ fontSize: "11.5px", color: "var(--text-muted)" }}>
                        {d._distanceFromPreviousKm.toFixed(1)} km
                      </span>
                    )}
                    <StatusBadge status={d.status} />
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
