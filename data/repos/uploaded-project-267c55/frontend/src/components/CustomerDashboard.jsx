import React, { useEffect, useState } from "react";
import { useCustomerAuth } from "../context/CustomerAuthContext";
import { useTheme } from "../context/ThemeContext";
import { customerResendVerificationRequest } from "../services/authApi";
import VerificationBanner from "./VerificationBanner";
import {
  fetchMyCustomerDeliveries,
  fetchMyCustomerDeliveryHistory,
  fetchMyCustomerDeliveryPod,
  fetchMyCustomerDeliveryFeedback,
  fetchMyCustomerNotifications,
  markAllCustomerNotificationsRead,
  submitDeliveryFeedback,
  claimCustomerOrder,
  cancelCustomerDelivery,
  reorderCustomerDelivery,
  fetchMyOrders,
  fetchReviewableItems,
  submitProductReview,
  fetchMyCustomerAddresses,
  addCustomerAddress,
  deleteCustomerAddress,
  fetchVapidPublicKey,
  subscribeToPush,
  exportCustomerData,
  deleteCustomerAccount,
  deleteCustomerNotification,
  clearCustomerNotifications,
  fetchMyCustomerProfile,
  updateMyCustomerProfile,
  changeMyCustomerPassword,
  setMyCustomerPassword,
  createReturnRequest,
  fetchMyReturnRequests,
  API_BASE_URL,
} from "../services/api";
import StatusBadge from "./StatusBadge";
import LiveTrackingMap from "./LiveTrackingMap";
import Storefront from "./Storefront";
import SubscriptionManager from "./SubscriptionManager";
import "../styles/auth.css";
import {
  setActiveCustomer,
  cacheCustomerDeliveries,
  getCachedCustomerDeliveries,
  getCustomerLastSyncedAt,
  queueCustomerAction,
} from "../services/customerOfflineStore";
import { startCustomerActionAutoSync } from "../services/customerSyncEngine";
import { writeSyncContext } from "../services/backgroundSyncContext";
import { urlBase64ToUint8Array } from "../services/pushUtil";
import CustomerDeliveryMessages from "./CustomerDeliveryMessages";
import CustomerSupportPanel from "./CustomerSupportPanel";
import CustomerInvoicesPanel from "./CustomerInvoicesPanel";
import PasswordInput from "./PasswordInput";

const STATUS_LABELS = {
  confirmed: "Order Confirmed",
  pending: "Placed (Awaiting Assignment)",
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  failed_attempt: "Delivery Attempt Failed",
  cancelled: "Cancelled",
};

const LIVE_TRACKABLE_STATUSES = ["picked_up", "out_for_delivery"];

const DELIVERIES_PAGE_SIZE = 10;
const NOTIFICATIONS_PAGE_SIZE = 15;

