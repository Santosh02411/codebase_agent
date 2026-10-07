import { API_BASE_URL } from "./api";

/**
 * Thin wrapper around the browser's native WebSocket with automatic
 * reconnection — a plain `new WebSocket(...)` just dies silently on any
 * network blip (phone goes through a tunnel, laptop sleeps, dev server
 * restarts) and never comes back, which would make "live updates" less
 * reliable than the polling it's replacing. Reconnects with exponential
 * backoff (1s, 2s, 4s... capped at 15s) so a flaky connection retries
 * quickly at first without hammering the server if it stays down.
 *
 * Derives ws:// or wss:// from API_BASE_URL automatically, so this
 * doesn't need its own separate configuration.
 *
 * Usage:
 *   const socket = connectWebSocket("/ws/deliveries/abc/messages?token=...", {
 *     onMessage: (data) => { ... },
 *   });
 *   // later: socket.close();
 */
export function connectWebSocket(path, { onMessage, onOpen, onClose } = {}) {
  const wsBase = API_BASE_URL.replace(/^http/, "ws");
  const url = `${wsBase}${path}`;

  let socket = null;
  let closedByCaller = false;
  let reconnectDelayMs = 1000;
  let reconnectTimer = null;

  function connect() {
    socket = new WebSocket(url);

    socket.onopen = () => {
      reconnectDelayMs = 1000; // reset backoff on a successful connection
      if (onOpen) onOpen();
    };

    socket.onmessage = (event) => {
      if (!onMessage) return;
      try {
        onMessage(JSON.parse(event.data));
      } catch (err) {
        console.warn("Malformed WebSocket message:", err);
      }
    };

    socket.onclose = () => {
      if (onClose) onClose();
      if (closedByCaller) return;
      reconnectTimer = setTimeout(() => {
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, 15000);
        connect();
      }, reconnectDelayMs);
    };

    socket.onerror = () => {
      // onclose always fires right after onerror for a WebSocket — the
      // reconnect logic above already handles it, nothing extra needed here.
    };
  }

  connect();

  return {
    close() {
      closedByCaller = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) socket.close();
    },
  };
}
