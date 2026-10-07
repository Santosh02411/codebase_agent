import React, { useEffect, useState } from "react";
import {
  saveDeliveryLocally,
  getAllLocalDeliveries,
  deleteDeliveryLocally,
  mergeAssignedDeliveries,
  setActiveUser,
  queueLocationPing,
} from "../services/indexedDb";
import { startAutoSync, runSync, describeConflict } from "../services/syncEngine";
import { startPodSync, queuePod, countQueuedPod } from "../services/podOfflineQueue";
import { startLocationPingAutoSync } from "../services/locationSyncEngine";
import { writeSyncContext } from "../services/backgroundSyncContext";
import { API_BASE_URL } from "../services/api";
import { deleteDeliveryOnServer, fetchMyDeliveriesFromServer, updateMyAgentLocation, detectMyArea, clearMyArea, setMyArea, fetchAreaSuggestions, rescheduleDelivery } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import DeliveryStatusUpdater from "./DeliveryStatusUpdater";
import SyncStatusBadge from "./SyncStatusBadge";
import StatusBadge from "./StatusBadge";
import DeliveryDetailModal from "./DeliveryDetailModal";
import Pagination from "./Pagination";
import SuggestedRoute from "./SuggestedRoute";
import ProofOfDeliveryModal from "./ProofOfDeliveryModal";
import BarcodeScannerModal from "./BarcodeScannerModal";

const PULL_INTERVAL_MS = 15000; // check for newly-assigned deliveries every 15s while online
const PAGE_SIZE = 5;

/**
 * Main view for the delivery agent. Deliveries come from TWO sources,
 * merged together locally:
 * 1. Deliveries a dispatcher assigned (pulled from the server)
 * 2. Any local status updates the agent makes, saved to IndexedDB first
 *    and pushed up via the sync engine
 */