export default function CustomerDashboard() {
  const { customer, token, logout, updateCustomer } = useCustomerAuth();
  const { theme, toggleTheme } = useTheme();
  const [deliveries, setDeliveries] = useState([]);
  const [deliveriesVisibleCount, setDeliveriesVisibleCount] = useState(DELIVERIES_PAGE_SIZE);
  const [notifications, setNotifications] = useState([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [activeView, setActiveView] = useState("orders"); // "orders" | "shop" | "addresses" | "privacy" | "profile"
  const [expandedId, setExpandedId] = useState(null);
  const [error, setError] = useState(null);
  const [pushStatus, setPushStatus] = useState("idle");
  const [isOffline, setIsOffline] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState(null);
  const [pendingActionSyncMsg, setPendingActionSyncMsg] = useState(null);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const notificationsLimitRef = React.useRef(NOTIFICATIONS_PAGE_SIZE);
  const [notificationsHasMore, setNotificationsHasMore] = useState(false);

  useEffect(() => {
    if (customer?.id) {
      setActiveCustomer(customer.id);
      writeSyncContext({ userId: customer.id, token, role: "customer", apiBaseUrl: API_BASE_URL });
    }
    loadDeliveries();
    loadNotifications();
    const intervalId = setInterval(loadNotifications, 10000);
    const stopActionSync = startCustomerActionAutoSync(token, (result) => {
      if (result.syncedCount > 0) {
        setPendingActionSyncMsg(
          `Synced ${result.syncedCount} action(s) that were queued while offline.`
        );
        loadDeliveries();
      }
      if (result.failed.length > 0) {
        setPendingActionSyncMsg(
          `${result.failed.length} queued action(s) couldn't be applied: ${result.failed[0].message}`
        );
      }
    });
    return () => {
      clearInterval(intervalId);
      stopActionSync();
    };
  }, []);

  useEffect(() => {
    if (!("Notification" in window)) {
      setPushStatus("unsupported");
    } else if (Notification.permission === "granted") {
      setPushStatus("enabled");
    } else if (Notification.permission === "denied") {
      setPushStatus("denied");
    }
  }, []);

  async function loadDeliveries() {
    try {
      const data = await fetchMyCustomerDeliveries(token);
      setDeliveries(data);
      setError(null);
      setIsOffline(false);
      await cacheCustomerDeliveries(data);
    } catch (err) {
      // Fall back to cached data instead of leaving the customer with
      // an empty screen when they lose connectivity.
      try {
        const cached = await getCachedCustomerDeliveries();
        const lastSynced = await getCustomerLastSyncedAt();
        setDeliveries(cached);
        setIsOffline(true);
        setLastSyncedAt(lastSynced);
        setError(cached.length === 0 ? err.message : null);
      } catch (cacheErr) {
        setError(err.message);
      }
    }
  }

  async function loadNotifications() {
    try {
      const data = await fetchMyCustomerNotifications(token, { limit: notificationsLimitRef.current, offset: 0 });
      setNotifications(data);
      setNotificationsHasMore(data.length === notificationsLimitRef.current);
    } catch (err) {
      console.warn("Could not load notifications:", err.message);
    }
  }

  function handleLoadMoreNotifications() {
    notificationsLimitRef.current += NOTIFICATIONS_PAGE_SIZE;
    loadNotifications();
  }

  async function handleMarkAllRead() {
    await markAllCustomerNotificationsRead(token);
    await loadNotifications();
  }

  async function handleDeleteNotification(id) {
    await deleteCustomerNotification(token, id);
    await loadNotifications();
  }

  async function handleClearReadNotifications() {
    await clearCustomerNotifications(token, true);
    await loadNotifications();
  }

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
      const { public_key: vapidPublicKey } = await fetchVapidPublicKey(token);

      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });
      }

      await subscribeToPush(token, subscription.toJSON());
      setPushStatus("enabled");
    } catch (err) {
      console.warn("Push enable failed:", err.message);
      setPushStatus("idle");
      setError("Couldn't enable push notifications: " + err.message);
    }
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const navLinks = [
    { key: "orders", label: "My Orders", icon: "\u25A4" },
    { key: "shop", label: "Shop", icon: "\u25A3" },
    { key: "subscriptions", label: "Recurring Orders", icon: "\u27F3" },
    { key: "addresses", label: "Addresses", icon: "\u2691" },
    { key: "support", label: "Support", icon: "\u2753" },
    { key: "invoices", label: "Invoices", icon: "\u2637" },
    { key: "privacy", label: "Privacy", icon: "\u26BF" },
    { key: "profile", label: "Profile", icon: "\u25C9" },
  ];

  function handleNavigate(key) {
    setActiveView(key);
    setIsMobileNavOpen(false); // close the drawer after picking a page, on mobile
    setShowNotifications(false); // close the notifications panel too, so it doesn't linger on the new page
  }

  return (
    <div className="app-shell">
      <div className="mobile-topbar">
        <span className="mobile-topbar-brand">Delivery Sync</span>
        <button
          className="mobile-menu-btn"
          onClick={() => setIsMobileNavOpen(!isMobileNavOpen)}
          aria-label="Toggle menu"
        >
          {isMobileNavOpen ? "\u2715" : "\u2630"}
        </button>
      </div>

      {isMobileNavOpen && (
        <div className="sidebar-overlay" onClick={() => setIsMobileNavOpen(false)} />
      )}

      <div className={`sidebar ${isMobileNavOpen ? "mobile-open" : ""}`}>
        <div className="sidebar-brand">Delivery Sync</div>
        <div className="sidebar-section-label">Customer</div>

        {navLinks.map((link) => (
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
            <strong>{customer.name}</strong>
            Customer
          </div>
          {pushStatus !== "enabled" && pushStatus !== "unsupported" && (
            <button className="btn sidebar-action-btn" onClick={handleEnablePush} disabled={pushStatus === "enabling"}>
              {pushStatus === "enabling" ? "Enabling..." : pushStatus === "denied" ? "Notifications Blocked" : "🔔 Enable Push"}
            </button>
          )}
          <button className="btn sidebar-action-btn" onClick={() => setShowNotifications(!showNotifications)}>
            🔔 Notifications{unreadCount > 0 && ` (${unreadCount})`}
          </button>
          <button className="btn sidebar-action-btn" onClick={toggleTheme}>
            {theme === "dark" ? "☀ Light Mode" : "☾ Dark Mode"}
          </button>
          <button className="btn sidebar-action-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </div>

      <div className="main-content">

      {!customer.email_verified && (
        <VerificationBanner onResend={() => customerResendVerificationRequest(token)} />
      )}

      {activeView === "shop" && (
        <div>
          <Storefront token={token} onOrderPlaced={() => { loadDeliveries(); loadNotifications(); setActiveView("orders"); }} />
        </div>
      )}

      {activeView === "subscriptions" && (
        <div>
          <SubscriptionManager token={token} />
        </div>
      )}

      {activeView === "addresses" && (
        <div>
          <AddressBook token={token} />
        </div>
      )}

      {activeView === "support" && (
        <div>
          <CustomerSupportPanel />
        </div>
      )}

      {activeView === "invoices" && (
        <div>
          <CustomerInvoicesPanel />
        </div>
      )}

      {activeView === "privacy" && (
        <div>
          <PrivacyPanel token={token} onAccountDeleted={logout} />
        </div>
      )}

      {activeView === "profile" && (
        <div>
          <ProfilePanel token={token} customer={customer} />
        </div>
      )}

      {showNotifications && (
        <>
          <div className="notifications-overlay" onClick={() => setShowNotifications(false)} />
          <div className="notifications-panel">
            <div className="notifications-panel-header">
              <span className="notifications-panel-title">Notifications</span>
              <div className="notifications-panel-actions">
                {unreadCount > 0 && (
                  <button className="btn" onClick={handleMarkAllRead} style={{ fontSize: "12px", padding: "4px 8px" }}>
                    Mark all read
                  </button>
                )}
                {notifications.some((n) => n.is_read) && (
                  <button className="btn" onClick={handleClearReadNotifications} style={{ fontSize: "12px", padding: "4px 8px" }}>
                    Clear read
                  </button>
                )}
                <button
                  className="notifications-panel-close"
                  onClick={() => setShowNotifications(false)}
                  aria-label="Close notifications"
                  title="Close"
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="notifications-panel-body">
              {notifications.length === 0 && (
                <p className="notifications-panel-empty">No notifications yet.</p>
              )}
              {notifications.map((n) => (
              <div
                key={n.id}
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--border-color)",
                  opacity: n.is_read ? 0.6 : 1,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  gap: "8px",
                }}
              >
                <div>
                  <div style={{ fontSize: "13px" }}>{n.message}</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                    {new Date(n.created_at).toLocaleString()}
                  </div>
                </div>
                <button
                  className="btn"
                  style={{ fontSize: "11px", padding: "2px 6px", flexShrink: 0 }}
                  onClick={() => handleDeleteNotification(n.id)}
                  title="Delete this notification"
                >
                  🗑
                </button>
              </div>
              ))}
              {notificationsHasMore && (
                <button
                  className="btn"
                  style={{ fontSize: "12px", padding: "4px 8px", marginTop: "8px", width: "100%" }}
                  onClick={handleLoadMoreNotifications}
                >
                  Load more
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {activeView === "orders" && (
      <div style={{ maxWidth: "700px" }}>
        <h2 className="page-title">My Orders</h2>

        {isOffline && (
          <div className="connectivity-banner offline" style={{ marginBottom: "16px" }}>
            Offline — showing your last synced orders{lastSyncedAt ? ` from ${new Date(lastSyncedAt).toLocaleString()}` : ""}
          </div>
        )}

        {pendingActionSyncMsg && (
          <p style={{ fontSize: "12.5px", color: "var(--accent)", marginBottom: "12px" }}>
            {pendingActionSyncMsg}
          </p>
        )}

        {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

        {deliveries.length === 0 && (
          <div className="empty-state" style={{ marginBottom: "16px" }}>
            <div className="empty-state-icon">📦</div>
            <div className="empty-state-title">No orders yet</div>
            <div className="empty-state-body">
              Orders placed under this email address show up here automatically.
              Head to Shop to place your first one.
            </div>
          </div>
        )}

        <ClaimOrderPanel token={token} onLinked={loadDeliveries} />

        {deliveries.slice(0, deliveriesVisibleCount).map((delivery) => (
          <CustomerDeliveryCard
            key={delivery.id}
            delivery={delivery}
            token={token}
            isExpanded={expandedId === delivery.id}
            onToggle={() => setExpandedId(expandedId === delivery.id ? null : delivery.id)}
            onChanged={loadDeliveries}
          />
        ))}

        {deliveries.length > deliveriesVisibleCount && (
          <button
            className="btn"
            style={{ marginTop: "8px" }}
            onClick={() => setDeliveriesVisibleCount((prev) => prev + DELIVERIES_PAGE_SIZE)}
          >
            Load more ({deliveries.length - deliveriesVisibleCount} more)
          </button>
        )}
      </div>
      )}

      </div>
    </div>
  );
}

function ProfilePanel({ token, customer }) {
  const { updateCustomer } = useCustomerAuth();

  const [name, setName] = useState(customer.name);
  const [email, setEmail] = useState(customer.email);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState(null);
  const [profileSuccess, setProfileSuccess] = useState(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState(null);
  const [passwordSuccess, setPasswordSuccess] = useState(null);

  const [newPasswordToSet, setNewPasswordToSet] = useState("");
  const [isSettingPassword, setIsSettingPassword] = useState(false);
  const [setPasswordFormError, setSetPasswordFormError] = useState(null);
  const [setPasswordFormSuccess, setSetPasswordFormSuccess] = useState(null);

  async function handleSaveProfile(e) {
    e.preventDefault();
    setProfileError(null);
    setProfileSuccess(null);
    setIsSavingProfile(true);
    try {
      const updated = await updateMyCustomerProfile(token, { name: name.trim(), email: email.trim() });
      updateCustomer({ name: updated.name, email: updated.email });
      setProfileSuccess("Profile updated.");
    } catch (err) {
      setProfileError(err.message);
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleChangePassword(e) {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);
    setIsChangingPassword(true);
    try {
      await changeMyCustomerPassword(token, currentPassword, newPassword);
      setPasswordSuccess("Password changed.");
      setCurrentPassword("");
      setNewPassword("");
    } catch (err) {
      setPasswordError(err.message);
    } finally {
      setIsChangingPassword(false);
    }
  }

  async function handleSetPassword(e) {
    e.preventDefault();
    setSetPasswordFormError(null);
    setSetPasswordFormSuccess(null);
    setIsSettingPassword(true);
    try {
      await setMyCustomerPassword(token, newPasswordToSet);
      setSetPasswordFormSuccess("Password set. You can now log in with it, in addition to Google Sign-In.");
      setNewPasswordToSet("");
      updateCustomer({ has_usable_password: true });
    } catch (err) {
      setSetPasswordFormError(err.message);
    } finally {
      setIsSettingPassword(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px", maxWidth: "500px" }}>
      <div className="card">
        <strong style={{ fontSize: "13.5px" }}>Profile</strong>
        <form onSubmit={handleSaveProfile} style={{ marginTop: "12px" }}>
          <div className="auth-field">
            <label>Name</label>
            <input className="input" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Email</label>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          {profileError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{profileError}</p>}
          {profileSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{profileSuccess}</p>}
          <button type="submit" className="btn btn-primary" disabled={isSavingProfile}>
            {isSavingProfile ? "Saving..." : "Save Changes"}
          </button>
        </form>
      </div>

      {customer.has_usable_password === false ? (
        <div className="card">
          <strong style={{ fontSize: "13.5px" }}>Set a Password</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px", marginBottom: "12px" }}>
            Your account currently only logs in via Google Sign-In. Add a password so you still
            have a way in if Google Sign-In is ever unavailable.
          </p>
          <form onSubmit={handleSetPassword}>
            <div className="auth-field">
              <label>New Password</label>
              <PasswordInput className="input" value={newPasswordToSet} onChange={(e) => setNewPasswordToSet(e.target.value)} required minLength={6} />
            </div>
            {setPasswordFormError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{setPasswordFormError}</p>}
            {setPasswordFormSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{setPasswordFormSuccess}</p>}
            <button type="submit" className="btn btn-primary" disabled={isSettingPassword}>
              {isSettingPassword ? "Setting..." : "Set Password"}
            </button>
          </form>
        </div>
      ) : (
        <div className="card">
          <strong style={{ fontSize: "13.5px" }}>Change Password</strong>
          <form onSubmit={handleChangePassword} style={{ marginTop: "12px" }}>
            <div className="auth-field">
              <label>Current Password</label>
              <PasswordInput className="input" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
            </div>
            <div className="auth-field">
              <label>New Password</label>
              <PasswordInput className="input" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required minLength={6} />
            </div>
            {passwordError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{passwordError}</p>}
            {passwordSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{passwordSuccess}</p>}
            <button type="submit" className="btn btn-primary" disabled={isChangingPassword}>
              {isChangingPassword ? "Changing..." : "Change Password"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function PrivacyPanel({ token, onAccountDeleted }) {
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState(null);

  const [showDeleteForm, setShowDeleteForm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleExport() {
    setError(null);
    setIsExporting(true);
    try {
      const blob = await exportCustomerData(token);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `my_data_export_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsExporting(false);
    }
  }

  async function handleDelete(e) {
    e.preventDefault();
    setError(null);
    setIsDeleting(true);
    try {
      await deleteCustomerAccount(token, deletePassword);
      onAccountDeleted();
    } catch (err) {
      setError(err.message);
      setIsDeleting(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: "500px" }}>
      <strong style={{ fontSize: "13.5px" }}>Your Data & Privacy</strong>

      <div style={{ marginTop: "14px" }}>
        <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "4px" }}>Download your data</div>
        <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "8px" }}>
          Get a JSON file with everything tied to your account: profile, addresses,
          orders, deliveries, notifications, and reviews.
        </p>
        <button className="btn" onClick={handleExport} disabled={isExporting}>
          {isExporting ? "Preparing download..." : "⬇ Download my data"}
        </button>
      </div>

      <div style={{ marginTop: "20px", paddingTop: "16px", borderTop: "1px solid var(--border-color)" }}>
        <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "4px", color: "var(--danger)" }}>Delete account</div>
        <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "8px" }}>
          Permanently deletes your account, saved addresses, cart, and notifications.
          Past orders are kept by the store(s) you ordered from in anonymized form,
          for their own transaction records.
        </p>

        {!showDeleteForm && (
          <button className="btn-danger-outline" onClick={() => setShowDeleteForm(true)}>
            Delete my account
          </button>
        )}

        {showDeleteForm && (
          <form onSubmit={handleDelete}>
            <div className="auth-field">
              <label>Confirm your password to delete your account</label>
              <PasswordInput
                className="input"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                style={{ width: "100%" }}
                required
                autoFocus
              />
            </div>
            {error && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</p>}
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="submit" className="btn-danger-outline" disabled={isDeleting}>
                {isDeleting ? "Deleting..." : "Permanently delete my account"}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setShowDeleteForm(false);
                  setDeletePassword("");
                  setError(null);
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {!showDeleteForm && error && <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "8px" }}>{error}</p>}
      </div>
    </div>
  );
}

function AddressBook({ token }) {
  const [addresses, setAddresses] = useState([]);
  const [isAdding, setIsAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [addressLine, setAddressLine] = useState("");
  const [city, setCity] = useState("");
  const [phone, setPhone] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const data = await fetchMyCustomerAddresses(token);
      setAddresses(data);
    } catch (err) {
      console.warn("Could not load addresses:", err.message);
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    setError(null);
    try {
      await addCustomerAddress(token, {
        label: label.trim(),
        address_line: addressLine.trim(),
        city: city.trim() || null,
        phone: phone.trim() || null,
        is_default: isDefault,
      });
      setLabel("");
      setAddressLine("");
      setCity("");
      setPhone("");
      setIsDefault(false);
      setIsAdding(false);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    try {
      await deleteCustomerAddress(token, id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="card" style={{ maxWidth: "500px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
        <strong style={{ fontSize: "13.5px" }}>Saved Addresses</strong>
        <button className="btn" style={{ fontSize: "12px", padding: "4px 8px" }} onClick={() => setIsAdding(!isAdding)}>
          {isAdding ? "Cancel" : "+ Add"}
        </button>
      </div>

      {addresses.length === 0 && !isAdding && (
        <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>No saved addresses yet.</p>
      )}

      {addresses.map((addr) => (
        <div
          key={addr.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            padding: "8px 0",
            borderBottom: "1px solid var(--border-color)",
          }}
        >
          <div>
            <div style={{ fontSize: "13px", fontWeight: 600 }}>
              {addr.label} {addr.is_default && <span style={{ color: "var(--accent)", fontSize: "11px" }}>(Default)</span>}
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
              {addr.address_line}{addr.city && `, ${addr.city}`}
            </div>
            {addr.phone && <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{addr.phone}</div>}
          </div>
          <button className="btn" style={{ fontSize: "11px", padding: "3px 7px" }} onClick={() => handleDelete(addr.id)}>
            Delete
          </button>
        </div>
      ))}

      {isAdding && (
        <form onSubmit={handleAdd} style={{ marginTop: "12px" }}>
          <div className="auth-field">
            <label>Label (e.g. Home, Work)</label>
            <input className="input" type="text" value={label} onChange={(e) => setLabel(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Address</label>
            <input className="input" type="text" value={addressLine} onChange={(e) => setAddressLine(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>City</label>
            <input className="input" type="text" value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
          <div className="auth-field">
            <label>Phone</label>
            <input className="input" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <label style={{ fontSize: "12.5px", display: "flex", alignItems: "center", gap: "6px", marginBottom: "10px" }}>
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            Set as default
          </label>
          {error && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</p>}
          <button type="submit" className="btn btn-primary">Save Address</button>
        </form>
      )}
    </div>
  );
}

function ClaimOrderPanel({ token, onLinked }) {
  const [isOpen, setIsOpen] = useState(false);
  const [orderId, setOrderId] = useState("");
  const [phone, setPhone] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setIsSubmitting(true);
    try {
      await claimCustomerOrder(token, orderId.trim(), phone.trim());
      setSuccess(true);
      setOrderId("");
      setPhone("");
      await onLinked();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "20px" }}>
      <div
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <strong style={{ fontSize: "13.5px" }}>Don't see an order? Link it manually</strong>
        <span style={{ fontSize: "12px", color: "var(--accent)" }}>{isOpen ? "Hide" : "Link an order"}</span>
      </div>

      {isOpen && (
        <div style={{ marginTop: "14px" }}>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "12px" }}>
            If an order was placed under a different email than the one
            you signed up with, enter its Order ID and the phone number
            on file for it to link it to your account.
          </p>
          <form onSubmit={handleSubmit}>
            <div className="auth-field">
              <label>Order ID</label>
              <input className="input" type="text" value={orderId} onChange={(e) => setOrderId(e.target.value)} required />
            </div>
            <div className="auth-field">
              <label>Phone number on the order</label>
              <input className="input" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required />
            </div>
            {error && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</p>}
            {success && <p style={{ color: "var(--accent)", fontSize: "12px" }}>Order linked to your account.</p>}
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? "Linking..." : "Link order"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function CustomerDeliveryCard({ delivery, token, isExpanded, onToggle, onChanged }) {
  const [history, setHistory] = useState([]);
  const [feedback, setFeedback] = useState(null);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isReordering, setIsReordering] = useState(false);
  const [reviewableItems, setReviewableItems] = useState([]);
  const [refundInfo, setRefundInfo] = useState(null);
  const [returnRequest, setReturnRequest] = useState(null);
  const [showReturnForm, setShowReturnForm] = useState(false);
  const [returnType, setReturnType] = useState("return");
  const [returnReason, setReturnReason] = useState("");
  const [isSubmittingReturn, setIsSubmittingReturn] = useState(false);
  const [returnError, setReturnError] = useState(null);
  const [podDetail, setPodDetail] = useState(null);

  useEffect(() => {
    if (isExpanded) loadDetails();
  }, [isExpanded]);

  async function loadDetails() {
    try {
      const [historyData, feedbackData] = await Promise.all([
        fetchMyCustomerDeliveryHistory(token, delivery.id),
        fetchMyCustomerDeliveryFeedback(token, delivery.id),
      ]);
      setHistory(historyData);
      setFeedback(feedbackData);
    } catch (err) {
      console.warn("Could not load order details:", err.message);
    }
    if (delivery.status === "delivered") {
      try {
        setPodDetail(await fetchMyCustomerDeliveryPod(token, delivery.id));
      } catch (err) {
        console.warn("Could not load proof of delivery:", err.message);
      }
    }
    if (delivery.status === "delivered") {
      try {
        setReviewableItems(await fetchReviewableItems(token, delivery.id));
      } catch (err) {
        console.warn("Could not load reviewable items:", err.message);
      }
    }
    if (delivery.status === "cancelled") {
      try {
        const orders = await fetchMyOrders(token, { deliveryId: delivery.id });
        const match = orders.find((o) => o.delivery_id === delivery.id);
        if (match && match.refund_status) setRefundInfo(match);
      } catch (err) {
        console.warn("Could not load refund status:", err.message);
      }
    }
    if (delivery.status === "delivered") {
      try {
        const requests = await fetchMyReturnRequests(token);
        const match = requests.find((r) => r.delivery_id === delivery.id && r.status !== "rejected");
        setReturnRequest(match || null);
      } catch (err) {
        console.warn("Could not load return request status:", err.message);
      }
    }
  }

  async function handleSubmitReturnRequest(e) {
    e.preventDefault();
    if (!returnReason.trim()) {
      setReturnError("Please describe the reason.");
      return;
    }
    setIsSubmittingReturn(true);
    setReturnError(null);
    try {
      const created = await createReturnRequest(token, delivery.id, returnType, returnReason.trim());
      setReturnRequest(created);
      setShowReturnForm(false);
      setReturnReason("");
    } catch (err) {
      setReturnError(err.message);
    } finally {
      setIsSubmittingReturn(false);
    }
  }

  async function handleReviewSubmit(item, itemRating, itemComment) {
    await submitProductReview(token, item.product_id, item.order_id, itemRating, itemComment);
    setReviewableItems(await fetchReviewableItems(token, delivery.id));
  }

  async function handleSubmitFeedback(e) {
    e.preventDefault();
    if (rating === 0) {
      setFeedbackError("Please pick a star rating.");
      return;
    }
    setIsSubmitting(true);
    setFeedbackError(null);
    try {
      await submitDeliveryFeedback(delivery.id, rating, comment.trim());
      await loadDetails();
    } catch (err) {
      setFeedbackError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!window.confirm(`Cancel order ${delivery.order_id}? This can't be undone.`)) return;
    setIsCancelling(true);
    setActionError(null);
    try {
      await cancelCustomerDelivery(token, delivery.id);
      await onChanged();
    } catch (err) {
      if (err instanceof TypeError || !navigator.onLine) {
        // Offline (fetch() throws TypeError when the network is
        // unreachable) — queue it instead of showing a hard error, so
        // it replays automatically once connectivity returns.
        await queueCustomerAction("cancel", delivery.id, delivery.order_id);
        setActionError("You're offline — this cancellation is queued and will go through once you're back online.");
      } else {
        setActionError(err.message);
      }
    } finally {
      setIsCancelling(false);
    }
  }

  async function handleReorder() {
    setIsReordering(true);
    setActionError(null);
    try {
      await reorderCustomerDelivery(token, delivery.id);
      await onChanged();
    } catch (err) {
      if (err instanceof TypeError || !navigator.onLine) {
        await queueCustomerAction("reorder", delivery.id, delivery.order_id);
        setActionError("You're offline — this reorder is queued and will be placed once you're back online.");
      } else {
        setActionError(err.message);
      }
    } finally {
      setIsReordering(false);
    }
  }

  const canCancel = delivery.status === "picked_up" || delivery.status === "pending";
  const canReorder = ["delivered", "cancelled", "failed_attempt"].includes(delivery.status);
  const isLiveTrackable = LIVE_TRACKABLE_STATUSES.includes(delivery.status);

  return (
    <div className="delivery-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="delivery-card-order-id">{delivery.order_id}</span>
        <StatusBadge status={delivery.status} />
      </div>
      {(delivery.sla_status === "at_risk" || delivery.sla_status === "breached" || delivery.sla_status === "missed") && (
        <div style={{ fontSize: "12px", color: "var(--warning, #b45309)", fontWeight: 600, marginTop: "4px" }}>
          Running a bit behind schedule
        </div>
      )}
      <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginTop: "6px" }}>
        Last updated: {new Date(delivery.updated_at).toLocaleString()}
        {delivery.expected_by && ` · Expected by ${new Date(delivery.expected_by).toLocaleString()}`}
      </div>

      <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
        <button className="btn-info-outline" onClick={onToggle}>
          {isExpanded ? "Hide Details" : "View Details"}
        </button>
        {canCancel && (
          <button className="btn" style={{ color: "var(--danger)" }} onClick={handleCancel} disabled={isCancelling}>
            {isCancelling ? "Cancelling..." : "Cancel Order"}
          </button>
        )}
        {canReorder && (
          <button className="btn" onClick={handleReorder} disabled={isReordering}>
            {isReordering ? "Placing..." : "Reorder"}
          </button>
        )}
        {delivery.status === "delivered" && !returnRequest && (
          <button className="btn" onClick={() => setShowReturnForm(!showReturnForm)}>
            {showReturnForm ? "Cancel" : "Return / Exchange"}
          </button>
        )}
      </div>

      {showReturnForm && (
        <form onSubmit={handleSubmitReturnRequest} className="card" style={{ marginTop: "10px", padding: "12px" }}>
          <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
            <button
              type="button"
              className="btn"
              style={returnType === "return" ? { background: "var(--accent)", color: "white" } : undefined}
              onClick={() => setReturnType("return")}
            >
              Return for refund
            </button>
            <button
              type="button"
              className="btn"
              style={returnType === "exchange" ? { background: "var(--accent)", color: "white" } : undefined}
              onClick={() => setReturnType("exchange")}
            >
              Exchange
            </button>
          </div>
          <div className="auth-field">
            <label>Reason</label>
            <input
              className="input"
              type="text"
              value={returnReason}
              onChange={(e) => setReturnReason(e.target.value)}
              placeholder="e.g. wrong item, damaged on arrival"
              required
            />
          </div>
          {returnError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{returnError}</p>}
          <button type="submit" className="btn btn-primary" disabled={isSubmittingReturn}>
            {isSubmittingReturn ? "Submitting..." : "Submit Request"}
          </button>
        </form>
      )}

      {returnRequest && (
        <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "8px" }}>
          {returnRequest.request_type === "return" ? "Return" : "Exchange"} request:{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            {returnRequest.status === "requested" && "Awaiting review"}
            {returnRequest.status === "approved" && "Approved — pickup scheduled"}
            {returnRequest.status === "completed" && (returnRequest.request_type === "return" ? "Completed — refund issued" : "Completed — replacement on the way")}
          </strong>
        </p>
      )}
      {actionError && <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "6px" }}>{actionError}</p>}
      {refundInfo && refundInfo.refund_status === "refunded" && (
        <p style={{ color: "var(--accent)", fontSize: "12px", marginTop: "6px" }}>
          Refund issued{refundInfo.is_test_mode_payment ? " (test mode — no real payment was ever taken)" : ""} on{" "}
          {new Date(refundInfo.refunded_at).toLocaleString()}.
        </p>
      )}
      {refundInfo && refundInfo.refund_status === "failed" && (
        <p style={{ color: "var(--danger)", fontSize: "12px", marginTop: "6px" }}>
          Your order was cancelled, but the refund couldn't be processed automatically — please contact support.
        </p>
      )}

      {isExpanded && (
        <div style={{ marginTop: "14px" }}>
          {isLiveTrackable && (
            <div style={{ marginBottom: "14px" }}>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "6px" }}>
                Live Location
              </div>
              <LiveTrackingMap token={token} deliveryId={delivery.id} />
            </div>
          )}

          {delivery.proof_of_delivery && (
            <div style={{ marginBottom: "14px" }}>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "6px" }}>
                Proof of Delivery
              </div>
              <img
                src={delivery.proof_of_delivery}
                alt="Proof of delivery"
                style={{ maxWidth: "100%", maxHeight: "160px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)" }}
              />
              {podDetail && (podDetail.recipient_name || podDetail.notes) && (
                <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginTop: "6px" }}>
                  {podDetail.recipient_name && <div>Received by: {podDetail.recipient_name}</div>}
                  {podDetail.otp_verified && <div>Verified with a one-time code</div>}
                  {podDetail.notes && <div>{podDetail.notes}</div>}
                </div>
              )}
            </div>
          )}

          {!["delivered", "cancelled"].includes(delivery.status) && (
            <div style={{ marginBottom: "14px" }}>
              <div style={{ fontSize: "12.5px", fontWeight: 600, marginBottom: "8px" }}>Message the delivery team</div>
              <CustomerDeliveryMessages deliveryId={delivery.id} />
            </div>
          )}

          <div style={{ fontSize: "12.5px", fontWeight: 600, marginBottom: "8px" }}>Timeline</div>
          {history.map((entry, i) => (
            <div key={i} style={{ borderLeft: "3px solid var(--accent)", paddingLeft: "10px", marginBottom: "8px" }}>
              <div style={{ fontSize: "12.5px", fontWeight: 600 }}>
                {entry.old_status
                  ? `${STATUS_LABELS[entry.old_status] || entry.old_status} → ${STATUS_LABELS[entry.new_status] || entry.new_status}`
                  : "Order Confirmed"}
              </div>
              <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                {new Date(entry.changed_at).toLocaleString()}
              </div>
            </div>
          ))}

          {delivery.status === "delivered" && (
            <div style={{ marginTop: "14px" }}>
              <div style={{ fontSize: "12.5px", fontWeight: 600, marginBottom: "8px" }}>
                How was your delivery?
              </div>
              {feedback ? (
                <div>
                  <div style={{ fontSize: "18px", letterSpacing: "2px" }}>
                    {"★".repeat(feedback.rating)}
                    <span style={{ color: "var(--text-muted)" }}>{"★".repeat(5 - feedback.rating)}</span>
                  </div>
                  {feedback.comment && (
                    <p style={{ fontSize: "12.5px", color: "var(--text-secondary)" }}>"{feedback.comment}"</p>
                  )}
                </div>
              ) : (
                <form onSubmit={handleSubmitFeedback}>
                  <div style={{ fontSize: "22px", marginBottom: "8px" }}>
                    {[1, 2, 3, 4, 5].map((star) => (
                      <span
                        key={star}
                        onClick={() => setRating(star)}
                        style={{ cursor: "pointer", color: star <= rating ? "var(--accent)" : "var(--text-muted)" }}
                      >
                        ★
                      </span>
                    ))}
                  </div>
                  <textarea
                    className="input"
                    placeholder="Optional comment..."
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    style={{ width: "100%", minHeight: "50px", marginBottom: "8px" }}
                  />
                  {feedbackError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{feedbackError}</p>}
                  <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? "Submitting..." : "Submit Feedback"}
                  </button>
                </form>
              )}
            </div>
          )}

          {delivery.status === "delivered" && reviewableItems.length > 0 && (
            <div style={{ marginTop: "18px" }}>
              <div style={{ fontSize: "12.5px", fontWeight: 600, marginBottom: "8px" }}>
                Rate your products
              </div>
              {reviewableItems.map((item) => (
                <ProductReviewRow key={item.product_id} item={item} onSubmit={handleReviewSubmit} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ProductReviewRow({ item, onSubmit }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (rating === 0) {
      setError("Please pick a star rating.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit(item, rating, comment.trim());
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div style={{ borderTop: "1px solid var(--border-color)", padding: "10px 0" }}>
      <div style={{ fontSize: "12.5px", marginBottom: "6px" }}>
        {item.product_name} {item.quantity > 1 && <span style={{ color: "var(--text-secondary)" }}>× {item.quantity}</span>}
      </div>
      {item.already_reviewed ? (
        <div>
          <div style={{ fontSize: "16px", letterSpacing: "2px" }}>
            {"★".repeat(item.my_review.rating)}
            <span style={{ color: "var(--text-muted)" }}>{"★".repeat(5 - item.my_review.rating)}</span>
          </div>
          {item.my_review.comment && (
            <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>"{item.my_review.comment}"</p>
          )}
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <div style={{ fontSize: "18px", marginBottom: "6px" }}>
            {[1, 2, 3, 4, 5].map((star) => (
              <span
                key={star}
                onClick={() => setRating(star)}
                style={{ cursor: "pointer", color: star <= rating ? "var(--accent)" : "var(--text-muted)" }}
              >
                ★
              </span>
            ))}
          </div>
          <textarea
            className="input"
            placeholder="Optional comment about the product..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            style={{ width: "100%", minHeight: "40px", marginBottom: "6px" }}
          />
          {error && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</p>}
          <button type="submit" className="btn" style={{ fontSize: "12px" }} disabled={isSubmitting}>
            {isSubmitting ? "Submitting..." : "Submit Review"}
          </button>
        </form>
      )}
    </div>
  );
}
