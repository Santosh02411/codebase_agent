// Shared by both the customer push-subscribe flow (CustomerDashboard.jsx)
// and the staff push-subscribe flow (Sidebar.jsx) — the browser's
// PushManager.subscribe() needs the VAPID public key as a raw
// Uint8Array, not the base64url string the backend hands back.
export function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}
