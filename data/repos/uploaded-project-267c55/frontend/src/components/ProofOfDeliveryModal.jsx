import React, { useRef, useState, useEffect } from "react";
import { generateDeliveryOtp } from "../services/api";

/**
 * Shown when an agent marks a delivery "Delivered" — captures full
 * proof of delivery (Phase 1): a signature or photo, recipient name/
 * phone, an optional OTP verification step, GPS coordinates, and
 * notes. Calls onConfirm(payload) with the full capture object once
 * confirmed; onCancel() if the agent backs out (in which case the
 * status change itself is also cancelled — proof is required to
 * complete a delivery, not optional, whenever an org has any
 * pod_require_* setting turned on; when none are on, this still runs
 * the same way, it's just that nothing downstream will reject an
 * incomplete capture).
 *
 * Every field here is OPTIONAL from this component's own point of
 * view — it never knows which org settings are active. Validation
 * against the org's actual requirements happens server-side (see
 * services/pod.py), and any rejection is surfaced back to the agent
 * as a toast by the caller. This keeps the modal itself simple and
 * correct even if org settings change after this bundle was built.
 */
export default function ProofOfDeliveryModal({ deliveryId, token, onConfirm, onCancel }) {
  const [mode, setMode] = useState("signature"); // "signature" | "photo"
  const canvasRef = useRef(null);
  const isDrawingRef = useRef(false);
  const [hasDrawn, setHasDrawn] = useState(false);
  const [photoDataUrl, setPhotoDataUrl] = useState(null);

  const [recipientName, setRecipientName] = useState("");
  const [recipientPhone, setRecipientPhone] = useState("");
  const [notes, setNotes] = useState("");

  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpSending, setOtpSending] = useState(false);
  const [otpHint, setOtpHint] = useState(null);
  const [otpError, setOtpError] = useState(null);

  const [coords, setCoords] = useState(null); // { latitude, longitude } as strings
  const [gpsStatus, setGpsStatus] = useState("idle"); // idle | locating | done | denied

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#1a1204";
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
  }, [mode]);

  // Best-effort GPS capture as soon as the modal opens — never blocks
  // confirming (an org that requires GPS gets that enforced server-side;
  // this is just "grab it automatically if the browser/agent allows it"
  // so the agent doesn't have to do anything extra in the common case).
  useEffect(() => {
    if (!navigator.geolocation) return;
    setGpsStatus("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({
          latitude: String(pos.coords.latitude),
          longitude: String(pos.coords.longitude),
        });
        setGpsStatus("done");
      },
      () => setGpsStatus("denied"),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }, []);

  function getPos(e) {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function startDraw(e) {
    isDrawingRef.current = true;
    const { x, y } = getPos(e);
    const ctx = canvasRef.current.getContext("2d");
    ctx.beginPath();
    ctx.moveTo(x, y);
  }

  function draw(e) {
    if (!isDrawingRef.current) return;
    e.preventDefault();
    const { x, y } = getPos(e);
    const ctx = canvasRef.current.getContext("2d");
    ctx.lineTo(x, y);
    ctx.stroke();
    setHasDrawn(true);
  }

  function stopDraw() {
    isDrawingRef.current = false;
  }

  function clearCanvas() {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    setHasDrawn(false);
  }

  function handlePhotoSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => setPhotoDataUrl(event.target.result);
    reader.readAsDataURL(file);
  }

  async function handleSendOtp() {
    if (!navigator.onLine) {
      setOtpError("You're offline — OTP codes can't be sent until you're back online.");
      return;
    }
    setOtpSending(true);
    setOtpError(null);
    try {
      const result = await generateDeliveryOtp(token, deliveryId);
      if (!result.sent) {
        setOtpError("No email or phone on file for this order — ask the recipient to confirm verbally, or add contact info first.");
      } else {
        setOtpSent(true);
        setOtpHint(result.destination_hint);
      }
    } catch (err) {
      setOtpError(err.message);
    } finally {
      setOtpSending(false);
    }
  }

  function handleConfirm() {
    onConfirm({
      recipient_name: recipientName.trim() || undefined,
      recipient_phone: recipientPhone.trim() || undefined,
      otp_code: otpCode.trim() || undefined,
      signature_data_url: mode === "signature" && hasDrawn ? canvasRef.current.toDataURL("image/png") : undefined,
      photo_data_url: mode === "photo" && photoDataUrl ? photoDataUrl : undefined,
      latitude: coords ? coords.latitude : undefined,
      longitude: coords ? coords.longitude : undefined,
      notes: notes.trim() || undefined,
      captured_at: new Date().toISOString(),
    });
  }

  const hasSignatureOrPhoto = mode === "signature" ? hasDrawn : !!photoDataUrl;
  // At least SOME capture is required at the UI level (a signature/photo);
  // everything else is optional here and enforced server-side per org.
  const canConfirm = hasSignatureOrPhoto;

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "440px", maxHeight: "85vh", overflowY: "auto" }}>
        <h3 style={{ marginBottom: "12px" }}>Proof of Delivery</h3>
        <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
          Capture a signature or photo to confirm this delivery. Recipient details, verification, and location are optional unless required by your organization.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "10px" }}>
          <div>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Recipient name</label>
            <input className="input" value={recipientName} onChange={(e) => setRecipientName(e.target.value)} placeholder="Who received it" />
          </div>
          <div>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Recipient phone</label>
            <input className="input" value={recipientPhone} onChange={(e) => setRecipientPhone(e.target.value)} placeholder="Optional" />
          </div>
        </div>

        <div style={{ marginBottom: "10px", padding: "8px", background: "var(--bg-secondary, #f8fafc)", borderRadius: "var(--radius-sm)" }}>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" className="btn" onClick={handleSendOtp} disabled={otpSending || otpSent}>
              {otpSending ? "Sending..." : otpSent ? "Code sent" : "Send verification code"}
            </button>
            {otpHint && <span style={{ fontSize: "11.5px", color: "var(--text-secondary)" }}>Sent to {otpHint}</span>}
          </div>
          {otpSent && (
            <input
              className="input"
              style={{ marginTop: "8px" }}
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              placeholder="Enter the 6-digit code from the recipient"
              maxLength={6}
            />
          )}
          {otpError && <p style={{ fontSize: "11.5px", color: "var(--danger, #dc2626)", marginTop: "6px" }}>{otpError}</p>}
        </div>

        <div style={{ fontSize: "11.5px", color: "var(--text-secondary)", marginBottom: "10px" }}>
          {gpsStatus === "locating" && "Getting your location..."}
          {gpsStatus === "done" && `Location captured (${coords.latitude.slice(0, 8)}, ${coords.longitude.slice(0, 8)})`}
          {gpsStatus === "denied" && "Location unavailable — check your device's location permission."}
        </div>

        <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
          <button
            className={mode === "signature" ? "btn btn-primary" : "btn"}
            onClick={() => setMode("signature")}
          >
            Signature
          </button>
          <button
            className={mode === "photo" ? "btn btn-primary" : "btn"}
            onClick={() => setMode("photo")}
          >
            Photo
          </button>
        </div>

        {mode === "signature" && (
          <div>
            <canvas
              ref={canvasRef}
              width={360}
              height={180}
              style={{ border: "1px solid var(--border-color)", borderRadius: "var(--radius-sm)", touchAction: "none", width: "100%", maxWidth: "360px" }}
              onMouseDown={startDraw}
              onMouseMove={draw}
              onMouseUp={stopDraw}
              onMouseLeave={stopDraw}
              onTouchStart={startDraw}
              onTouchMove={draw}
              onTouchEnd={stopDraw}
            />
            <button className="btn" onClick={clearCanvas} style={{ marginTop: "8px" }}>
              Clear
            </button>
          </div>
        )}

        {mode === "photo" && (
          <div>
            <input type="file" accept="image/*" capture="environment" onChange={handlePhotoSelect} className="input" />
            {photoDataUrl && (
              <img
                src={photoDataUrl}
                alt="Proof of delivery preview"
                style={{ marginTop: "10px", maxWidth: "100%", maxHeight: "180px", borderRadius: "var(--radius-sm)" }}
              />
            )}
          </div>
        )}

        <div style={{ marginTop: "10px" }}>
          <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Notes</label>
          <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Left with neighbor, gate code used, etc." />
        </div>

        <div style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
          <button className="btn btn-primary" onClick={handleConfirm} disabled={!canConfirm}>
            Confirm Delivery
          </button>
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
