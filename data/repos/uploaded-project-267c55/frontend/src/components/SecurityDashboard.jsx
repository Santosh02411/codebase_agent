import React, { useEffect, useState } from "react";
import {
  fetchMySessions, revokeMySession, logoutAllSessions,
  fetchMyLoginHistory, fetchMySecurityEvents, regenerateRecoveryCodes,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import PasswordInput from "./PasswordInput";

const EVENT_LABELS = {
  login_success: "Successful login", login_failed: "Failed login attempt", suspicious_login: "Login from a new location",
  password_changed: "Password changed", password_reset: "Password reset", "2fa_enabled": "Two-factor authentication enabled",
  "2fa_disabled": "Two-factor authentication disabled", session_revoked: "Session revoked", all_sessions_revoked: "Logged out of all devices",
  account_locked: "Account locked (too many failed attempts)", recovery_codes_generated: "Recovery codes generated", recovery_code_used: "Recovery code used",
};

/** Sessions, login history, security events, and recovery codes (Phase 17). Sits alongside TwoFactorSettings on the Security page. */
export default function SecurityDashboard() {
  const { token, refreshToken, user } = useAuth();
  const { showToast } = useToast();

  const [sessions, setSessions] = useState([]);
  const [loginHistory, setLoginHistory] = useState([]);
  const [securityEvents, setSecurityEvents] = useState([]);
  const [revealedCodes, setRevealedCodes] = useState(null);
  const [regenPassword, setRegenPassword] = useState("");
  const [showRegenForm, setShowRegenForm] = useState(false);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try {
      setSessions(await fetchMySessions(token, refreshToken));
      setLoginHistory(await fetchMyLoginHistory(token));
      setSecurityEvents(await fetchMySecurityEvents(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleRevoke(sessionId) {
    try {
      await revokeMySession(token, sessionId);
      showToast("Session revoked.", "success");
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleLogoutAll() {
    if (!window.confirm("Log out of all devices, including this one?")) return;
    try {
      await logoutAllSessions(token);
      showToast("Logged out everywhere.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleRegenerateCodes(e) {
    e.preventDefault();
    try {
      const result = await regenerateRecoveryCodes(token, regenPassword);
      setRevealedCodes(result.codes);
      setRegenPassword("");
      setShowRegenForm(false);
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div style={{ marginTop: "24px" }}>
      {revealedCodes && (
        <div className="card" style={{ marginBottom: "20px", borderLeft: "3px solid var(--warning, #b45309)" }}>
          <strong>Save these recovery codes now — they won't be shown again:</strong>
          <div className="mono" style={{ marginTop: "8px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px" }}>
            {revealedCodes.map((c) => <div key={c}>{c}</div>)}
          </div>
          <button className="btn-info-outline" style={{ marginTop: "8px" }} onClick={() => setRevealedCodes(null)}>Dismiss</button>
        </div>
      )}

      {user.totp_enabled && (
        <div className="card" style={{ marginBottom: "20px" }}>
          <strong style={{ display: "block", marginBottom: "8px" }}>Recovery Codes</strong>
          <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "8px" }}>
            Use a recovery code to sign in if you lose access to your authenticator app or 2FA email. Regenerating invalidates any unused codes.
          </p>
          {!showRegenForm ? (
            <button className="btn-info-outline" onClick={() => setShowRegenForm(true)}>Regenerate Codes</button>
          ) : (
            <form onSubmit={handleRegenerateCodes} style={{ display: "flex", gap: "8px" }}>
              <PasswordInput className="input" placeholder="Confirm your password" required value={regenPassword} onChange={(e) => setRegenPassword(e.target.value)} />
              <button type="submit" className="btn btn-primary">Confirm</button>
            </form>
          )}
        </div>
      )}

      <div className="card" style={{ marginBottom: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <strong>Active Sessions</strong>
          <button className="btn-danger-outline" onClick={handleLogoutAll}>Log Out All Devices</button>
        </div>
        <table className="data-table">
          <thead><tr><th>Device</th><th>IP Address</th><th>Since</th><th></th></tr></thead>
          <tbody>
            {sessions.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No active sessions.</td></tr>}
            {sessions.map((s) => (
              <tr key={s.id}>
                <td>{s.device_info || "Unknown device"} {s.is_current && <em style={{ color: "var(--text-muted)" }}>(this device)</em>}</td>
                <td className="mono">{s.ip_address || "—"}</td>
                <td>{new Date(s.created_at).toLocaleString()}</td>
                <td>{!s.is_current && <button className="btn-danger-outline" onClick={() => handleRevoke(s.id)}>Revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <strong style={{ display: "block", padding: "12px" }}>Login History</strong>
          <table className="data-table">
            <thead><tr><th>Event</th><th>IP</th><th>When</th></tr></thead>
            <tbody>
              {loginHistory.length === 0 && <tr><td colSpan={3} style={{ color: "var(--text-muted)" }}>No login history yet.</td></tr>}
              {loginHistory.map((h) => (
                <tr key={h.id}>
                  <td style={{ color: h.event_type === "login_failed" ? "var(--danger, #b91c1c)" : h.event_type === "suspicious_login" ? "var(--warning, #b45309)" : undefined }}>
                    {EVENT_LABELS[h.event_type] || h.event_type}
                  </td>
                  <td className="mono">{h.ip_address || "—"}</td>
                  <td>{new Date(h.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <strong style={{ display: "block", padding: "12px" }}>Security Activity</strong>
          <table className="data-table">
            <thead><tr><th>Event</th><th>When</th></tr></thead>
            <tbody>
              {securityEvents.length === 0 && <tr><td colSpan={2} style={{ color: "var(--text-muted)" }}>No security activity yet.</td></tr>}
              {securityEvents.map((e) => (
                <tr key={e.id}>
                  <td>{EVENT_LABELS[e.event_type] || e.event_type}</td>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
