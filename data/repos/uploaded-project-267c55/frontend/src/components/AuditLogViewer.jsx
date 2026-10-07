import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { fetchAuditLog, fetchActionLog, fetchOrganizationUsers } from "../services/api";

const PAGE_SIZE = 50;

/**
 * Admin-facing audit log, split into two tabs:
 *  - "Delivery Status Changes": every status change made to a delivery
 *    in the org — who made it and when (unchanged from before).
 *  - "Admin Actions": everything ELSE an admin might need to trace —
 *    user management (deactivate/reactivate/reset password), product
 *    create/update/delete, coupon create/update/delete, and store
 *    settings changes (visibility/pricing/slots/profile). Backed by
 *    the new ActionLogDB / GET /admin/action-log.
 */
export default function AuditLogViewer() {
  const [activeTab, setActiveTab] = useState("deliveries");

  return (
    <div>
      <h2 className="page-title">Audit Log</h2>

      <div style={{ display: "flex", gap: "8px", marginBottom: "16px", borderBottom: "1px solid var(--border-color)" }}>
        <button
          className="btn"
          style={{
            borderRadius: "6px 6px 0 0",
            borderBottom: activeTab === "deliveries" ? "2px solid var(--accent-color, #4f8cff)" : "2px solid transparent",
            fontWeight: activeTab === "deliveries" ? 600 : 400,
          }}
          onClick={() => setActiveTab("deliveries")}
        >
          Delivery Status Changes
        </button>
        <button
          className="btn"
          style={{
            borderRadius: "6px 6px 0 0",
            borderBottom: activeTab === "actions" ? "2px solid var(--accent-color, #4f8cff)" : "2px solid transparent",
            fontWeight: activeTab === "actions" ? 600 : 400,
          }}
          onClick={() => setActiveTab("actions")}
        >
          Admin Actions
        </button>
      </div>

      {activeTab === "deliveries" ? <DeliveryStatusAuditLog /> : <AdminActionLog />}
    </div>
  );
}

