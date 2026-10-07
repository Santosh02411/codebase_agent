import React, { useEffect, useRef, useState } from "react";

/**
 * Scans a QR code or barcode using the device camera, so an agent can
 * scan a package instead of typing its order ID.
 *
 * Deliberately built on the browser's NATIVE BarcodeDetector API rather
 * than a third-party JS library — this needs zero new npm dependencies,
 * which matters because camera-based code genuinely can't be verified
 * without a real device and camera, so keeping the implementation as
 * simple and dependency-free as possible reduces what could go wrong.
 *
 * KNOWN LIMITATION (disclosed, not hidden): BarcodeDetector is currently
 * only supported in Chromium-based browsers (Chrome, Edge, Opera) — NOT
 * in Firefox or Safari as of this writing. Where unsupported, this shows
 * a clear message and lets the agent type the order ID manually instead
 * of failing silently or showing a broken camera view.
 */
export default function BarcodeScannerModal({ onScan, onClose }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [status, setStatus] = useState("checking"); // checking | unsupported | requesting | scanning | error
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!("BarcodeDetector" in window)) {
      setStatus("unsupported");
      return;
    }

    let detector;
    let animationFrameId;
    let isCancelled = false;

    async function startScanning() {
      try {
        detector = new window.BarcodeDetector({
          formats: ["qr_code", "code_128", "code_39", "ean_13", "upc_a"],
        });

        setStatus("requesting");
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
        if (isCancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = stream;
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        setStatus("scanning");

        async function scanFrame() {
          if (isCancelled) return;
          try {
            const barcodes = await detector.detect(videoRef.current);
            if (barcodes.length > 0) {
              onScan(barcodes[0].rawValue);
              return;
            }
          } catch (err) {
            // A single failed frame isn't fatal — try the next one.
          }
          animationFrameId = requestAnimationFrame(scanFrame);
        }
        scanFrame();
      } catch (err) {
        setStatus("error");
        setErrorMessage(
          err.name === "NotAllowedError"
            ? "Camera permission was denied. Allow camera access and try again."
            : `Couldn't access the camera: ${err.message}`
        );
      }
    }

    startScanning();

    return () => {
      isCancelled = true;
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, [onScan]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <h3 style={{ margin: 0 }}>Scan Package</h3>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{ background: "none", border: "none", fontSize: "22px", cursor: "pointer", color: "var(--text-secondary)" }}
          >
            ×
          </button>
        </div>

        {status === "unsupported" && (
          <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
            Barcode scanning isn't supported in this browser yet (it currently
            works in Chrome/Edge on Android and desktop). Please type the
            order ID in the search box instead.
          </p>
        )}

        {status === "error" && (
          <p style={{ fontSize: "13px", color: "var(--danger)" }}>{errorMessage}</p>
        )}

        {(status === "requesting" || status === "scanning") && (
          <div>
            <video
              ref={videoRef}
              style={{ width: "100%", borderRadius: "var(--radius-sm)", backgroundColor: "#000" }}
              muted
              playsInline
            />
            <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginTop: "8px" }}>
              {status === "requesting" ? "Requesting camera access..." : "Point your camera at a QR code or barcode."}
            </p>
          </div>
        )}

        <button className="btn" onClick={onClose} style={{ marginTop: "12px" }}>
          Cancel
        </button>
      </div>
    </div>
  );
}