export default function AgentDeliveryList() {
  const { token, user, updateUser } = useAuth();
  const { showToast } = useToast();
  const [deliveries, setDeliveries] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDelivery, setSelectedDelivery] = useState(null);
  const [pendingDelivered, setPendingDelivered] = useState(null);
  const [pendingPodCount, setPendingPodCount] = useState(0);
  const [showScanner, setShowScanner] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [isSharingLocation, setIsSharingLocation] = useState(false);
  const [locationError, setLocationError] = useState(null);
  const [isDetectingArea, setIsDetectingArea] = useState(false);
  const [areaError, setAreaError] = useState(null);
  const [areaSuggestions, setAreaSuggestions] = useState([]);
  const [manualAreaInput, setManualAreaInput] = useState("");
  const [isSettingArea, setIsSettingArea] = useState(false);
  const [conflictNotices, setConflictNotices] = useState([]);
  const [reschedulingId, setReschedulingId] = useState(null);
  const [rescheduleDate, setRescheduleDate] = useState("");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [isRescheduling, setIsRescheduling] = useState(false);
  const watchIdRef = React.useRef(null);

  useEffect(() => {
    // CRITICAL: must happen before any IndexedDB read/write below. Scopes
    // local storage to THIS specific user, so switching accounts on the
    // same browser can never show one agent another agent's deliveries.
    setActiveUser(user.id);
    writeSyncContext({ userId: user.id, token, role: user.role, apiBaseUrl: API_BASE_URL });

    loadFromLocalStorage();
    pullAssignedDeliveries();
    fetchAreaSuggestions(token).then(setAreaSuggestions).catch(() => {});

    const stopAutoSync = startAutoSync((result) => {
      if (result.success && result.syncedCount > 0) {
        loadFromLocalStorage();
      }
      if (result.conflicts && result.conflicts.length > 0) {
        recordConflicts(result.conflicts);
      }
    });

    const stopLocationSync = startLocationPingAutoSync(token);
    const stopPodSync = startPodSync(() => token);
    countQueuedPod().then(setPendingPodCount).catch(() => {});
    const podCountIntervalId = setInterval(() => {
      countQueuedPod().then(setPendingPodCount).catch(() => {});
    }, PULL_INTERVAL_MS);

    const pullIntervalId = setInterval(() => {
      if (navigator.onLine) pullAssignedDeliveries();
    }, PULL_INTERVAL_MS);

    return () => {
      stopAutoSync();
      stopLocationSync();
      stopPodSync();
      clearInterval(pullIntervalId);
      clearInterval(podCountIntervalId);
    };
  }, []);

  // Reset to page 1 whenever the search query changes, so a new search
  // doesn't leave you stranded on a page that no longer has results
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  async function pullAssignedDeliveries() {
    if (!navigator.onLine) return;
    try {
      const assigned = await fetchMyDeliveriesFromServer(token);
      await mergeAssignedDeliveries(assigned);
      await loadFromLocalStorage();
    } catch (error) {
      console.warn("Could not pull assigned deliveries:", error.message);
      showToast(`Couldn't check for new assignments: ${error.message}`, "error");
    }
  }

  async function loadFromLocalStorage() {
    const records = await getAllLocalDeliveries();
    const sorted = records.sort(
      (a, b) => new Date(a.created_at) - new Date(b.created_at)
    );
    setDeliveries(sorted);
  }

  async function handleStatusUpdate(deliveryId, newStatus, notes, extras = {}) {
    if (newStatus === "delivered") {
      // Don't save yet — require proof of delivery first. The actual
      // save happens in handleProofConfirm once the agent provides it.
      // `extras` here carries is_partial/partial_notes from
      // DeliveryStatusUpdater's "partially delivered" toggle, so that
      // still applies once proof is captured.
      setPendingDelivered({ deliveryId, notes, extras });
      return;
    }
    await applyStatusUpdate(deliveryId, newStatus, notes, null, extras);
  }

  async function applyStatusUpdate(deliveryId, newStatus, notes, proofOfDelivery, extras = {}) {
    const existing = deliveries.find((d) => d.id === deliveryId);
    const now = new Date().toISOString();

    const updatedRecord = {
      ...existing,
      status: newStatus,
      notes: notes || existing?.notes || "",
      updated_at: now,
      ...(proofOfDelivery ? { proof_of_delivery: proofOfDelivery } : {}),
      // reason_code_id (failed_attempt) / is_partial + partial_notes
      // (delivered) — see routes/sync.py's SyncRecordIn and
      // services/conflict_resolver.py for how these get applied and
      // logged as a delivery attempt once this syncs to the server.
      ...extras,
    };

    await saveDeliveryLocally(updatedRecord);
    await loadFromLocalStorage();
  }

  async function handleProofConfirm(podPayload) {
    const { deliveryId, notes, extras } = pendingDelivered;
    setPendingDelivered(null);
    // podPayload is the full Phase 1 capture (recipient/OTP/signature/
    // photo/GPS/notes) — the legacy `proof_of_delivery` blob field on
    // the delivery record itself still gets the signature/photo (so
    // older UI that only reads that field keeps working unchanged);
    // the richer structured record is queued separately to
    // POST /deliveries/{id}/pod, which is what actually satisfies an
    // org's configured POD requirements (see services/pod.py).
    const legacyProofBlob = podPayload.signature_data_url || podPayload.photo_data_url || null;
    await applyStatusUpdate(deliveryId, "delivered", notes, legacyProofBlob, extras);
    await queuePod(deliveryId, podPayload);
    setPendingPodCount(await countQueuedPod());
    showToast(
      extras && extras.is_partial ? "Partial delivery confirmed with proof." : "Delivery confirmed with proof.",
      "success"
    );
  }

  async function handleRescheduleSubmit(deliveryId) {
    if (!rescheduleDate || !rescheduleReason.trim()) return;
    setIsRescheduling(true);
    try {
      const updated = await rescheduleDelivery(token, deliveryId, new Date(rescheduleDate).toISOString(), rescheduleReason.trim());
      // Reschedule is an online-only endpoint (not part of the offline
      // sync flow, since it needs the server's own failed-attempt
      // enforcement + reason logging immediately) — merge the server's
      // response straight into the local cache so the UI reflects it
      // without waiting for the next full re-fetch.
      await mergeAssignedDeliveries([updated]);
      await loadFromLocalStorage();
      showToast("Delivery rescheduled.", "success");
      setReschedulingId(null);
      setRescheduleDate("");
      setRescheduleReason("");
    } catch (error) {
      showToast(`Couldn't reschedule: ${error.message}`, "error");
    } finally {
      setIsRescheduling(false);
    }
  }

  async function handleDelete(delivery) {
    const confirmed = window.confirm(
      `Delete ${delivery.order_id}? This cannot be undone.`
    );
    if (!confirmed) return;

    await deleteDeliveryLocally(delivery.id);

    if (delivery.sync_status === "synced") {
      try {
        await deleteDeliveryOnServer(token, delivery.id);
      } catch (error) {
        console.warn("Could not delete on server (may be offline):", error.message);
      }
    }

    showToast(`Deleted ${delivery.order_id}.`, "success");
    await loadFromLocalStorage();
  }

  function toggleLocationSharing() {
    if (isSharingLocation) {
      if (watchIdRef.current !== null) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      setIsSharingLocation(false);
      return;
    }

    if (!navigator.geolocation) {
      setLocationError("Location isn't available on this device/browser.");
      return;
    }

    if (!window.isSecureContext) {
      setLocationError(
        "Location sharing needs a secure connection. If you're testing locally, open the app via 'localhost' " +
        "(not a network IP like 192.168.x.x) — browsers block location access on plain http:// outside localhost."
      );
      return;
    }

    setLocationError(null);
    watchIdRef.current = navigator.geolocation.watchPosition(
      async (position) => {
        try {
          await updateMyAgentLocation(token, position.coords.latitude, position.coords.longitude);
        } catch (err) {
          if (err instanceof TypeError) {
            // fetch() throws TypeError specifically when the network is
            // unreachable — queue it instead of losing it.
            // locationSyncEngine.js replays the queue (oldest first) the
            // moment connectivity returns.
            try {
              await queueLocationPing(position.coords.latitude, position.coords.longitude);
            } catch (queueErr) {
              console.warn("Failed to queue location ping locally:", queueErr.message);
            }
          } else {
            // A real server-side rejection (e.g. expired session) — queueing
            // this would just retry the same failure forever once "online".
            console.warn("Failed to push location update:", err.message);
          }
        }
      },
      (err) => {
        const friendlyMessage =
          err.code === err.PERMISSION_DENIED
            ? "Location permission was denied. Check your browser's site settings and allow location access, then try again."
            : err.code === err.TIMEOUT
            ? "Timed out getting your location. Check your device's location/GPS is turned on and try again."
            : `Couldn't get your location: ${err.message}`;
        setLocationError(friendlyMessage);
        setIsSharingLocation(false);
      },
      { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 }
    );
    setIsSharingLocation(true);
  }

  useEffect(() => {
    // Stop sharing if the agent navigates away from this screen entirely
    return () => {
      if (watchIdRef.current !== null) navigator.geolocation.clearWatch(watchIdRef.current);
    };
  }, []);

  function handleDetectArea() {
    if (!navigator.geolocation) {
      setAreaError("Location isn't available on this device/browser.");
      return;
    }
    if (!window.isSecureContext) {
      setAreaError(
        "Detecting your area needs a secure connection. If you're testing locally, open the app via " +
        "'localhost' (not a network IP like 192.168.x.x)."
      );
      return;
    }

    setAreaError(null);
    setIsDetectingArea(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const result = await detectMyArea(token, position.coords.latitude, position.coords.longitude);
          updateUser({ area_name: result.area_name });
        } catch (err) {
          setAreaError(err.message);
        } finally {
          setIsDetectingArea(false);
        }
      },
      (err) => {
        const friendlyMessage =
          err.code === err.PERMISSION_DENIED
            ? "Location permission was denied. Check your browser's site settings and allow location access, then try again."
            : err.code === err.TIMEOUT
            ? "Timed out getting your location. Check your device's location/GPS is turned on and try again."
            : `Couldn't get your location: ${err.message}`;
        setAreaError(friendlyMessage);
        setIsDetectingArea(false);
      },
      { enableHighAccuracy: true, timeout: 20000 }
    );
  }

  async function handleClearArea() {
    try {
      await clearMyArea(token);
      updateUser({ area_name: null });
    } catch (err) {
      setAreaError(err.message);
    }
  }

  async function handleSetAreaManually(areaName) {
    const trimmed = areaName.trim();
    if (!trimmed) return;
    setAreaError(null);
    setIsSettingArea(true);
    try {
      const result = await setMyArea(token, trimmed);
      updateUser({ area_name: result.area_name });
      setManualAreaInput("");
      if (!areaSuggestions.includes(result.area_name)) {
        setAreaSuggestions([...areaSuggestions, result.area_name].sort());
      }
    } catch (err) {
      setAreaError(err.message);
    } finally {
      setIsSettingArea(false);
    }
  }

  async function handleManualSync() {
    const result = await runSync();
    if (result.success) {
      if (result.syncedCount > 0) {
        showToast(`Synced ${result.syncedCount} record(s).`, "success");
      } else {
        showToast("Already up to date.", "info");
      }
      if (result.errorCount > 0) {
        showToast(
          `${result.errorCount} record(s) couldn't sync — they may not belong to your account.`,
          "error"
        );
      }
      if (result.conflicts && result.conflicts.length > 0) {
        recordConflicts(result.conflicts);
      }
      // CRITICAL: reload the UI from IndexedDB directly, unconditionally —
      // this is a pure local read and needs no network at all. The
      // previous version called pullAssignedDeliveries() here instead,
      // which ALSO tries to fetch new assignments from the server and
      // bails out early if navigator.onLine is false. That early return
      // was silently skipping the local-only UI refresh too, so a
      // successful sync (which DID update IndexedDB to "synced" — the
      // toast above was accurate) could still show stale "Saved locally"
      // badges on screen if the browser reported offline at that exact
      // moment. Splitting these two concerns fixes that: the local
      // reload always happens, and pulling new assignments is attempted
      // separately as a best-effort, network-dependent step.
      await loadFromLocalStorage();
      await pullAssignedDeliveries();
    } else {
      showToast(`Sync failed: ${result.error}`, "error");
    }
  }

  function recordConflicts(conflicts) {
    // Durable banner (not just a toast) — a discarded offline change is
    // exactly the kind of thing an agent shouldn't have to catch in a
    // 3.5-second popup. It stays visible until they dismiss it.
    const withIds = conflicts.map((c) => ({ ...c, _noticeId: `${c.id}-${c.your_updated_at}` }));
    setConflictNotices((prev) => {
      const existingIds = new Set(prev.map((n) => n._noticeId));
      const fresh = withIds.filter((n) => !existingIds.has(n._noticeId));
      return [...prev, ...fresh];
    });
    showToast(
      conflicts.length === 1
        ? "One of your updates was overridden by a newer change — see details below."
        : `${conflicts.length} of your updates were overridden by newer changes — see details below.`,
      "error"
    );
  }

  function dismissConflictNotice(noticeId) {
    setConflictNotices((prev) => prev.filter((n) => n._noticeId !== noticeId));
  }

  const filteredDeliveries = deliveries.filter((d) =>
    d.order_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalPages = Math.max(1, Math.ceil(filteredDeliveries.length / PAGE_SIZE));
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const visibleDeliveries = filteredDeliveries.slice(pageStart, pageStart + PAGE_SIZE);

  return (
    <div>
      <h2 className="page-title">My Deliveries</h2>

      {conflictNotices.length > 0 && (
        <div style={{ marginBottom: "14px", display: "grid", gap: "8px" }}>
          {conflictNotices.map((c) => (
            <div
              key={c._noticeId}
              className="card"
              style={{ borderColor: "var(--danger)", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px" }}
            >
              <div style={{ fontSize: "12.5px" }}>
                <strong style={{ color: "var(--danger)" }}>Update overridden — </strong>
                {describeConflict(c)}
              </div>
              <button className="btn" style={{ fontSize: "11px", flexShrink: 0 }} onClick={() => dismissConflictNotice(c._noticeId)}>
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}

      <SuggestedRoute deliveries={deliveries} token={token} />

      <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap" }}>
        <button className="btn btn-primary" onClick={handleManualSync}>
          Sync Now
        </button>
        <button className="btn" onClick={() => setShowScanner(true)}>
          Scan Package
        </button>
        <button
          className="btn"
          onClick={toggleLocationSharing}
          style={isSharingLocation ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
        >
          {isSharingLocation ? "📍 Sharing Location" : "📍 Share My Location"}
        </button>
        <input
          type="text"
          className="input"
          placeholder="Search by order ID..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{ flexGrow: 1, minWidth: "200px" }}
        />
      </div>

      {locationError && (
        <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "-12px", marginBottom: "16px" }}>
          {locationError}
        </p>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          flexWrap: "wrap",
          marginBottom: "20px",
          padding: "10px 14px",
          border: "1px solid var(--border-color)",
          borderRadius: "var(--radius-sm)",
        }}
      >
        <span style={{ fontSize: "12.5px", color: "var(--text-secondary)" }}>
          My area:{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            {user.area_name || "Not set"}
          </strong>
        </span>
        <button className="btn" style={{ fontSize: "12px" }} onClick={handleDetectArea} disabled={isDetectingArea}>
          {isDetectingArea ? "Detecting..." : "📍 Detect via GPS"}
        </button>
        {areaSuggestions.length > 0 && (
          <select
            className="input"
            style={{ fontSize: "12px", width: "auto" }}
            value=""
            onChange={(e) => { if (e.target.value) handleSetAreaManually(e.target.value); }}
            disabled={isSettingArea}
          >
            <option value="">Choose an area...</option>
            {areaSuggestions.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        )}
        <input
          type="text"
          className="input"
          style={{ fontSize: "12px", width: "160px" }}
          placeholder="Or type an area name"
          value={manualAreaInput}
          onChange={(e) => setManualAreaInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleSetAreaManually(manualAreaInput); } }}
        />
        <button
          className="btn"
          style={{ fontSize: "12px" }}
          onClick={() => handleSetAreaManually(manualAreaInput)}
          disabled={isSettingArea || !manualAreaInput.trim()}
        >
          Set
        </button>
        {user.area_name && (
          <button className="btn" style={{ fontSize: "12px" }} onClick={handleClearArea}>
            Clear
          </button>
        )}
      </div>
      {areaError && (
        <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "-12px", marginBottom: "16px" }}>
          {areaError}
        </p>
      )}

      {showScanner && (
        <BarcodeScannerModal
          onScan={(value) => {
            setSearchQuery(value);
            setShowScanner(false);
            showToast(`Scanned: ${value}`, "success");
          }}
          onClose={() => setShowScanner(false)}
        />
      )}

      {filteredDeliveries.length === 0 && deliveries.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">🚚</div>
          <div className="empty-state-title">No deliveries assigned yet</div>
          <div className="empty-state-body">Check back soon, or ask your dispatcher.</div>
        </div>
      )}
      {filteredDeliveries.length === 0 && deliveries.length > 0 && (
        <p style={{ color: "var(--text-secondary)" }}>No deliveries match "{searchQuery}".</p>
      )}

      {visibleDeliveries.map((delivery) => (
        <div key={delivery.id} className="delivery-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="delivery-card-order-id">{delivery.order_id}</span>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <SyncStatusBadge status={delivery.sync_status} />
              <button className="btn-info-outline" onClick={() => setSelectedDelivery(delivery)}>
                Details
              </button>
              <button className="btn-danger-outline" onClick={() => handleDelete(delivery)}>
                Delete
              </button>
            </div>
          </div>

          <div style={{ marginTop: "8px", display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <StatusBadge status={delivery.status} />
            {delivery.zone && (
              <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                Zone: {delivery.zone}
              </span>
            )}
            {(delivery.customer_email || delivery.customer_phone) && (
              <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                {[delivery.customer_email, delivery.customer_phone].filter(Boolean).join(" · ")}
              </span>
            )}
            {delivery.expected_by && (() => {
              const overdue = delivery.status !== "delivered" && new Date(delivery.expected_by) < new Date();
              return (
                <span style={{ fontSize: "12px", color: overdue ? "var(--danger)" : "var(--text-secondary)", fontWeight: overdue ? 600 : 400 }}>
                  Due: {new Date(delivery.expected_by).toLocaleString()}{overdue && " (Overdue)"}
                </span>
              );
            })()}
          </div>

          {delivery.notes && (
            <p style={{ marginTop: "8px", fontSize: "13px", color: "var(--text-secondary)" }}>
              {delivery.notes}
            </p>
          )}

          <DeliveryStatusUpdater
            deliveryId={delivery.id}
            currentStatus={delivery.status}
            onUpdate={handleStatusUpdate}
          />

          {delivery.status !== "delivered" && delivery.status !== "cancelled" && (
            reschedulingId === delivery.id ? (
              <div style={{ marginTop: "10px", padding: "10px", border: "1px solid var(--border)", borderRadius: "8px" }}>
                <label style={{ fontSize: "13px", fontWeight: 600, display: "block", marginBottom: "6px" }}>
                  New delivery date/time
                </label>
                <input
                  type="datetime-local"
                  className="input"
                  value={rescheduleDate}
                  onChange={(e) => setRescheduleDate(e.target.value)}
                  style={{ width: "100%" }}
                />
                <input
                  type="text"
                  className="input"
                  placeholder="Reason (e.g. customer asked for tomorrow)"
                  value={rescheduleReason}
                  onChange={(e) => setRescheduleReason(e.target.value)}
                  style={{ marginTop: "8px", width: "100%" }}
                />
                <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                  <button
                    className="btn btn-primary"
                    disabled={isRescheduling || !rescheduleDate || !rescheduleReason.trim()}
                    onClick={() => handleRescheduleSubmit(delivery.id)}
                  >
                    {isRescheduling ? "Rescheduling…" : "Confirm Reschedule"}
                  </button>
                  <button className="btn" onClick={() => setReschedulingId(null)}>Cancel</button>
                </div>
                {!navigator.onLine && (
                  <p style={{ fontSize: "12px", color: "var(--danger)", marginTop: "6px" }}>
                    Rescheduling needs a connection — try again once you're back online.
                  </p>
                )}
              </div>
            ) : (
              <button
                className="btn"
                style={{ marginTop: "8px" }}
                onClick={() => { setReschedulingId(delivery.id); setRescheduleDate(""); setRescheduleReason(""); }}
              >
                Reschedule
              </button>
            )
          )}

          {delivery.reschedule_count > 0 && (
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "6px" }}>
              Rescheduled {delivery.reschedule_count}x
              {delivery.rescheduled_to && ` — next attempt: ${new Date(delivery.rescheduled_to).toLocaleString()}`}
            </p>
          )}
        </div>
      ))}

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
          onClose={() => setSelectedDelivery(null)}
        />
      )}

      {pendingDelivered && (
        <ProofOfDeliveryModal
          deliveryId={pendingDelivered.deliveryId}
          token={token}
          onConfirm={handleProofConfirm}
          onCancel={() => setPendingDelivered(null)}
        />
      )}
      {pendingPodCount > 0 && (
        <div style={{ position: "fixed", bottom: 16, right: 16, background: "#334155", color: "#fff", padding: "8px 14px", borderRadius: 8, fontSize: 13 }}>
          {pendingPodCount} proof-of-delivery {pendingPodCount === 1 ? "record" : "records"} waiting to sync
        </div>
      )}
    </div>
  );
}
