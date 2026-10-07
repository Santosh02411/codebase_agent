import React, { useEffect, useState } from "react";
import {
  fetchOrganizationUsers,
  fetchOrganizationInfo,
  deactivateUser,
  activateUser,
  resetUserPassword,
  fetchCustomRoles,
  assignCustomRole,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import PasswordInput from "./PasswordInput";

/**
 * Admin panel: view every user in the admin's own organization, and
 * deactivate/reactivate accounts or reset a user's password.
 *
 * Honest limitation shown in the UI too: password reset sets a new
 * password directly (no email service is available) — the admin must
 * communicate it to the user some other way.
 */
export default function AdminPanel() {
  const { token, user: currentUser } = useAuth();
  const { showToast } = useToast();
  const [users, setUsers] = useState([]);
  const [orgInfo, setOrgInfo] = useState(null);
  const [error, setError] = useState(null);
  const [resetTargetId, setResetTargetId] = useState(null);
  const [newPassword, setNewPassword] = useState("");
  const [isResetting, setIsResetting] = useState(false);
  const [customRoles, setCustomRoles] = useState([]);

  useEffect(() => {
    loadUsers();
    loadOrgInfo();
    loadCustomRoles();
  }, []);

  async function loadCustomRoles() {
    try {
      setCustomRoles(await fetchCustomRoles(token));
    } catch (err) {
      console.warn("Could not load custom roles:", err.message);
    }
  }

  async function handleAssignRole(userId, customRoleId) {
    try {
      await assignCustomRole(token, userId, customRoleId || null);
      showToast("Role assignment updated.", "success");
      await loadUsers();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadOrgInfo() {
    try {
      const info = await fetchOrganizationInfo(token);
      setOrgInfo(info);
    } catch (err) {
      console.warn("Could not load organization info:", err.message);
    }
  }

  async function loadUsers() {
    try {
      const data = await fetchOrganizationUsers(token);
      setUsers(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleToggleActive(user) {
    try {
      if (user.is_active) {
        await deactivateUser(token, user.id);
        showToast(`Deactivated ${user.display_name}.`, "success");
      } else {
        await activateUser(token, user.id);
        showToast(`Reactivated ${user.display_name}.`, "success");
      }
      await loadUsers();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    if (newPassword.length < 6) {
      showToast("New password must be at least 6 characters.", "error");
      return;
    }
    setIsResetting(true);
    try {
      await resetUserPassword(token, resetTargetId, newPassword);
      showToast("Password reset. Share the new password with the user yourself.", "success");
      setResetTargetId(null);
      setNewPassword("");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsResetting(false);
    }
  }

  return (
    <div>
      <h2 className="page-title">Admin — Organization Users</h2>

      {orgInfo && (
        <div className="card" style={{ marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Organization</div>
            <div style={{ fontSize: "15px", fontWeight: 600 }}>{orgInfo.name}</div>
          </div>
          <div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Invite Code (share with your team)</div>
            <div className="mono" style={{ fontSize: "16px", fontWeight: 600, letterSpacing: "0.08em" }}>
              {orgInfo.invite_code}
            </div>
          </div>
        </div>
      )}

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Display Name</th>
              <th>Username</th>
              <th>Role</th>
              <th>Custom Role</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.display_name}</td>
                <td className="mono">{u.username}</td>
                <td style={{ textTransform: "capitalize" }}>{u.role}</td>
                <td>
                  {u.role === "admin" ? (
                    <span style={{ color: "var(--text-muted)", fontSize: "12px" }}>N/A (full access)</span>
                  ) : (
                    <select
                      className="input"
                      style={{ fontSize: "12.5px", padding: "4px 6px" }}
                      value={u.custom_role_id || ""}
                      onChange={(e) => handleAssignRole(u.id, e.target.value)}
                    >
                      <option value="">Default ({u.role} permissions)</option>
                      {customRoles.map((r) => (
                        <option key={r.id} value={r.id}>{r.name}</option>
                      ))}
                    </select>
                  )}
                </td>
                <td>
                  <span style={{ color: u.is_active ? "var(--status-delivered)" : "var(--danger)", fontWeight: 600 }}>
                    {u.is_active ? "Active" : "Deactivated"}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", gap: "8px" }}>
                    {u.id !== currentUser.id && (
                      <button
                        className={u.is_active ? "btn-danger-outline" : "btn-info-outline"}
                        onClick={() => handleToggleActive(u)}
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    )}
                    <button className="btn-info-outline" onClick={() => setResetTargetId(u.id)}>
                      Reset Password
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {resetTargetId && (
        <div className="modal-overlay" onClick={() => setResetTargetId(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "360px" }}>
            <h3>Reset Password</h3>
            <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
              This sets the password directly — there's no email service to
              send a reset link, so you'll need to share the new password
              with {users.find((u) => u.id === resetTargetId)?.display_name} yourself.
            </p>
            <form onSubmit={handleResetPassword}>
              <PasswordInput
                className="input"
                placeholder="New password (min. 6 characters)"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                style={{ width: "100%", marginBottom: "12px" }}
                autoFocus
              />
              <div style={{ display: "flex", gap: "8px" }}>
                <button type="submit" className="btn btn-primary" disabled={isResetting}>
                  {isResetting ? "Resetting..." : "Reset Password"}
                </button>
                <button type="button" className="btn" onClick={() => setResetTargetId(null)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