function DeliveryStatusAuditLog() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [entries, setEntries] = useState([]);
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [changedByUserId, setChangedByUserId] = useState("");
  const [orderIdFilter, setOrderIdFilter] = useState("");

  useEffect(() => {
    fetchOrganizationUsers(token).then(setUsers).catch(() => {});
  }, [token]);

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, changedByUserId, orderIdFilter]);

  async function load(newOffset) {
    setIsLoading(true);
    try {
      const data = await fetchAuditLog(token, {
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        changedByUserId: changedByUserId || undefined,
        orderId: orderIdFilter || undefined,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      setEntries((prev) => (newOffset === 0 ? data : [...prev, ...data]));
      setHasMore(data.length === PAGE_SIZE);
      setOffset(newOffset);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  function handleLoadMore() {
    load(offset + PAGE_SIZE);
  }

  function clearFilters() {
    setDateFrom("");
    setDateTo("");
    setChangedByUserId("");
    setOrderIdFilter("");
  }

  const hasFilters = dateFrom || dateTo || changedByUserId || orderIdFilter;

  return (
    <div>
      <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "16px" }}>
        Every status change made to a delivery in your organization, in order — who made it and when.
      </p>

      <div className="card" style={{ marginBottom: "16px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-date-from">From</label>
          <input id="audit-date-from" type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-date-to">To</label>
          <input id="audit-date-to" type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-changed-by">Changed by</label>
          <select id="audit-changed-by" className="input" value={changedByUserId} onChange={(e) => setChangedByUserId(e.target.value)}>
            <option value="">Anyone</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.display_name}</option>
            ))}
          </select>
        </div>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-order-id">Order ID contains</label>
          <input
            id="audit-order-id"
            type="text"
            className="input"
            value={orderIdFilter}
            onChange={(e) => setOrderIdFilter(e.target.value)}
            placeholder="e.g. ORD-1023"
          />
        </div>
        {hasFilters && (
          <button className="btn" onClick={clearFilters}>Clear filters</button>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Order</th>
              <th>Changed By</th>
              <th>From</th>
              <th>To</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td style={{ whiteSpace: "nowrap" }}>{new Date(e.changed_at).toLocaleString()}</td>
                <td className="mono">{e.delivery_order_id}</td>
                <td>{e.changed_by_display_name}</td>
                <td style={{ textTransform: "capitalize" }}>{e.old_status ? e.old_status.replace(/_/g, " ") : "—"}</td>
                <td style={{ textTransform: "capitalize" }}>{e.new_status.replace(/_/g, " ")}</td>
                <td style={{ color: "var(--text-secondary)" }}>{e.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!isLoading && entries.length === 0 && (
        <p style={{ color: "var(--text-secondary)", marginTop: "12px" }}>
          No audit entries match these filters yet.
        </p>
      )}

      {hasMore && (
        <button className="btn" style={{ marginTop: "12px" }} onClick={handleLoadMore} disabled={isLoading}>
          {isLoading ? "Loading..." : "Load more"}
        </button>
      )}
    </div>
  );
}

const ENTITY_TYPE_OPTIONS = [
  { value: "", label: "All types" },
  { value: "user", label: "User" },
  { value: "product", label: "Product" },
  { value: "coupon", label: "Coupon" },
  { value: "store_settings", label: "Store settings" },
];

function formatChanges(changesJson) {
  if (!changesJson) return null;
  try {
    const parsed = JSON.parse(changesJson);
    const parts = Object.entries(parsed).map(
      ([field, { from, to }]) => `${field}: ${from ?? "—"} → ${to ?? "—"}`
    );
    return parts.join(", ");
  } catch {
    return null;
  }
}

function AdminActionLog() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [entries, setEntries] = useState([]);
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const [entityType, setEntityType] = useState("");
  const [actorUserId, setActorUserId] = useState("");

  useEffect(() => {
    fetchOrganizationUsers(token).then(setUsers).catch(() => {});
  }, [token]);

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, actorUserId]);

  async function load(newOffset) {
    setIsLoading(true);
    try {
      const data = await fetchActionLog(token, {
        entityType: entityType || undefined,
        actorUserId: actorUserId || undefined,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      setEntries((prev) => (newOffset === 0 ? data : [...prev, ...data]));
      setHasMore(data.length === PAGE_SIZE);
      setOffset(newOffset);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  function handleLoadMore() {
    load(offset + PAGE_SIZE);
  }

  function clearFilters() {
    setEntityType("");
    setActorUserId("");
  }

  const hasFilters = entityType || actorUserId;

  return (
    <div>
      <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "16px" }}>
        Every other admin action in your organization — user management, product and coupon changes, and store settings — who made it and when.
      </p>

      <div className="card" style={{ marginBottom: "16px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-entity-type">Type</label>
          <select id="audit-entity-type" className="input" value={entityType} onChange={(e) => setEntityType(e.target.value)}>
            {ENTITY_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="auth-field" style={{ marginBottom: 0 }}>
          <label htmlFor="audit-actor">Done by</label>
          <select id="audit-actor" className="input" value={actorUserId} onChange={(e) => setActorUserId(e.target.value)}>
            <option value="">Anyone</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.display_name}</option>
            ))}
          </select>
        </div>
        {hasFilters && (
          <button className="btn" onClick={clearFilters}>Clear filters</button>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Type</th>
              <th>Item</th>
              <th>Done By</th>
              <th>What happened</th>
              <th>Changes</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td style={{ whiteSpace: "nowrap" }}>{new Date(e.created_at).toLocaleString()}</td>
                <td style={{ textTransform: "capitalize" }}>{e.entity_type.replace(/_/g, " ")}</td>
                <td>{e.entity_label || "—"}</td>
                <td>{e.actor_display_name}</td>
                <td>{e.summary}</td>
                <td style={{ color: "var(--text-secondary)", fontSize: "12px" }}>{formatChanges(e.changes) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!isLoading && entries.length === 0 && (
        <p style={{ color: "var(--text-secondary)", marginTop: "12px" }}>
          No admin actions match these filters yet.
        </p>
      )}

      {hasMore && (
        <button className="btn" style={{ marginTop: "12px" }} onClick={handleLoadMore} disabled={isLoading}>
          {isLoading ? "Loading..." : "Load more"}
        </button>
      )}
    </div>
  );
}
