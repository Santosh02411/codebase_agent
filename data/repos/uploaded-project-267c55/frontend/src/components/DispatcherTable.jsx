import React, { useEffect, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { connectWebSocket } from "../services/websocket";
import LocationPicker from "./LocationPicker";
import {
  fetchAllDeliveriesFromServer,
  fetchAgentsList,
  createDeliveryOnServer,
  exportDeliveriesCSV,
  fetchUnassignedDeliveries,
  assignAgentToDelivery,
  fetchSuggestedAgents,
  autoAssignDelivery,
  bulkUpdateDeliveryStatus,
  bulkAssignAgent,
  returnDeliveryToPool,
  updateDeliveryPriority,
  API_BASE_URL,
} from "../services/api";
import {
  setActiveDispatcher,
  cacheDispatcherDeliveries,
  getCachedDispatcherDeliveries,
  getDispatcherLastSyncedAt,
  queueDispatcherAction,
  getQueuedDispatcherActions,
} from "../services/dispatcherCache";
import { startDispatcherActionAutoSync } from "../services/dispatcherSyncEngine";
import { writeSyncContext } from "../services/backgroundSyncContext";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import DeliveryDetailModal from "./DeliveryDetailModal";
import StatusBadge from "./StatusBadge";
import Pagination from "./Pagination";
import BulkImportPanel from "./BulkImportPanel";

const STATUS_FILTER_OPTIONS = [
  { value: "all", label: "All Statuses" },
  { value: "pending", label: "Pending (Unassigned)" },
  { value: "picked_up", label: "Picked Up" },
  { value: "out_for_delivery", label: "Out for Delivery" },
  { value: "delivered", label: "Delivered" },
  { value: "failed_attempt", label: "Failed Attempt" },
  { value: "cancelled", label: "Cancelled" },
];

const SORT_OPTIONS = [
  { value: "updated_desc", label: "Most Recently Updated" },
  { value: "updated_asc", label: "Oldest Updated First" },
  { value: "order_id_asc", label: "Order ID (A-Z)" },
  { value: "status", label: "Status" },
  { value: "priority", label: "Priority" },
];

const PAGE_SIZE = 8;

/**
 * Dashboard for dispatchers/managers — summary stats, assign new
 * deliveries, and browse all deliveries with status/agent/date filters,
 * sorting, search, pagination, and a click-through detail modal.
 */
const PRIORITY_RANK = { urgent: 3, high: 2, normal: 1, low: 0 };

export default function DispatcherTable() {
  const { token, user } = useAuth();
  const { showToast } = useToast();
  const [deliveries, setDeliveries] = useState([]);
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);
  const [isOffline, setIsOffline] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState(null);

  const [statusFilter, setStatusFilter] = useState("all");
  const [agentFilter, setAgentFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortOption, setSortOption] = useState("updated_desc");
  const [currentPage, setCurrentPage] = useState(1);

  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [newOrderId, setNewOrderId] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newZone, setNewZone] = useState("");
  const [newExpectedBy, setNewExpectedBy] = useState("");
  const [newCustomerEmail, setNewCustomerEmail] = useState("");
  const [newCustomerPhone, setNewCustomerPhone] = useState("");
  const [showCoordFields, setShowCoordFields] = useState(false);
  const [newLatitude, setNewLatitude] = useState("");
  const [newLongitude, setNewLongitude] = useState("");
  const [newPriority, setNewPriority] = useState("normal");
  const [isAssigning, setIsAssigning] = useState(false);

  const [selectedDelivery, setSelectedDelivery] = useState(null);
  const [pendingActionCount, setPendingActionCount] = useState(0);
  const [pendingActionMsg, setPendingActionMsg] = useState(null);

  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkStatusChoice, setBulkStatusChoice] = useState("picked_up");
  const [bulkAgentChoice, setBulkAgentChoice] = useState("");
  const [isBulkActing, setIsBulkActing] = useState(false);
  const [reassigningId, setReassigningId] = useState(null);
  const [returningId, setReturningId] = useState(null);

  useEffect(() => {
    if (user?.id) {
      setActiveDispatcher(user.id);
      writeSyncContext({ userId: user.id, token, role: user.role, apiBaseUrl: API_BASE_URL });
    }
    loadDeliveries();
    loadAgents();
    refreshPendingActionCount();

    const stopDispatcherSync = startDispatcherActionAutoSync(token, (result) => {
      refreshPendingActionCount();
      if (result.syncedCount > 0) {
        setPendingActionMsg(`Synced ${result.syncedCount} queued action(s) from earlier.`);
        loadDeliveries();
      }
      if (result.failed.length > 0) {
        setPendingActionMsg(`${result.failed.length} queued action(s) couldn't be applied: ${result.failed[0].message}`);
      }
    });

    return () => stopDispatcherSync();
  }, []);

  async function refreshPendingActionCount() {
    const queued = await getQueuedDispatcherActions();
    setPendingActionCount(queued.length);
  }

  useEffect(() => {
    setCurrentPage(1);
  }, [statusFilter, agentFilter, dateFrom, dateTo, searchQuery]);

  async function loadDeliveries() {
    try {
      const records = await fetchAllDeliveriesFromServer(token);
      setDeliveries(records);
      setError(null);
      setIsOffline(false);
      await cacheDispatcherDeliveries(records);
    } catch (err) {
      // Fall back to the last-cached data instead of leaving the screen
      // blank — this is what makes the dispatcher view usable offline.
      try {
        const cached = await getCachedDispatcherDeliveries();
        const lastSynced = await getDispatcherLastSyncedAt();
        setDeliveries(cached);
        setIsOffline(true);
        setLastSyncedAt(lastSynced);
        setError(cached.length === 0 ? err.message : null);
      } catch (cacheErr) {
        setError(err.message);
      }
    }
  }

  async function loadAgents() {
    try {
      const agentList = await fetchAgentsList(token);
      setAgents(agentList);
      if (agentList.length > 0) setSelectedAgentId(agentList[0].id);
    } catch (err) {
      console.warn("Could not load agents list:", err.message);
    }
  }

  async function handleExportCSV() {
    try {
      await exportDeliveriesCSV(token, dateFrom, dateTo);
      showToast("CSV export downloaded.", "success");
    } catch (err) {
      showToast(`Export failed: ${err.message}`, "error");
    }
  }

  function toggleSelected(id) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllVisible() {
    setSelectedIds((prev) => {
      const allVisibleSelected = visibleDeliveries.every((d) => prev.has(d.id));
      const next = new Set(prev);
      if (allVisibleSelected) {
        visibleDeliveries.forEach((d) => next.delete(d.id));
      } else {
        visibleDeliveries.forEach((d) => next.add(d.id));
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function handlePriorityChange(deliveryId, newPriority) {
    // Optimistic update so the row re-sorts/re-labels immediately
    // rather than waiting on the round-trip.
    setDeliveries((prev) => prev.map((d) => (d.id === deliveryId ? { ...d, priority: newPriority } : d)));
    try {
      await updateDeliveryPriority(token, deliveryId, newPriority);
    } catch (err) {
      showToast(`Couldn't update priority: ${err.message}`, "error");
      loadDeliveries(); // revert to server truth on failure
    }
  }

  function summarizeBulkResult(result, actionLabel) {
    if (result.failure_count === 0) {
      showToast(`${actionLabel}: ${result.success_count} updated.`, "success");
    } else {
      showToast(
        `${actionLabel}: ${result.success_count} updated, ${result.failure_count} failed.`,
        result.success_count > 0 ? "success" : "error"
      );
    }
  }

  async function handleBulkStatusApply() {
    if (selectedIds.size === 0) return;
    setIsBulkActing(true);
    try {
      const result = await bulkUpdateDeliveryStatus(token, Array.from(selectedIds), bulkStatusChoice);
      summarizeBulkResult(result, "Bulk status update");
      clearSelection();
      await loadDeliveries();
    } catch (err) {
      showToast(`Bulk status update failed: ${err.message}`, "error");
    } finally {
      setIsBulkActing(false);
    }
  }

  async function handleRowReassign(deliveryId, agentId) {
    if (!agentId) return;
    setReassigningId(deliveryId);
    try {
      const result = await bulkAssignAgent(token, [deliveryId], agentId);
      if (result.failure_count > 0) {
        showToast(result.results[0]?.error || "Reassign failed.", "error");
      } else {
        showToast("Agent reassigned.", "success");
      }
      await loadDeliveries();
    } catch (err) {
      showToast(`Reassign failed: ${err.message}`, "error");
    } finally {
      setReassigningId(null);
    }
  }

  async function handleReturnToPool(deliveryId) {
    setReturningId(deliveryId);
    try {
      await returnDeliveryToPool(token, deliveryId);
      showToast("Order returned to the unassigned pool.", "success");
      await loadDeliveries();
    } catch (err) {
      showToast(`Couldn't return to pool: ${err.message}`, "error");
    } finally {
      setReturningId(null);
    }
  }

  async function handleBulkReassign() {
    if (selectedIds.size === 0 || !bulkAgentChoice) return;
    setIsBulkActing(true);
    try {
      const result = await bulkAssignAgent(token, Array.from(selectedIds), bulkAgentChoice);
      summarizeBulkResult(result, "Bulk reassign");
      clearSelection();
      await loadDeliveries();
    } catch (err) {
      showToast(`Bulk reassign failed: ${err.message}`, "error");
    } finally {
      setIsBulkActing(false);
    }
  }

  async function handleAssignDelivery(e) {
    e.preventDefault();

    if (!selectedAgentId || !newOrderId.trim()) {
      showToast("Pick an agent and enter an order ID.", "error");
      return;
    }

    // If either coordinate is filled, both must be filled and must be valid numbers —
    // a half-entered coordinate pair would silently break route optimization later
    const latTrimmed = newLatitude.trim();
    const lonTrimmed = newLongitude.trim();
    if ((latTrimmed || lonTrimmed) && (!latTrimmed || !lonTrimmed)) {
      showToast("Enter both latitude and longitude, or leave both blank.", "error");
      return;
    }
    if (latTrimmed && (isNaN(parseFloat(latTrimmed)) || isNaN(parseFloat(lonTrimmed)))) {
      showToast("Latitude and longitude must be numbers.", "error");
      return;
    }

    setIsAssigning(true);
    const now = new Date().toISOString();
    const record = {
      id: uuidv4(),
      agent_id: selectedAgentId,
      order_id: newOrderId.trim(),
      status: "picked_up",
      notes: newNotes.trim(),
      location_note: "",
      zone: newZone.trim() || null,
      customer_email: newCustomerEmail.trim() || null,
      customer_phone: newCustomerPhone.trim() || null,
      latitude: latTrimmed || null,
      longitude: lonTrimmed || null,
      expected_by: newExpectedBy ? new Date(newExpectedBy).toISOString() : null,
      priority: newPriority,
      created_at: now,
      updated_at: now,
    };
    try {
      await createDeliveryOnServer(token, record);
      showToast(`Assigned ${newOrderId} successfully.`, "success");
      setNewOrderId("");
      setNewNotes("");
      setNewZone("");
      setNewExpectedBy("");
      setNewPriority("normal");
      setNewCustomerEmail("");
      setNewCustomerPhone("");
      setNewLatitude("");
      setNewLongitude("");
      await loadDeliveries();
    } catch (err) {
      if (err instanceof TypeError) {
        // Offline — queue it instead of losing the entered data.
        // dispatcherSyncEngine.js creates it for real the moment
        // connectivity returns.
        await queueDispatcherAction("create_delivery", record);
        await refreshPendingActionCount();
        showToast(`You're offline — ${newOrderId} is queued and will be created once you're back online.`, "info");
        setNewOrderId("");
        setNewNotes("");
        setNewZone("");
        setNewExpectedBy("");
        setNewCustomerEmail("");
        setNewCustomerPhone("");
        setNewLatitude("");
        setNewLongitude("");
      } else {
        showToast(`Failed to assign: ${err.message}`, "error");
      }
    } finally {
      setIsAssigning(false);
    }
  }

  const agentNameById = new Map(agents.map((a) => [a.id, a.display_name]));

  const today = new Date().toDateString();
  const statCounts = { picked_up: 0, out_for_delivery: 0, delivered: 0, failed_attempt: 0 };
  let deliveredToday = 0;
  for (const d of deliveries) {
    if (statCounts[d.status] !== undefined) statCounts[d.status] += 1;
    if (d.status === "delivered" && new Date(d.updated_at).toDateString() === today) {
      deliveredToday += 1;
    }
  }

  let filteredDeliveries = deliveries.filter((d) => {
    const matchesStatus = statusFilter === "all" || d.status === statusFilter;
    const matchesAgent = agentFilter === "all" || d.agent_id === agentFilter;

    const updatedDate = new Date(d.updated_at);
    const matchesFrom = !dateFrom || updatedDate >= new Date(dateFrom);
    const matchesTo = !dateTo || updatedDate <= new Date(dateTo + "T23:59:59");

    const agentName = agentNameById.get(d.agent_id) || d.agent_id;
    const query = searchQuery.toLowerCase();
    const matchesSearch =
      query === "" ||
      d.order_id.toLowerCase().includes(query) ||
      agentName.toLowerCase().includes(query);

    return matchesStatus && matchesAgent && matchesFrom && matchesTo && matchesSearch;
  });

  filteredDeliveries = [...filteredDeliveries].sort((a, b) => {
    switch (sortOption) {
      case "updated_asc":
        return new Date(a.updated_at) - new Date(b.updated_at);
      case "order_id_asc":
        return a.order_id.localeCompare(b.order_id);
      case "status":
        return a.status.localeCompare(b.status);
      case "priority":
        return (PRIORITY_RANK[b.priority] ?? 1) - (PRIORITY_RANK[a.priority] ?? 1) || new Date(a.created_at) - new Date(b.created_at);
      case "updated_desc":
      default:
        return new Date(b.updated_at) - new Date(a.updated_at);
    }
  });

  const totalPages = Math.max(1, Math.ceil(filteredDeliveries.length / PAGE_SIZE));
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const visibleDeliveries = filteredDeliveries.slice(pageStart, pageStart + PAGE_SIZE);

  function clearFilters() {
    setStatusFilter("all");
    setAgentFilter("all");
    setDateFrom("");
    setDateTo("");
    setSearchQuery("");
  }

  return (
    <div>
      <h2 className="page-title">Dispatcher Dashboard</h2>

      {isOffline && (
        <div className="connectivity-banner offline" style={{ marginBottom: "16px" }}>
          Offline — showing data from last sync{lastSyncedAt ? ` at ${new Date(lastSyncedAt).toLocaleString()}` : ""}
        </div>
      )}

      {pendingActionCount > 0 && (
        <div className="connectivity-banner offline" style={{ marginBottom: "16px" }}>
          {pendingActionCount} action(s) queued while offline — will sync automatically once you're back online.
        </div>
      )}

      {pendingActionMsg && (
        <p style={{ fontSize: "12.5px", color: "var(--accent)", marginBottom: "12px" }}>
          {pendingActionMsg}
        </p>
      )}

      <UnassignedOrdersPanel token={token} agents={agents} onAssigned={loadDeliveries} onActionQueued={refreshPendingActionCount} />

      <div style={{ display: "flex", gap: "12px", marginBottom: "24px", flexWrap: "wrap" }}>
        <div className="stat-card">
          <div className="stat-card-value">{statCounts.picked_up}</div>
          <div className="stat-card-label">Picked Up</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{statCounts.out_for_delivery}</div>
          <div className="stat-card-label">Out for Delivery</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{statCounts.delivered}</div>
          <div className="stat-card-label">Delivered</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{statCounts.failed_attempt}</div>
          <div className="stat-card-label">Failed Attempts</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{deliveredToday}</div>
          <div className="stat-card-label">Delivered Today</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "24px" }}>
        <h3 style={{ marginBottom: "12px" }}>Assign a New Delivery</h3>
        {agents.length === 0 && (
          <p style={{ color: "var(--text-secondary)" }}>
            No agents registered yet. Have an agent sign up first.
          </p>
        )}
        {agents.length > 0 && (
          <form onSubmit={handleAssignDelivery} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "flex-end" }}>
              <div>
                <label className="field-label">Agent</label>
                <select className="input" value={selectedAgentId} onChange={(e) => setSelectedAgentId(e.target.value)}>
                  {agents.map((agent) => (
                    <option key={agent.id} value={agent.id}>{agent.display_name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label">Order ID</label>
                <input className="input" type="text" value={newOrderId} onChange={(e) => setNewOrderId(e.target.value)} placeholder="order-123" />
              </div>
              <div>
                <label className="field-label">Zone (optional)</label>
                <input className="input" type="text" value={newZone} onChange={(e) => setNewZone(e.target.value)} placeholder="e.g. North" />
              </div>
              <div>
                <label className="field-label">Expected By (optional)</label>
                <input className="input" type="datetime-local" value={newExpectedBy} onChange={(e) => setNewExpectedBy(e.target.value)} />
              </div>
              <div>
                <label className="field-label">Priority</label>
                <select className="input" value={newPriority} onChange={(e) => setNewPriority(e.target.value)}>
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="urgent">Urgent</option>
                </select>
              </div>
              <div style={{ flexGrow: 1, minWidth: "150px" }}>
                <label className="field-label">Notes (optional)</label>
                <input className="input" type="text" value={newNotes} onChange={(e) => setNewNotes(e.target.value)} placeholder="Fragile, deliver before 5pm..." style={{ width: "100%" }} />
              </div>
              <div>
                <label className="field-label">Customer Email (optional)</label>
                <input className="input" type="email" value={newCustomerEmail} onChange={(e) => setNewCustomerEmail(e.target.value)} placeholder="customer@example.com" />
              </div>
              <div>
                <label className="field-label">Customer Phone (optional)</label>
                <input className="input" type="text" value={newCustomerPhone} onChange={(e) => setNewCustomerPhone(e.target.value)} placeholder="+15551234567" />
              </div>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowCoordFields(!showCoordFields)}
                style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: "12.5px", padding: 0 }}
              >
                {showCoordFields ? "− Hide" : "+ Add"} coordinates (enables route optimization for the agent)
              </button>
            </div>

            {showCoordFields && (
              <div>
                <LocationPicker
                  latitude={newLatitude ? parseFloat(newLatitude) : null}
                  longitude={newLongitude ? parseFloat(newLongitude) : null}
                  onChange={(lat, lng) => {
                    setNewLatitude(lat.toFixed(6));
                    setNewLongitude(lng.toFixed(6));
                  }}
                  height={200}
                />
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "6px" }}>
                  <div>
                    <label className="field-label">Latitude</label>
                    <input className="input" type="text" value={newLatitude} onChange={(e) => setNewLatitude(e.target.value)} placeholder="12.9716" />
                  </div>
                  <div>
                    <label className="field-label">Longitude</label>
                    <input className="input" type="text" value={newLongitude} onChange={(e) => setNewLongitude(e.target.value)} placeholder="77.5946" />
                  </div>
                </div>
              </div>
            )}

            <div>
              <button type="submit" className="btn btn-primary" disabled={isAssigning}>
                {isAssigning ? "Assigning..." : "Assign"}
              </button>
            </div>
          </form>
        )}
      </div>

      <BulkImportPanel onImportComplete={loadDeliveries} />

      <div className="card" style={{ marginBottom: "16px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
        <button className="btn" onClick={loadDeliveries}>Refresh</button>

        <div>
          <label className="field-label">Status</label>
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_FILTER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <div>
          <label className="field-label">Agent</label>
          <select className="input" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
            <option value="all">All Agents</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.display_name}</option>)}
          </select>
        </div>

        <div>
          <label className="field-label">From</label>
          <input className="input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>

        <div>
          <label className="field-label">To</label>
          <input className="input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>

        <div>
          <label className="field-label">Sort by</label>
          <select className="input" value={sortOption} onChange={(e) => setSortOption(e.target.value)}>
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <input
          className="input"
          type="text"
          placeholder="Search by order ID or agent name..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{ flexGrow: 1, minWidth: "200px" }}
        />

        <button className="btn" onClick={clearFilters}>Clear Filters</button>

        <button className="btn btn-primary" onClick={handleExportCSV}>
          Export CSV{(dateFrom || dateTo) ? " (filtered range)" : ""}
        </button>

        <span style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          {filteredDeliveries.length} of {deliveries.length}
        </span>
      </div>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {selectedIds.size > 0 && (
        <div
          className="card"
          style={{
            marginBottom: "12px",
            display: "flex",
            gap: "10px",
            alignItems: "center",
            flexWrap: "wrap",
            padding: "10px 14px",
          }}
        >
          <strong style={{ fontSize: "13px" }}>{selectedIds.size} selected</strong>

          <select
            className="input"
            style={{ maxWidth: "180px" }}
            value={bulkStatusChoice}
            onChange={(e) => setBulkStatusChoice(e.target.value)}
          >
            {STATUS_FILTER_OPTIONS.filter((o) => o.value !== "all").map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button className="btn" onClick={handleBulkStatusApply} disabled={isBulkActing}>
            {isBulkActing ? "Working..." : "Apply status"}
          </button>

          <select
            className="input"
            style={{ maxWidth: "180px" }}
            value={bulkAgentChoice}
            onChange={(e) => setBulkAgentChoice(e.target.value)}
          >
            <option value="">Reassign to...</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.display_name}</option>
            ))}
          </select>
          <button className="btn" onClick={handleBulkReassign} disabled={isBulkActing || !bulkAgentChoice}>
            {isBulkActing ? "Working..." : "Reassign"}
          </button>

          <button className="btn" onClick={clearSelection} style={{ marginLeft: "auto" }}>
            Clear selection
          </button>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: "36px" }}>
                <input
                  type="checkbox"
                  checked={visibleDeliveries.length > 0 && visibleDeliveries.every((d) => selectedIds.has(d.id))}
                  onChange={toggleSelectAllVisible}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Select all deliveries on this page"
                />
              </th>
              <th>Order ID</th>
              <th>Customer</th>
              <th>Agent</th>
              <th>Zone</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Expected By</th>
              <th>Last Updated</th>
              <th>Reassign</th>
            </tr>
          </thead>
          <tbody>
            {visibleDeliveries.map((d) => {
              const isOverdue =
                d.expected_by &&
                d.status !== "delivered" &&
                new Date(d.expected_by) < new Date();
              const canReassign = d.agent_id && !["delivered", "cancelled"].includes(d.status);
              const canReturnToPool = d.customer_id && d.agent_id && d.status === "picked_up";
              return (
                <tr key={d.id} onClick={() => setSelectedDelivery(d)} className="row-animate">
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(d.id)}
                      onChange={() => toggleSelected(d.id)}
                      aria-label={`Select delivery ${d.order_id}`}
                    />
                  </td>
                  <td className="mono">{d.order_id}</td>
                  <td style={{ fontSize: "12.5px" }}>
                    {d.customer_email || d.customer_phone
                      ? [d.customer_email, d.customer_phone].filter(Boolean).join(" · ")
                      : "—"}
                  </td>
                  <td>{agentNameById.get(d.agent_id) || d.agent_id}</td>
                  <td>{d.zone || "—"}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <select
                      className="input"
                      style={{
                        padding: "2px 6px",
                        fontSize: "12px",
                        color: d.priority === "urgent" ? "var(--danger)" : d.priority === "high" ? "var(--warning, #b45309)" : undefined,
                        fontWeight: (d.priority === "urgent" || d.priority === "high") ? 600 : 400,
                      }}
                      value={d.priority || "normal"}
                      onChange={(e) => handlePriorityChange(d.id, e.target.value)}
                    >
                      <option value="low">Low</option>
                      <option value="normal">Normal</option>
                      <option value="high">High</option>
                      <option value="urgent">Urgent</option>
                    </select>
                  </td>
                  <td><StatusBadge status={d.status} /></td>
                  <td style={{ color: isOverdue ? "var(--danger)" : undefined, fontWeight: isOverdue ? 600 : undefined }}>
                    {d.expected_by ? new Date(d.expected_by).toLocaleString() : "—"}
                    {isOverdue && " (Overdue)"}
                  </td>
                  <td>{new Date(d.updated_at).toLocaleString()}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {canReassign ? (
                      <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                        <select
                          className="input"
                          style={{ padding: "2px 6px", fontSize: "12px", maxWidth: "120px" }}
                          value=""
                          disabled={reassigningId === d.id}
                          onChange={(e) => handleRowReassign(d.id, e.target.value)}
                          title="Reassign this order to a different agent"
                        >
                          <option value="">{reassigningId === d.id ? "Working..." : "↻ Reassign..."}</option>
                          {agents.filter((a) => a.id !== d.agent_id).map((a) => (
                            <option key={a.id} value={a.id}>{a.display_name}</option>
                          ))}
                        </select>
                        {canReturnToPool && (
                          <button
                            className="btn btn-sm"
                            onClick={() => handleReturnToPool(d.id)}
                            disabled={returningId === d.id}
                            title="Unassign and return this order to the unassigned pool"
                          >
                            {returningId === d.id ? "..." : "↩ Return"}
                          </button>
                        )}
                      </div>
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {visibleDeliveries.length === 0 && (
        <p style={{ color: "var(--text-secondary)", marginTop: "12px" }}>
          No deliveries match this filter/search.
        </p>
      )}

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={setCurrentPage}
        totalItems={filteredDeliveries.length}
        pageSize={PAGE_SIZE}
      />

      {selectedDelivery && (
        <DeliveryDetailModal
          delivery={selectedDelivery}
          agentName={agentNameById.get(selectedDelivery.agent_id)}
          onClose={() => setSelectedDelivery(null)}
          agents={agents}
          isReassigning={reassigningId === selectedDelivery.id}
          isReturning={returningId === selectedDelivery.id}
          onReassign={async (deliveryId, agentId) => {
            await handleRowReassign(deliveryId, agentId);
            setSelectedDelivery((prev) => (prev && prev.id === deliveryId ? { ...prev, agent_id: agentId, status: "picked_up" } : prev));
          }}
          onReturnToPool={async (deliveryId) => {
            await handleReturnToPool(deliveryId);
            setSelectedDelivery(null);
          }}
        />
      )}
    </div>
  );
}

function UnassignedOrdersPanel({ token, agents, onAssigned, onActionQueued }) {
  const [orders, setOrders] = useState([]);
  const [assigningId, setAssigningId] = useState(null);
  const [autoAssigningId, setAutoAssigningId] = useState(null);
  const [selectedAgentByOrder, setSelectedAgentByOrder] = useState({});
  const [error, setError] = useState(null);
  const [queuedOrderIds, setQueuedOrderIds] = useState(new Set());
  const [suggestionsByOrder, setSuggestionsByOrder] = useState({});
  const [loadingSuggestionsFor, setLoadingSuggestionsFor] = useState(null);

  useEffect(() => {
    load();
    // Live-updated instead of polled: the dispatcher queue socket
    // (routes/websockets.py) pushes a "queue_changed" event whenever a
    // new checkout order lands, an order gets assigned, or a return/
    // exchange pickup is created — this just re-fetches on that signal
    // rather than re-fetching blindly every 15s regardless of whether
    // anything actually changed.
    const socket = connectWebSocket(`/ws/dispatcher/queue?token=${encodeURIComponent(token)}`, {
      onMessage: (data) => {
        if (data.event === "queue_changed") load();
      },
    });
    return () => socket.close();
  }, []);

  async function load() {
    try {
      const data = await fetchUnassignedDeliveries(token);
      setOrders(data);
    } catch (err) {
      console.warn("Could not load unassigned orders:", err.message);
    }
  }

  async function handleShowSuggestions(orderId) {
    setLoadingSuggestionsFor(orderId);
    setError(null);
    try {
      const result = await fetchSuggestedAgents(token, orderId);
      setSuggestionsByOrder((prev) => ({ ...prev, [orderId]: result }));
      // Pre-select the top suggestion so "Assign" is one click if they agree with it.
      if (result.suggestions.length > 0) {
        setSelectedAgentByOrder((prev) => ({ ...prev, [orderId]: result.suggestions[0].agent_id }));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingSuggestionsFor(null);
    }
  }

  async function handleAutoAssign(orderId) {
    setAutoAssigningId(orderId);
    setError(null);
    try {
      await autoAssignDelivery(token, orderId);
      await load();
      await onAssigned();
    } catch (err) {
      setError(err.message);
    } finally {
      setAutoAssigningId(null);
    }
  }

  async function handleAssign(orderId) {
    const agentId = selectedAgentByOrder[orderId];
    if (!agentId) {
      setError("Pick an agent first.");
      return;
    }
    setAssigningId(orderId);
    setError(null);
    try {
      await assignAgentToDelivery(token, orderId, agentId);
      await load();
      await onAssigned();
    } catch (err) {
      if (err instanceof TypeError) {
        // Offline — queue it instead of losing the dispatcher's choice.
        // dispatcherSyncEngine.js applies it for real once online.
        await queueDispatcherAction("assign_agent", { delivery_id: orderId, agent_id: agentId });
        if (onActionQueued) await onActionQueued();
        setQueuedOrderIds((prev) => new Set(prev).add(orderId));
        setError(null);
      } else {
        setError(err.message);
      }
    } finally {
      setAssigningId(null);
    }
  }

  const visibleOrders = orders.filter((o) => !queuedOrderIds.has(o.id));
  if (visibleOrders.length === 0) return null;

  return (
    <div className="card" style={{ marginBottom: "20px", borderColor: "var(--accent)" }}>
      <strong style={{ fontSize: "13.5px" }}>
        🛒 Unassigned Orders ({visibleOrders.length})
      </strong>
      <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px", marginBottom: "12px" }}>
        Placed and paid for via the storefront — assign an agent to start fulfillment.
      </p>
      {error && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</p>}
      <div style={{ display: "grid", gap: "10px" }}>
        {visibleOrders.map((order) => {
          const suggestionData = suggestionsByOrder[order.id];
          const suggestionMap = suggestionData
            ? new Map(suggestionData.suggestions.map((s) => [s.agent_id, s]))
            : null;
          return (
            <div
              key={order.id}
              style={{
                padding: "8px 0",
                borderBottom: "1px solid var(--border-color)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "8px",
                }}
              >
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 600 }}>{order.order_id}</div>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{order.notes}</div>
                  {order.zone && (
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>🗺 Zone: {order.zone}</div>
                  )}
                  {order.location_note && (
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>📍 {order.location_note}</div>
                  )}
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                    {[order.customer_email, order.customer_phone].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                  {!suggestionData && (
                    <button
                      className="btn"
                      style={{ fontSize: "12px", padding: "4px 8px" }}
                      onClick={() => handleShowSuggestions(order.id)}
                      disabled={loadingSuggestionsFor === order.id}
                      title="Rank agents by zone match, live GPS distance, and current workload"
                    >
                      {loadingSuggestionsFor === order.id ? "Ranking..." : "🎯 Suggest agent"}
                    </button>
                  )}
                  <select
                    className="input"
                    style={{ fontSize: "12px", padding: "4px 8px" }}
                    value={selectedAgentByOrder[order.id] || ""}
                    onChange={(e) =>
                      setSelectedAgentByOrder({ ...selectedAgentByOrder, [order.id]: e.target.value })
                    }
                  >
                    <option value="">Select agent...</option>
                    {agents.map((a) => {
                      const s = suggestionMap?.get(a.id);
                      const coverTag = s?.covers_matched_zone ? "\u2b21 zone coverer — " : s?.zone_match ? "\u2713 zone match — " : "";
                      const areaTag = a.area_name ? ` (${a.area_name})` : "";
                      const label = s
                        ? `${coverTag}${a.display_name}${areaTag}${s.distance_km !== null ? ` — ${s.distance_km} km away` : " — no location"}, ${s.active_delivery_count} active`
                        : `${a.display_name}${areaTag}`;
                      return (
                        <option key={a.id} value={a.id}>{label}</option>
                      );
                    })}
                  </select>
                  <button
                    className="btn btn-primary"
                    style={{ fontSize: "12px", padding: "4px 10px" }}
                    onClick={() => handleAssign(order.id)}
                    disabled={assigningId === order.id}
                  >
                    {assigningId === order.id ? "Assigning..." : "Assign"}
                  </button>
                  <button
                    className="btn"
                    style={{ fontSize: "12px", padding: "4px 10px", borderColor: "var(--accent)", color: "var(--accent)" }}
                    onClick={() => handleAutoAssign(order.id)}
                    disabled={autoAssigningId === order.id}
                    title="Skip the pick — assign the best-ranked agent automatically"
                  >
                    {autoAssigningId === order.id ? "Assigning..." : "⚡ Auto-assign"}
                  </button>
                </div>
              </div>
              {suggestionData && !suggestionData.ranked_by_distance && (
                <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
                  This order has no delivery coordinates — ranked by current workload only.
                </p>
              )}
              {suggestionData && suggestionData.matched_zone_name && (
                <p style={{ fontSize: "11px", color: suggestionData.zone_restricted ? "var(--accent)" : "var(--text-muted)", marginTop: "4px" }}>
                  {suggestionData.zone_restricted
                    ? `\u2b21 Inside zone "${suggestionData.matched_zone_name}" — Auto-assign will restrict to that zone's covering agents.`
                    : `\u2b21 Inside zone "${suggestionData.matched_zone_name}", but no agents cover it yet — auto-assign will fall back to org-wide ranking.`}
                </p>
              )}
              {suggestionData && suggestionData.used_real_routing && (
                <p style={{ fontSize: "11px", color: "var(--accent)", marginTop: "4px" }}>
                  ⬡ Top candidates ranked using real road distance, not straight-line.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
