import React, { useState } from "react";

/**
 * A quiet, non-blocking nudge shown above the dashboard when the
 * logged-in account's email isn't verified yet. Deliberately NOT a
 * modal or anything that blocks interaction — see routes/auth.py's
 * /verify-email docstring for why verification itself doesn't gate
 * anything else in this app. This is just a visible reminder plus a
 * one-click way to get a fresh link if the first email was missed or
 * expired (48-hour expiry).
 */
export default function VerificationBanner({ onResend }) {
  const [status, setStatus] = useState("idle"); // idle | sending | sent | error
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  async function handleResend() {
    setStatus("sending");
    try {
      await onResend();
      setStatus("sent");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        flexWrap: "wrap",
        padding: "10px 14px",
        marginBottom: "16px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-color)",
        backgroundColor: "var(--bg-surface-elevated)",
        fontSize: "13px",
      }}
    >
      <span style={{ flex: 1, minWidth: "200px" }}>
        {status === "sent"
          ? "Verification email sent — check your inbox."
          : "Please verify your email address to secure your account."}
      </span>
      {status !== "sent" && (
        <button className="btn" style={{ fontSize: "12px", padding: "4px 10px" }} onClick={handleResend} disabled={status === "sending"}>
          {status === "sending" ? "Sending..." : status === "error" ? "Failed — retry" : "Resend email"}
        </button>
      )}
      <button
        className="btn"
        style={{ fontSize: "12px", padding: "4px 10px" }}
        onClick={() => setDismissed(true)}
      >
        Dismiss
      </button>
    </div>
  );
}
