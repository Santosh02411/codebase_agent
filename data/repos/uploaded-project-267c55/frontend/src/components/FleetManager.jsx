import React, { useEffect, useState } from "react";
import {
  fetchVehicles, createVehicle, updateVehicle, deactivateVehicle, assignVehicle,
  recordVehicleInspection, addVehicleMaintenance, fetchVehicleMaintenance,
  addVehicleFuelRecord, fetchVehicleFuelRecords,
  fetchVehicleUtilization, fetchFleetReminders, fetchAgentsList,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const STATUS_LABELS = { available: "Available", in_use: "In Use", maintenance: "Maintenance", inactive: "Inactive" };

/**
 * Fleet management (Phase 11). Dispatchers/admins get the full manager
 * (vehicle CRUD, assignment, maintenance/fuel logging, reminders);
 * agents get a read-only view of their own assigned vehicle only —
 * routes/fleet.py already scopes GET /fleet/vehicles that way for the
 * agent role, so this component doesn't need to filter client-side.
 */
export default function FleetManager() {
  const { token, user } = useAuth();
  const { showToast } = useToast();
  const isManager = user.role === "dispatcher" || user.role === "admin";

  const [vehicles, setVehicles] = useState([]);
  const [agents, setAgents] = useState([]);
  const [reminders, setReminders] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [maintenance, setMaintenance] = useState([]);
  const [fuel, setFuel] = useState([]);
  const [utilization, setUtilization] = useState(null);

  const [newVehicle, setNewVehicle] = useState({ vehicle_type: "van", registration_number: "", capacity_units: "" });
  const [maintenanceForm, setMaintenanceForm] = useState({ maintenance_type: "", cost: "", next_due_date: "" });
  const [fuelForm, setFuelForm] = useState({ liters: "", cost: "", odometer_km: "" });

  useEffect(() => {
    loadVehicles();
    if (isManager) {
      loadAgents();
      loadReminders();
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      loadMaintenance(selectedId);
      loadFuel(selectedId);
      if (isManager) loadUtilization(selectedId);
    }
  }, [selectedId]);

  async function loadVehicles() {
    try {
      const data = await fetchVehicles(token);
      setVehicles(data);
      if (data.length > 0 && !selectedId) setSelectedId(data[0].id);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadAgents() {
    try {
      setAgents(await fetchAgentsList(token));
    } catch (err) {}
  }

  async function loadReminders() {
    try {
      setReminders(await fetchFleetReminders(token));
    } catch (err) {}
  }

  async function loadMaintenance(vehicleId) {
    try {
      setMaintenance(await fetchVehicleMaintenance(token, vehicleId));
    } catch (err) {}
  }

  async function loadFuel(vehicleId) {
    try {
      setFuel(await fetchVehicleFuelRecords(token, vehicleId));
    } catch (err) {}
  }

  async function loadUtilization(vehicleId) {
    try {
      setUtilization(await fetchVehicleUtilization(token, vehicleId));
    } catch (err) {}
  }

  async function handleCreateVehicle(e) {
    e.preventDefault();
    try {
      const payload = { ...newVehicle };
      if (payload.capacity_units === "") delete payload.capacity_units;
      else payload.capacity_units = parseInt(payload.capacity_units, 10);
      await createVehicle(token, payload);
      showToast("Vehicle added.", "success");
      setNewVehicle({ vehicle_type: "van", registration_number: "", capacity_units: "" });
      await loadVehicles();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleStatusChange(vehicleId, status) {
    try {
      await updateVehicle(token, vehicleId, { status });
      showToast("Vehicle status updated.", "success");
      await loadVehicles();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAssign(vehicleId, agentId) {
    try {
      await assignVehicle(token, vehicleId, agentId || null);
      showToast(agentId ? "Vehicle assigned." : "Vehicle unassigned.", "success");
      await loadVehicles();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleDeactivate(vehicleId) {
    if (!window.confirm("Deactivate this vehicle?")) return;
    try {
      await deactivateVehicle(token, vehicleId);
      showToast("Vehicle deactivated.", "success");
      setSelectedId(null);
      await loadVehicles();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAddMaintenance(e) {
    e.preventDefault();
    try {
      const payload = { ...maintenanceForm };
      if (payload.cost === "") delete payload.cost;
      else payload.cost = parseFloat(payload.cost);
      if (payload.next_due_date === "") delete payload.next_due_date;
      await addVehicleMaintenance(token, selectedId, payload);
      showToast("Maintenance record added.", "success");
      setMaintenanceForm({ maintenance_type: "", cost: "", next_due_date: "" });
      await loadMaintenance(selectedId);
      await loadVehicles();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAddFuel(e) {
    e.preventDefault();
    try {
      const payload = {
        liters: parseFloat(fuelForm.liters),
        cost: parseFloat(fuelForm.cost),
      };
      if (fuelForm.odometer_km !== "") payload.odometer_km = parseFloat(fuelForm.odometer_km);
      await addVehicleFuelRecord(token, selectedId, payload);
      showToast("Fuel record added.", "success");
      setFuelForm({ liters: "", cost: "", odometer_km: "" });
      await loadFuel(selectedId);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const selected = vehicles.find((v) => v.id === selectedId);

  return (
    <div>
      <h2 className="page-title">{isManager ? "Fleet" : "My Vehicle"}</h2>

      {isManager && reminders && (
        (reminders.insurance_due.length + reminders.registration_due.length + reminders.inspection_due.length + reminders.maintenance_due.length) > 0 && (
          <div className="card" style={{ marginBottom: "20px", borderLeft: "3px solid var(--warning, #b45309)" }}>
            <strong>Attention needed soon:</strong>
            <ul style={{ margin: "8px 0 0 18px" }}>
              {reminders.insurance_due.map((v) => <li key={`ins-${v.id}`}>{v.registration_number} — insurance expiring</li>)}
              {reminders.registration_due.map((v) => <li key={`reg-${v.id}`}>{v.registration_number} — registration expiring</li>)}
              {reminders.inspection_due.map((v) => <li key={`insp-${v.id}`}>{v.registration_number} — inspection due</li>)}
              {reminders.maintenance_due.map((m, i) => <li key={`maint-${i}`}>{m.maintenance_type} due</li>)}
            </ul>
          </div>
        )
      )}

      {isManager && (
        <form onSubmit={handleCreateVehicle} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "20px", flexWrap: "wrap" }}>
          <div>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Type</label>
            <select className="input" value={newVehicle.vehicle_type} onChange={(e) => setNewVehicle({ ...newVehicle, vehicle_type: e.target.value })}>
              <option value="bike">Bike</option>
              <option value="van">Van</option>
              <option value="truck">Truck</option>
              <option value="car">Car</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Registration Number</label>
            <input className="input" required value={newVehicle.registration_number} onChange={(e) => setNewVehicle({ ...newVehicle, registration_number: e.target.value })} />
          </div>
          <div>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Capacity (units)</label>
            <input type="number" min={1} className="input" style={{ width: "110px" }} value={newVehicle.capacity_units} onChange={(e) => setNewVehicle({ ...newVehicle, capacity_units: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-primary">Add Vehicle</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "20px" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Registration</th><th>Type</th><th>Status</th><th>Assigned Agent</th><th>Odometer</th>
              {isManager && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {vehicles.length === 0 && <tr><td colSpan={isManager ? 6 : 5} style={{ color: "var(--text-muted)" }}>No vehicles.</td></tr>}
            {vehicles.map((v) => {
              const agent = agents.find((a) => a.id === v.assigned_agent_id);
              return (
                <tr key={v.id} onClick={() => setSelectedId(v.id)} style={{ cursor: "pointer", background: v.id === selectedId ? "var(--hover-bg, rgba(0,0,0,0.03))" : undefined }}>
                  <td className="mono">{v.registration_number}</td>
                  <td>{v.vehicle_type}</td>
                  <td>
                    {isManager ? (
                      <select className="input" value={v.status} onClick={(e) => e.stopPropagation()} onChange={(e) => handleStatusChange(v.id, e.target.value)}>
                        {Object.keys(STATUS_LABELS).map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                      </select>
                    ) : STATUS_LABELS[v.status]}
                  </td>
                  <td>{agent ? agent.display_name : "Unassigned"}</td>
                  <td>{v.odometer_km} km</td>
                  {isManager && (
                    <td onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: "6px" }}>
                        <select className="input" value={v.assigned_agent_id || ""} onChange={(e) => handleAssign(v.id, e.target.value)}>
                          <option value="">Unassign</option>
                          {agents.map((a) => <option key={a.id} value={a.id}>{a.display_name}</option>)}
                        </select>
                        <button className="btn-danger-outline" onClick={() => handleDeactivate(v.id)}>Deactivate</button>
                      </div>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selected && (
        <div style={{ display: "grid", gridTemplateColumns: isManager ? "1fr 1fr" : "1fr", gap: "20px" }}>
          <div>
            <h4 style={{ marginBottom: "8px" }}>Maintenance — {selected.registration_number}</h4>
            {isManager && (
              <form onSubmit={handleAddMaintenance} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "12px", flexWrap: "wrap" }}>
                <input className="input" placeholder="Type (e.g. oil_change)" required value={maintenanceForm.maintenance_type} onChange={(e) => setMaintenanceForm({ ...maintenanceForm, maintenance_type: e.target.value })} />
                <input type="number" min={0} className="input" style={{ width: "100px" }} placeholder="Cost" value={maintenanceForm.cost} onChange={(e) => setMaintenanceForm({ ...maintenanceForm, cost: e.target.value })} />
                <input type="date" className="input" value={maintenanceForm.next_due_date} onChange={(e) => setMaintenanceForm({ ...maintenanceForm, next_due_date: e.target.value })} />
                <button type="submit" className="btn btn-primary">Log</button>
              </form>
            )}
            <div className="card" style={{ padding: 0, overflowX: "auto" }}>
              <table className="data-table">
                <thead><tr><th>Type</th><th>Cost</th><th>Date</th><th>Next Due</th></tr></thead>
                <tbody>
                  {maintenance.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No maintenance records.</td></tr>}
                  {maintenance.map((m) => (
                    <tr key={m.id}>
                      <td>{m.maintenance_type}</td>
                      <td>{m.cost != null ? `₹${m.cost}` : "—"}</td>
                      <td>{new Date(m.performed_at).toLocaleDateString()}</td>
                      <td>{m.next_due_date ? new Date(m.next_due_date).toLocaleDateString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h4 style={{ marginBottom: "8px" }}>Fuel — {selected.registration_number}</h4>
            <form onSubmit={handleAddFuel} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "12px", flexWrap: "wrap" }}>
              <input type="number" min={0.1} step="0.1" className="input" style={{ width: "90px" }} placeholder="Liters" required value={fuelForm.liters} onChange={(e) => setFuelForm({ ...fuelForm, liters: e.target.value })} />
              <input type="number" min={0} className="input" style={{ width: "100px" }} placeholder="Cost" required value={fuelForm.cost} onChange={(e) => setFuelForm({ ...fuelForm, cost: e.target.value })} />
              <input type="number" min={0} className="input" style={{ width: "110px" }} placeholder="Odometer" value={fuelForm.odometer_km} onChange={(e) => setFuelForm({ ...fuelForm, odometer_km: e.target.value })} />
              <button type="submit" className="btn btn-primary">Log</button>
            </form>
            <div className="card" style={{ padding: 0, overflowX: "auto" }}>
              <table className="data-table">
                <thead><tr><th>Liters</th><th>Cost</th><th>Odometer</th><th>Date</th></tr></thead>
                <tbody>
                  {fuel.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No fuel records.</td></tr>}
                  {fuel.map((f) => (
                    <tr key={f.id}>
                      <td>{f.liters} L</td>
                      <td>₹{f.cost}</td>
                      <td>{f.odometer_km != null ? `${f.odometer_km} km` : "—"}</td>
                      <td>{new Date(f.recorded_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {isManager && utilization && (
              <div className="card" style={{ marginTop: "12px" }}>
                <strong>Utilization (30 days):</strong> {utilization.deliveries_completed} deliveries completed
                {utilization.note && <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>{utilization.note}</div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
