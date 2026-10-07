import React, { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { fetchCustomerDeliveryAgentLocation, fetchPublicTrackingAgentLocation } from "../services/api";
import { cacheTile, getCachedTile } from "../services/tileCache";
import { connectWebSocket } from "../services/websocket";

// Leaflet's default marker icon references image files by a relative
// path that doesn't survive bundling — this is the standard fix,
// pointing it at the same images the leaflet package ships.
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

/**
 * A tile layer that caches every tile it loads (via services/tileCache.js)
 * and falls back to that cache when a tile can't be fetched — this is
 * what keeps the tracking map showing the last-viewed area instead of
 * going blank the moment connectivity drops. Overrides Leaflet's
 * createTile, which is the documented extension point for exactly this
 * (custom tile loading logic), rather than Leaflet's normal built-in
 * <img src="..."> loading which only ever uses the browser's regular
 * HTTP cache and has no offline fallback of its own.
 */
const CachedTileLayer = L.TileLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement("img");
    tile.alt = "";
    tile.setAttribute("role", "presentation");
    const url = this.getTileUrl(coords);

    (async () => {
      // If we're definitely offline, don't waste time on a network
      // attempt that will only fail — go straight to cache.
      if (!navigator.onLine) {
        const cached = await getCachedTile(url);
        if (cached) {
          tile.src = URL.createObjectURL(cached);
          done(null, tile);
        } else {
          done(new Error("Offline and no cached tile for this area"), tile);
        }
        return;
      }

      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Tile fetch failed: ${response.status}`);
        const blob = await response.blob();
        cacheTile(url, blob); // fire-and-forget — don't block rendering on the cache write
        tile.src = URL.createObjectURL(blob);
        done(null, tile);
      } catch (err) {
        // Network attempt failed even though navigator.onLine said we
        // were online (flaky connection) — fall back to cache.
        const cached = await getCachedTile(url);
        if (cached) {
          tile.src = URL.createObjectURL(cached);
          done(null, tile);
        } else {
          done(err, tile);
        }
      }
    })();

    return tile;
  },
});

/**
 * Live GPS tracking map for one delivery — moves the marker in real
 * time as the agent's position updates, pushed over a WebSocket
 * (routes/websockets.py's tracking room) rather than polled. No auth
 * needed for that socket: it's scoped to one delivery_id (an
 * unguessable UUID), the same security model the public tracking page
 * already uses. A slow (30s) background poll still runs alongside it
 * purely as a safety net — if a network blocks WebSocket upgrades
 * entirely (some restrictive corporate/mobile networks do), the map
 * still stays roughly current instead of freezing forever. Uses
 * OpenStreetMap tiles (free, no API key) via Leaflet, not Google Maps,
 * since Google Maps requires a billing-enabled API key.
 *
 * Works in two modes: pass `token` for the logged-in customer dashboard
 * (calls GET /customer/deliveries/{id}/agent-location), or omit it for
 * the public no-login tracking page (calls GET /track/{id}/agent-location
 * instead — same shape, no auth, but only returns a position while the
 * delivery is actually out with an agent; see that endpoint's docstring).
 * The WebSocket push needs no auth either way, so real-time updates work
 * identically in both modes.
 */
export default function LiveTrackingMap({ token, deliveryId }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | live | unavailable

  useEffect(() => {
    let intervalId;
    let cancelled = false;

    function applyLocation(latitude, longitude) {
      if (cancelled) return;
      setStatus("live");
      const latLng = [latitude, longitude];

      if (!mapRef.current && mapContainerRef.current) {
        mapRef.current = L.map(mapContainerRef.current, {
          zoomControl: true,
          attributionControl: true,
        }).setView(latLng, 14);

        new CachedTileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(mapRef.current);

        markerRef.current = L.marker(latLng).addTo(mapRef.current)
          .bindPopup("Your delivery agent");
      } else if (mapRef.current && markerRef.current) {
        markerRef.current.setLatLng(latLng);
        mapRef.current.panTo(latLng);
      }
    }

    async function poll() {
      try {
        const loc = token
          ? await fetchCustomerDeliveryAgentLocation(token, deliveryId)
          : await fetchPublicTrackingAgentLocation(deliveryId);
        if (cancelled) return;
        if (!loc) {
          setStatus((prev) => (prev === "live" ? "live" : "unavailable"));
          return;
        }
        applyLocation(loc.latitude, loc.longitude);
      } catch (err) {
        if (!cancelled) setStatus((prev) => (prev === "live" ? "live" : "unavailable"));
      }
    }

    poll(); // initial fetch so the map isn't blank while the socket connects
    intervalId = setInterval(poll, 30000); // safety net — see module docstring

    const socket = connectWebSocket(`/ws/tracking/${deliveryId}`, {
      onMessage: (data) => {
        if (data.event === "location_update") {
          applyLocation(data.latitude, data.longitude);
        }
      },
    });

    return () => {
      cancelled = true;
      clearInterval(intervalId);
      socket.close();
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [token, deliveryId]);

  if (status === "unavailable") {
    return (
      <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>
        Live location isn't available for this order yet — it shows up
        once the agent turns on location sharing.
      </p>
    );
  }

  return (
    <div>
      <div
        ref={mapContainerRef}
        style={{ height: "220px", width: "100%", borderRadius: "var(--radius-sm)", overflow: "hidden" }}
      />
      {status === "loading" && (
        <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>Locating agent...</p>
      )}
    </div>
  );
}
