import React, { useEffect, useState } from "react";
import { fetchPackageQrUrl, recordScan, fetchScanHistory } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const SCAN_TYPES = [
  { value: "pickup", label: "Pickup" },
  { value: "hub", label: "Hub" },
  { value: "out_for_delivery", label: "Out for Delivery" },
  { value: "delivery", label: "Delivery" },
  { value: "return", label: "Return" },
];

/**
 * Shown on a delivery's detail view (Phase 8) — the delivery's own ID
 * is the package code (see models/scan.py's module docstring), so the
 * QR here just encodes that ID; scanning it elsewhere resolves back to
 * this same delivery via GET /scan/{code}.
 */
export default function PackageScanWidget({ deliveryId }) {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [qrUrl, setQrUrl] = useState(null);
  const [history, setHistory] = useState([]);
  const [locationNote, setLocationNote] = useState("");
  const [isRecording, setIsRecording] = useState(false);

  useEffect(() => {
    fetchPackageQrUrl(token, deliveryId).then(setQrUrl).catch(() => {});
    loadHistory();
  }, [deliveryId]);

  async function loadHistory() {
    try {
      setHistory(await fetchScanHistory(token, deliveryId));
    } catch (err) {
      // permission/ownership-gated — silently show empty history rather than an alarming error here
    }
  }

  async function handleScan(scanType) {
    setIsRecording(true);
    try {
      await recordScan(token, deliveryId, { scan_type: scanType, location_note: locationNote || undefined });
      showToast(`${scanType.replace("_", " ")} scan recorded.`, "success");
      setLocationNote("");
      await loadHistory();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsRecording(false);
    }
  }

  return (
    <div style={{ marginBottom: "10px" }}>
      <div style={{ display: "flex", gap: "12px", alignItems: "flex-start", flexWrap: "wrap" }}>
        {qrUrl && (
          <img src={qrUrl} alt="Package QR code" style={{ width: "90px", height: "90px", background: "#fff", padding: "4px", borderRadius: "var(--radius-sm)" }} />
        )}
        <div style={{ flexGrow: 1, minWidth: "200px" }}>
          <input
            className="input"
            placeholder="Location note (optional)"
            value={locationNote}
            onChange={(e) => setLocationNote(e.target.value)}
            style={{ marginBottom: "6px" }}
          />
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {SCAN_TYPES.map((t) => (
              <button key={t.value} className="btn-info-outline" disabled={isRecording} onClick={() => handleScan(t.value)}>
                Scan: {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {history.length > 0 && (
        <div style={{ marginTop: "10px" }}>
          <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginBottom: "4px" }}>Scan History</div>
          {history.map((s) => (
            <div key={s.id} style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
              {s.scan_type.replace("_", " ")}{s.location_note ? ` — ${s.location_note}` : ""} — {new Date(s.scanned_at).toLocaleString()}
              {s.captured_offline && " (offline)"}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
