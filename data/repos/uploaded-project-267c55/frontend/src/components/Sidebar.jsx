import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { fetchStaffVapidPublicKey, subscribeStaffToPush } from "../services/api";
import { urlBase64ToUint8Array } from "../services/pushUtil";

/**
 * Left sidebar navigation. Nav items differ by role: agents get
 * "My Deliveries" and "Performance"; dispatchers get a single
 * "Dashboard" (which already includes assignment, filtering, and stats).
 *
 * On mobile (see the max-width:768px block in theme.css), this becomes an
 * off-canvas drawer: hidden by default, toggled open by a hamburger button
 * in a slim top bar, with a dark overlay behind it that closes the drawer
 * when tapped. On desktop, none of that applies — the sidebar is simply
 * always visible, exactly as before.
 */
export default function Sidebar({ activeView, onNavigate }) {
  const { user, token, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [pushStatus, setPushStatus] = useState("idle");

  useEffect(() => {
    if (!("Notification" in window)) {
      setPushStatus("unsupported");
    } else if (Notification.permission === "granted") {
      setPushStatus("enabled");
    } else if (Notification.permission === "denied") {
      setPushStatus("denied");
    }
  }, []);

  async function handleEnablePush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setPushStatus("unsupported");
      return;
    }
    setPushStatus("enabling");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setPushStatus(permission === "denied" ? "denied" : "idle");
        return;
      }

      const registration = await navigator.serviceWorker.ready;
      const { public_key: vapidPublicKey } = await fetchStaffVapidPublicKey(token);

      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });
      }

      await subscribeStaffToPush(token, subscription.toJSON());
      setPushStatus("enabled");
    } catch (err) {
      console.warn("Push enable failed:", err.message);
      setPushStatus("idle");
    }
  }

  const agentLinks = [
    { key: "deliveries", label: "My Deliveries", icon: "\u25A4" },
    { key: "performance", label: "Performance", icon: "\u25CE" },
    { key: "workforce", label: "My Workforce", icon: "\u25F0" },
    { key: "fleet", label: "My Vehicle", icon: "\u2691" },
    { key: "account", label: "My Account", icon: "\u25CB" },
    { key: "security", label: "Security", icon: "\u26BF" },
  ];

  const dispatcherLinks = [
    { key: "dashboard", label: "Dashboard", icon: "\u25A4" },
    { key: "sla", label: "SLA", icon: "\u23F1" },
    { key: "warehouses", label: "Warehouses", icon: "\u2b1a" },
    { key: "fleet", label: "Fleet", icon: "\u2691" },
    { key: "reconciliation", label: "Finance", icon: "\u20B9" },
    { key: "rto", label: "RTO", icon: "\u21A9" },
    { key: "routing", label: "Routing", icon: "\u26F0" },
    { key: "workforce", label: "Workforce", icon: "\u25F0" },
    { key: "products", label: "Products", icon: "\u25A3" },
    { key: "returns", label: "Returns & Exchanges", icon: "\u21BA" },
    { key: "support", label: "Support", icon: "\u2753" },
    { key: "invoicing", label: "Invoicing", icon: "\u20B9" },
    { key: "account", label: "My Account", icon: "\u25CB" },
    { key: "security", label: "Security", icon: "\u26BF" },
  ];

  const adminLinks = [
    { key: "dashboard", label: "Dashboard", icon: "\u25A4" },
    { key: "analytics", label: "Analytics", icon: "\u25C8" },
    { key: "advanced-analytics", label: "Advanced Analytics", icon: "\u25C9" },
    { key: "sla", label: "SLA", icon: "\u23F1" },
    { key: "warehouses", label: "Warehouses", icon: "\u2b1a" },
    { key: "reconciliation", label: "Finance", icon: "\u20B9" },
    { key: "rto", label: "RTO", icon: "\u21A9" },
    { key: "routing", label: "Routing", icon: "\u26F0" },
    { key: "workforce", label: "Workforce", icon: "\u25F0" },
    { key: "fleet", label: "Fleet", icon: "\u2691" },
    { key: "products", label: "Products", icon: "\u25A3" },
    { key: "admin", label: "Manage Users", icon: "\u2699" },
    { key: "rbac", label: "Custom Roles", icon: "\u26E8" },
    { key: "zones", label: "Zones", icon: "\u2b21" },
    { key: "reason-codes", label: "Reason Codes", icon: "\u2691" },
    { key: "pod-settings", label: "Proof of Delivery", icon: "\u2713" },
    { key: "notification-templates", label: "Notifications", icon: "\u2709" },
    { key: "returns", label: "Returns & Exchanges", icon: "\u21BA" },
    { key: "support", label: "Support", icon: "\u2753" },
    { key: "invoicing", label: "Invoicing", icon: "\u20B9" },
    { key: "api-webhooks", label: "API & Webhooks", icon: "\u2707" },
    { key: "organization", label: "Organization", icon: "\u2302" },
    { key: "monitoring", label: "Monitoring", icon: "\u2699" },
    { key: "audit-log", label: "Audit Log", icon: "\u2637" },
    { key: "account", label: "My Account", icon: "\u25CB" },
    { key: "security", label: "Security", icon: "\u26BF" },
  ];

  const links =
    user.role === "agent" ? agentLinks :
    user.role === "admin" ? adminLinks :
    dispatcherLinks;

  const sectionLabel =
    user.role === "agent" ? "Agent" :
    user.role === "admin" ? "Admin" :
    "Dispatch";

  function handleNavigate(key) {
    onNavigate(key);
    setIsMobileOpen(false); // close the drawer after picking a page, on mobile
  }

  return (
    <>
      {/* Only visible on mobile widths (theme.css) — always present in the
          DOM so the hamburger button exists regardless of screen size at
          the moment the component first renders. */}
      <div className="mobile-topbar">
        <span className="mobile-topbar-brand">Delivery Sync</span>
        <button
          className="mobile-menu-btn"
          onClick={() => setIsMobileOpen(!isMobileOpen)}
          aria-label="Toggle menu"
        >
          {isMobileOpen ? "\u2715" : "\u2630"}
        </button>
      </div>

      {isMobileOpen && (
        <div className="sidebar-overlay" onClick={() => setIsMobileOpen(false)} />
      )}

      <div className={`sidebar ${isMobileOpen ? "mobile-open" : ""}`}>
        <div className="sidebar-brand">Delivery Sync</div>

        <div className="sidebar-section-label">{sectionLabel}</div>

        {links.map((link) => (
          <div
            key={link.key}
            className={`sidebar-link ${activeView === link.key ? "active" : ""}`}
            onClick={() => handleNavigate(link.key)}
          >
            <span aria-hidden="true">{link.icon}</span>
            {link.label}
          </div>
        ))}

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <strong>{user.display_name}</strong>
            {user.role}
          </div>
          {pushStatus !== "unsupported" && pushStatus !== "denied" && (
            <button
              className="btn sidebar-action-btn"
              onClick={handleEnablePush}
              disabled={pushStatus === "enabled" || pushStatus === "enabling"}
              title={
                user.role === "agent"
                  ? "Get notified the moment a new delivery is assigned to you"
                  : "Get notified the moment a new order needs an agent assigned"
              }
            >
              {pushStatus === "enabled" ? "🔔 Notifications On" : pushStatus === "enabling" ? "Enabling..." : "🔔 Enable Notifications"}
            </button>
          )}
          <button className="btn sidebar-action-btn" onClick={toggleTheme}>
            {theme === "dark" ? "☀ Light Mode" : "☾ Dark Mode"}
          </button>
          <button className="btn sidebar-action-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </div>
    </>
  );
}
