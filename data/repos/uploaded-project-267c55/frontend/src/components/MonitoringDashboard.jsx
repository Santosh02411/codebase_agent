import React, { useEffect, useState } from "react";
import {
  fetchMonitoringStatus, fetchApiMetrics, fetchNotificationMetrics, fetchErrorLogs,
  fetchBackups, triggerBackup, verifyBackup,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

/** Monitoring & reliability dashboard (Phase 18): admin-only. Health, job heartbeats, API/notification metrics, error log, backups. */
export default function MonitoringDashboard() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [status, setStatus] = useState(null);
  const [apiMetrics, setApiMetrics] = useState(null);
  const [notificationMetrics, setNotificationMetrics] = useState(null);
  const [errors, setErrors] = useState([]);
  const [backups, setBackups] = useState([]);
  const [creatingBackup, setCreatingBackup] = useState(false);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try {
      setStatus(await fetchMonitoringStatus(token));
      setApiMetrics(await fetchApiMetrics(token));
      setNotificationMetrics(await fetchNotificationMetrics(token));
      setErrors(await fetchErrorLogs(token));
      setBackups(await fetchBackups(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCreateBackup() {
    setCreatingBackup(true);
    try {
      const result = await triggerBackup(token);
      showToast(result.status === "success" ? "Backup created." : result.message, result.status === "success" ? "success" : "error");
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setCreatingBackup(false);
    }
  }

  async function handleVerify(filename) {
    try {
      const result = await verifyBackup(token, filename);
      showToast(result.status === "success" ? `Verified — ${result.size_bytes} bytes, checksum OK.` : result.message, result.status === "success" ? "success" : "error");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  if (!status) return <div style={{ color: "var(--text-muted)" }}>Loading...</div>;

  return (
    <div>
      <h2 className="page-title">Monitoring & Reliability</h2>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", marginBottom: "20px" }}>
        <div className="card" style={{ flex: "1 1 160px" }}>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Database</div>
          <div style={{ fontSize: "18px", fontWeight: 700, marginTop: "4px", color: status.database.status === "ok" ? "var(--success, #15803d)" : "var(--danger, #b91c1c)" }}>
            {status.database.status === "ok" ? `OK (${status.database.latency_ms}ms)` : "Error"}
          </div>
        </div>
        <div className="card" style={{ flex: "1 1 160px" }}>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Background Jobs</div>
          <div style={{ fontSize: "18px", fontWeight: 700, marginTop: "4px", color: status.all_jobs_healthy === false ? "var(--danger, #b91c1c)" : "var(--success, #15803d)" }}>
            {status.all_jobs_healthy === null ? "No data yet" : status.all_jobs_healthy ? "All Healthy" : "Attention Needed"}
          </div>
        </div>
        <div className="card" style={{ flex: "1 1 160px" }}>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>WebSocket Connections</div>
          <div style={{ fontSize: "18px", fontWeight: 700, marginTop: "4px" }}>{status.websocket.total_connections} <span style={{ fontSize: "12px", fontWeight: 400 }}>({status.websocket.active_rooms} rooms)</span></div>
        </div>
        {apiMetrics && (
          <div className="card" style={{ flex: "1 1 160px" }}>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>API Error Rate</div>
            <div style={{ fontSize: "18px", fontWeight: 700, marginTop: "4px" }}>{apiMetrics.error_rate_percent}%</div>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "20px" }}>
        <strong style={{ display: "block", padding: "12px" }}>Background Job Heartbeats</strong>
        <table className="data-table">
          <thead><tr><th>Job</th><th>Status</th><th>Last Run</th><th>Duration</th><th>Runs</th><th>Errors</th></tr></thead>
          <tbody>
            {status.background_jobs.length === 0 && <tr><td colSpan={6} style={{ color: "var(--text-muted)" }}>No jobs have run yet.</td></tr>}
            {status.background_jobs.map((j) => (
              <tr key={j.job_name}>
                <td>{j.job_name}</td>
                <td style={{ color: j.is_healthy ? "var(--success, #15803d)" : "var(--danger, #b91c1c)" }}>{j.is_healthy ? "Healthy" : "Unhealthy"}</td>
                <td>{j.last_run_at ? new Date(j.last_run_at).toLocaleString() : "Never"}</td>
                <td>{j.last_duration_ms != null ? `${j.last_duration_ms}ms` : "—"}</td>
                <td>{j.run_count}</td>
                <td>{j.error_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        {apiMetrics && (
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <strong style={{ display: "block", padding: "12px" }}>Slowest Endpoints</strong>
            <table className="data-table">
              <thead><tr><th>Endpoint</th><th>Avg</th><th>Requests</th></tr></thead>
              <tbody>
                {apiMetrics.slowest_endpoints.length === 0 && <tr><td colSpan={3} style={{ color: "var(--text-muted)" }}>No traffic yet.</td></tr>}
                {apiMetrics.slowest_endpoints.slice(0, 8).map((e) => (
                  <tr key={e.endpoint}>
                    <td style={{ fontSize: "12px" }}>{e.endpoint}</td>
                    <td>{e.avg_duration_ms}ms</td>
                    <td>{e.request_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {notificationMetrics && (
          <div className="card">
            <strong style={{ display: "block", marginBottom: "8px" }}>Notification Delivery</strong>
            {Object.keys(notificationMetrics).length === 0 && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No notifications sent yet.</div>}
            {Object.entries(notificationMetrics).map(([channel, stats]) => (
              <div key={channel} style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "4px 0" }}>
                <span style={{ textTransform: "capitalize" }}>{channel}</span>
                <span>{stats.sent} sent{stats.failed > 0 ? `, ${stats.failed} failed` : ""}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <strong>Database Backups</strong>
          <button className="btn btn-primary" disabled={creatingBackup} onClick={handleCreateBackup}>
            {creatingBackup ? "Creating..." : "Create Backup"}
          </button>
        </div>
        <table className="data-table">
          <thead><tr><th>File</th><th>Size</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {backups.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No backups yet.</td></tr>}
            {backups.map((b) => (
              <tr key={b.filename}>
                <td className="mono">{b.filename}</td>
                <td>{(b.size_bytes / 1024).toFixed(1)} KB</td>
                <td>{new Date(b.created_at).toLocaleString()}</td>
                <td><button className="btn-info-outline" onClick={() => handleVerify(b.filename)}>Verify</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <strong style={{ display: "block", padding: "12px" }}>Recent Errors</strong>
        <table className="data-table">
          <thead><tr><th>Endpoint</th><th>Type</th><th>Message</th><th>When</th></tr></thead>
          <tbody>
            {errors.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No errors recorded.</td></tr>}
            {errors.map((e) => (
              <tr key={e.id}>
                <td className="mono" style={{ fontSize: "12px" }}>{e.method} {e.path}</td>
                <td>{e.error_type}</td>
                <td style={{ fontSize: "12px" }}>{e.error_message}</td>
                <td>{new Date(e.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
