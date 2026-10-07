import React, { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/**
 * Click-anywhere-to-set-a-point map picker. Built for zone center
 * selection (ZoneManager.jsx) but generic — anywhere in the app that
 * needs "point on a map" instead of asking someone to type latitude
 * and longitude by hand. Nobody has coordinates memorized; a map click
 * is the only reasonable UI for this.
 *
 * Same OpenStreetMap tiles (free, no API key) as LiveTrackingMap.jsx.
 * A "Use my current location" button is also offered where the
 * caller wants it (see ZoneManager.jsx), but this component itself
 * only handles the click-to-place part — it has no opinion on how the
 * initial point got there.
 */
export default function LocationPicker({ latitude, longitude, onChange, radiusKm, height = 260 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const circleRef = useRef(null);
  const [isReady, setIsReady] = useState(false);

  // Initial mount — build the map once. Deliberately does NOT depend
  // on latitude/longitude/radiusKm so typing in the fallback manual
  // fields (or a parent re-render) never tears down and rebuilds the
  // whole Leaflet instance; those are synced via the second effect below.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const startLat = latitude ?? 20.5937; // center of India as a reasonable default when nothing's picked yet
    const startLng = longitude ?? 78.9629;
    const startZoom = latitude != null ? 13 : 5;

    const map = L.map(containerRef.current).setView([startLat, startLng], startZoom);
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    map.on("click", (e) => {
      onChange(e.latlng.lat, e.latlng.lng);
    });

    setIsReady(true);

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the marker/circle in sync with whatever point is currently selected.
  useEffect(() => {
    if (!isReady || !mapRef.current || latitude == null || longitude == null) return;
    const latLng = [latitude, longitude];

    if (!markerRef.current) {
      markerRef.current = L.marker(latLng, { draggable: true }).addTo(mapRef.current);
      markerRef.current.on("dragend", () => {
        const pos = markerRef.current.getLatLng();
        onChange(pos.lat, pos.lng);
      });
    } else {
      markerRef.current.setLatLng(latLng);
    }

    if (radiusKm && radiusKm > 0) {
      if (!circleRef.current) {
        circleRef.current = L.circle(latLng, {
          radius: radiusKm * 1000,
          color: "#f2a93b",
          fillColor: "#f2a93b",
          fillOpacity: 0.12,
          weight: 2,
        }).addTo(mapRef.current);
      } else {
        circleRef.current.setLatLng(latLng);
        circleRef.current.setRadius(radiusKm * 1000);
      }
    } else if (circleRef.current) {
      circleRef.current.remove();
      circleRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReady, latitude, longitude, radiusKm]);

  return (
    <div>
      <div
        ref={containerRef}
        style={{
          height: `${height}px`,
          borderRadius: "var(--radius-sm)",
          border: "1px solid var(--border-color-light)",
          marginBottom: "6px",
        }}
      />
      <p style={{ fontSize: "11.5px", color: "var(--text-muted)", margin: 0 }}>
        Click the map to set the point{radiusKm ? " (drag the marker to fine-tune)" : ""}.
      </p>
    </div>
  );
}
