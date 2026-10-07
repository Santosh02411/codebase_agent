import { useState, useEffect } from "react";

/**
 * Tracks whether the browser currently has internet connectivity.
 * Uses the browser's built-in online/offline events — no external library
 * needed.
 *
 * Note: `navigator.onLine` tells you if the device THINKS it's connected
 * (e.g. is Wi-Fi/data on), not necessarily that the server is reachable.
 * That's good enough for v1; a more robust check would ping the backend
 * periodically, which we can add later if needed.
 */
export function useConnectivity() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return isOnline;
}
