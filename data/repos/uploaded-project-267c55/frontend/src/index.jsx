import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/theme.css";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);

// Register the service worker for PWA installability/offline app-shell
// loading (see public/sw.js). Guarded by a feature check since older
// browsers don't support service workers at all — this simply does
// nothing on those instead of throwing an error.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.warn("Service worker registration failed:", error);
    });
  });

  // The service worker posts this after a real Background Sync event
  // completes (see public/sw.js's runBackgroundSync) — including syncs
  // that happened while every tab was closed. Dispatched as a DOM event
  // rather than called directly, since this file sits outside the React
  // tree (before ToastProvider mounts) — App.jsx listens for it and
  // shows a real toast once the tree is up.
  navigator.serviceWorker.addEventListener("message", (event) => {
    if (event.data?.type === "background-sync-complete" && event.data.syncedCount > 0) {
      window.dispatchEvent(new CustomEvent("background-sync-complete", { detail: event.data }));
    }
  });
}
