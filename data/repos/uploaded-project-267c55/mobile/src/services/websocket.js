/**
 * Thin wrapper around React Native's built-in `WebSocket` global (part
 * of React Native core — no extra native dependency needed, same as
 * the browser's native WebSocket the web app's own
 * frontend/src/services/websocket.js wraps) with automatic
 * reconnection — deliberately ported from that file almost verbatim,
 * not reinvented, since it's solving the exact same problem (a flaky
 * connection should retry, not just die silently) with an interface
 * (onopen/onmessage/onclose/onerror, .close()) React Native's
 * WebSocket implements identically to a browser's.
 *
 * Reconnects with exponential backoff (1s, 2s, 4s... capped at 15s)
 * so a brief network blip (elevator, tunnel, a moment of no signal —
 * far more common on mobile than in a desktop browser) retries
 * quickly at first without hammering the server if it stays down.
 *
 * Derives ws:// or wss:// from API_BASE_URL automatically.
 *
 * Usage:
 *   const socket = connectWebSocket(`/ws/deliveries/${id}/messages?token=${token}`, {
 *     onMessage: (data) => { ... },
 *   });
 *   // later, e.g. on screen unmount: socket.close();
 */
import { API_BASE_URL } from "./api";

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
