import React, { useEffect, useState } from "react";
import {
  fetchPermissionsCatalog,
  fetchCustomRoles,
  createCustomRole,
  updateCustomRole,
  deleteCustomRole,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

/**
 * Admin-only custom-role editor (Phase 4). Assigning a role to a
 * specific user happens from the user list in AdminPanel — this view
 * is just for defining what each role can do. Real enforcement of
 * every permission checked here happens on the backend
 * (services/permissions.py's require_permission) — this UI only
 * decides what buttons/menu items a permission-aware frontend shows,
 * it is never the actual authorization boundary.
 */
export default function RbacManager() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [catalog, setCatalog] = useState([]);
  const [roles, setRoles] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedPerms, setSelectedPerms] = useState([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    try {
      const [cat, roleList] = await Promise.all([fetchPermissionsCatalog(token), fetchCustomRoles(token)]);
      setCatalog(cat);
      setRoles(roleList);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function openNewForm() {
    setName("");
    setDescription("");
    setSelectedPerms([]);
    setEditingId(null);
    setShowForm(true);
  }

  function openEditForm(role) {
    setName(role.name);
    setDescription(role.description || "");
    setSelectedPerms(role.permissions);
    setEditingId(role.id);
    setShowForm(true);
  }

  function togglePerm(perm) {
    setSelectedPerms((prev) => (prev.includes(perm) ? prev.filter((p) => p !== perm) : [...prev, perm]));
  }

  async function handleSave(e) {
    e.preventDefault();
    setIsSaving(true);
    try {
      const payload = { name: name.trim(), description: description.trim() || null, permissions: selectedPerms };
      if (editingId) {
        await updateCustomRole(token, editingId, payload);
        showToast("Custom role updated.", "success");
      } else {
        await createCustomRole(token, payload);
        showToast("Custom role created.", "success");
      }
      setShowForm(false);
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(roleId) {
    try {
      const result = await deleteCustomRole(token, roleId);
      showToast(
        result.users_reset_to_default > 0
          ? `Role deleted. ${result.users_reset_to_default} user(s) reset to their default role permissions.`
          : "Role deleted.",
        "success"
      );
      await loadAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // group the flat catalog by resource prefix (e.g. "deliveries.*") for a readable checklist
  const grouped = catalog.reduce((acc, perm) => {
    const [resource] = perm.split(".");
    acc[resource] = acc[resource] || [];
    acc[resource].push(perm);
    return acc;
  }, {});

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 className="page-title" style={{ marginBottom: 0 }}>Custom Roles</h2>
        <button className="btn btn-primary" onClick={openNewForm}>+ New Role</button>
      </div>
      <p style={{ color: "var(--text-secondary)", fontSize: "13px", marginBottom: "16px" }}>
        Define named roles with an exact set of permissions, then assign them to individual users from the Manage Users page. A user with no custom role assigned keeps their normal agent/dispatcher/admin permissions.
      </p>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Description</th>
              <th>Permissions</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {roles.length === 0 && (
              <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No custom roles yet.</td></tr>
            )}
            {roles.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td style={{ color: "var(--text-secondary)" }}>{r.description || "—"}</td>
                <td style={{ fontSize: "12px" }}>{r.permissions.length} permission{r.permissions.length === 1 ? "" : "s"}</td>
                <td>
                  <div style={{ display: "flex", gap: "6px" }}>
                    <button className="btn-info-outline" onClick={() => openEditForm(r)}>Edit</button>
                    <button className="btn-danger-outline" onClick={() => handleDelete(r.id)}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "480px", maxHeight: "85vh", overflowY: "auto" }}>
            <h3 style={{ marginBottom: "12px" }}>{editingId ? "Edit" : "New"} Custom Role</h3>
            <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Name</label>
                <input className="input" required value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Description (optional)</label>
                <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Permissions</label>
                {Object.entries(grouped).map(([resource, perms]) => (
                  <div key={resource} style={{ marginBottom: "8px", padding: "8px", border: "1px solid var(--border-color)", borderRadius: "var(--radius-sm)" }}>
                    <div style={{ fontWeight: 600, fontSize: "12.5px", textTransform: "capitalize", marginBottom: "4px" }}>{resource}</div>
                    {perms.map((perm) => (
                      <label key={perm} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12.5px", padding: "2px 0" }}>
                        <input type="checkbox" checked={selectedPerms.includes(perm)} onChange={() => togglePerm(perm)} />
                        {perm}
                      </label>
                    ))}
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
                <button type="submit" className="btn btn-primary" disabled={isSaving}>{isSaving ? "Saving..." : "Save"}</button>
                <button type="button" className="btn" onClick={() => setShowForm(false)}>Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
