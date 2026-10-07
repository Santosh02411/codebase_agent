import React, { useState } from "react";
import { resetPasswordRequest, customerResetPasswordRequest } from "../services/authApi";
import { useTheme } from "../context/ThemeContext";
import PasswordInput from "./PasswordInput";
import "../styles/auth.css";

/**
 * Shown when the app loads with a ?reset_token=... (staff) or
 * ?customer_reset_token=... (customer) in the URL (i.e. the person
 * clicked the link from their "reset email" — which, without SMTP
 * configured, means the link printed to the backend console during local
 * development/testing).
 *
 * Staff accounts (not customers — the mobile app is agent/dispatcher-
 * only) additionally get an "Open in the Delivery Sync app" link,
 * built from the SAME token, using the `deliverysync://` scheme the
 * mobile app registers (see mobile/app.json's "scheme" and App.js's
 * deep-link handling). Tapping it in a mobile browser hands the token
 * straight to mobile/src/screens/ResetPasswordScreen.js instead of
 * finishing here. This page stays the link that actually goes in the
 * email (see backend FRONTEND_URL) because it works everywhere,
 * app-installed or not, unlike a bare custom-scheme link would — a
 * real "click the email, land straight in the app" flow (no browser
 * step at all) needs Android App Links / iOS Universal Links, which
 * need a verified HTTPS domain this project has no way to register or
 * test, so this is the honest middle ground: works for everyone, with
 * a real one-tap path into the app for anyone who has it installed.
 */
export default function ResetPasswordPage({ token, onDone, accountType = "staff" }) {
  const { theme, toggleTheme } = useTheme();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isCustomer = accountType === "customer";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = isCustomer
        ? await customerResetPasswordRequest(token, newPassword)
        : await resetPasswordRequest(token, newPassword);
      setMessage(result.message);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-page-wrapper">
            <div className="auth-wordmark">Delivery Sync</div>
      <button className="auth-theme-toggle" onClick={toggleTheme}>
        {theme === "dark" ? "☀ Light" : "☾ Dark"}
      </button>
      <div className="auth-card">
        <h2>Set a new password</h2>

        {!message && (
          <form onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="reset-password-new">New Password</label>
              <PasswordInput
                id="reset-password-new"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="auth-field">
              <label htmlFor="reset-password-confirm">Confirm New Password</label>
              <PasswordInput
                id="reset-password-confirm"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>

            {error && <p className="auth-error">{error}</p>}

            <button type="submit" className="auth-submit-btn" disabled={isSubmitting}>
              {isSubmitting ? "Resetting..." : "Reset Password"}
            </button>
          </form>
        )}

        {!message && !isCustomer && (
          <p style={{ fontSize: "12.5px", marginTop: "16px", textAlign: "center" }}>
            <a href={`deliverysync://reset-password?token=${encodeURIComponent(token)}`}>
              Open in the Delivery Sync app
            </a>
          </p>
        )}

        {message && (
          <>
            <p style={{ fontSize: "13.5px", color: "var(--status-delivered)", marginBottom: "16px" }}>
              {message}
            </p>
            <button className="auth-submit-btn" onClick={onDone}>
              Continue to Log In
            </button>
          </>
        )}
      </div>
    </div>
  );
}
