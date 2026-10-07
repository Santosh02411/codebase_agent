import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import LocationPicker from "./LocationPicker";
import {
  fetchZones,
  createZone,
  updateZone,
  deleteZone,
  assignAgentToZone,
  unassignAgentFromZone,
  fetchAgentsList,
} from "../services/api";

/**
 * Admin management of delivery zones/territories — a real geographic
 * entity (a center point + radius, tested with real point-in-circle
 * math server-side), and which agents are assigned to cover each one.
 * See backend/app/models/zone.py for why a circle rather than a drawn
 * polygon.
 *
 * A delivery whose coordinates fall inside a zone gets auto-assign
 * RESTRICTED to that zone's covering agents (routes/deliveries.py) —
 * this page is where an admin sets that up.
 */
export default function ZoneManager() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [zones, setZones] = useState([]);
  const [agents, setAgents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [centerLat, setCenterLat] = useState("");
  const [centerLng, setCenterLng] = useState("");
  const [radiusKm, setRadiusKm] = useState("3");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setIsLoading(true);
    try {
      const [zonesData, agentsData] = await Promise.all([fetchZones(token), fetchAgentsList(token)]);
      setZones(zonesData);
      setAgents(agentsData);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!centerLat || !centerLng) {
      showToast("Click the map (or enter coordinates) to set the zone's center first.", "error");
      return;
    }
    setIsCreating(true);
    try {
      await createZone(token, {
        name: name.trim(),
        description: description.trim() || null,
        center_latitude: parseFloat(centerLat),
        center_longitude: parseFloat(centerLng),
        radius_km: parseFloat(radiusKm),
      });
      showToast("Zone created.", "success");
      setName("");
      setDescription("");
      setCenterLat("");
      setCenterLng("");
      setRadiusKm("3");
      setShowCreateForm(false);
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDelete(zoneId) {
    try {
      await deleteZone(token, zoneId);
      showToast("Zone deleted.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleToggleAgent(zone, agentId, isCovering) {
    try {
      if (isCovering) {
        await unassignAgentFromZone(token, zone.id, agentId);
      } else {
        await assignAgentToZone(token, zone.id, agentId);
      }
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function useMyLocationForCenter() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCenterLat(pos.coords.latitude.toFixed(6));
        setCenterLng(pos.coords.longitude.toFixed(6));
      },
      () => showToast("Couldn't get your current location.", "error")
    );
  }

  if (isLoading) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ margin: 0 }}>Delivery Zones</h2>
        <button className="btn btn-primary" onClick={() => setShowCreateForm(!showCreateForm)}>
          {showCreateForm ? "Cancel" : "+ New Zone"}
        </button>
      </div>
      <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "16px" }}>
        A zone is a real circular territory (center point + radius). A delivery whose address falls
        inside a zone will auto-assign ONLY to agents you've assigned to cover it here.
      </p>

      {showCreateForm && (
        <form onSubmit={handleCreate} className="card" style={{ marginBottom: "20px", maxWidth: "480px" }}>
          <div className="auth-field">
            <label htmlFor="zone-name">Zone name</label>
            <input id="zone-name" className="input" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label htmlFor="zone-description">Description (optional)</label>
            <input id="zone-description" className="input" type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>

          <div className="auth-field">
            <label htmlFor="zone-radius">Radius (km)</label>
            <input id="zone-radius" className="input" type="number" step="any" min="0.1" value={radiusKm} onChange={(e) => setRadiusKm(e.target.value)} required />
          </div>

          <div className="auth-field">
            {/* Not a <label htmlFor>: LocationPicker is a map, not a
                single focusable form control, so a for/id pairing here
                would be an orphaned reference rather than a real fix.
                The exact-coordinate inputs it's paired with below
                (Latitude/Longitude) ARE properly labeled. */}
            <label>Center point</label>
            <LocationPicker
              latitude={centerLat ? parseFloat(centerLat) : null}
              longitude={centerLng ? parseFloat(centerLng) : null}
              radiusKm={radiusKm ? parseFloat(radiusKm) : null}
              onChange={(lat, lng) => {
                setCenterLat(lat.toFixed(6));
                setCenterLng(lng.toFixed(6));
              }}
            />
            <button type="button" className="btn" style={{ marginTop: "8px", fontSize: "12px" }} onClick={useMyLocationForCenter}>
              📍 Use my current location
            </button>
          </div>

          <details style={{ marginBottom: "12px" }}>
            <summary style={{ fontSize: "12px", color: "var(--text-secondary)", cursor: "pointer" }}>
              Enter exact coordinates instead
            </summary>
            <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
              <div className="auth-field" style={{ flex: 1, marginBottom: 0 }}>
                <label htmlFor="zone-latitude">Latitude</label>
                <input id="zone-latitude" className="input" type="number" step="any" value={centerLat} onChange={(e) => setCenterLat(e.target.value)} />
              </div>
              <div className="auth-field" style={{ flex: 1, marginBottom: 0 }}>
                <label htmlFor="zone-longitude">Longitude</label>
                <input id="zone-longitude" className="input" type="number" step="any" value={centerLng} onChange={(e) => setCenterLng(e.target.value)} />
              </div>
            </div>
          </details>

          <button type="submit" className="btn btn-primary" disabled={isCreating || !centerLat || !centerLng}>
            {isCreating ? "Creating..." : "Create Zone"}
          </button>
        </form>
      )}

      {zones.length === 0 && !showCreateForm && (
        <p style={{ color: "var(--text-secondary)" }}>No zones defined yet. Deliveries fall back to org-wide assignment ranking until you create one.</p>
      )}

      <div style={{ display: "grid", gap: "12px" }}>
        {zones.map((zone) => (
          <div key={zone.id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <strong style={{ fontSize: "14px" }}>{zone.name}</strong>
                {zone.description && (
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{zone.description}</div>
                )}
                <div style={{ fontSize: "11.5px", color: "var(--text-muted)", marginTop: "2px" }}>
                  Center: {zone.center_latitude.toFixed(4)}, {zone.center_longitude.toFixed(4)} &middot; Radius: {zone.radius_km} km
                </div>
              </div>
              <button className="btn-danger-outline" onClick={() => handleDelete(zone.id)}>
                Delete
              </button>
            </div>

            <div style={{ marginTop: "12px" }}>
              <div style={{ fontSize: "12.5px", fontWeight: 600, marginBottom: "6px" }}>Covering agents</div>
              {agents.length === 0 && <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No agents in this org yet.</p>}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {agents.map((agent) => {
                  const isCovering = zone.covering_agent_ids.includes(agent.id);
                  return (
                    <button
                      key={agent.id}
                      className="btn"
                      style={{
                        fontSize: "12px",
                        padding: "4px 10px",
                        background: isCovering ? "var(--accent)" : undefined,
                        color: isCovering ? "white" : undefined,
                      }}
                      onClick={() => handleToggleAgent(zone, agent.id, isCovering)}
                    >
                      {isCovering ? "✓ " : ""}{agent.display_name}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
