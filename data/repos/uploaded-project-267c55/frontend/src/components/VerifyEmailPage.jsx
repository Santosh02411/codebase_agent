import React, { useEffect, useState } from "react";
import { verifyEmailRequest, customerVerifyEmailRequest } from "../services/authApi";
import { useTheme } from "../context/ThemeContext";
import "../styles/auth.css";

/**
 * Shown when the app loads with a ?verify_email_token=... (staff) or
 * ?verify_customer_email_token=... (customer) in the URL — i.e. the
 * person clicked the link from their verification email (or, without
 * SMTP configured, the link printed to the backend console during
 * local development/testing). Fires the verification call once on
 * mount rather than requiring a button press, since arriving here at
 * all already proves intent (they clicked a link sent to their inbox).
 */
export default function VerifyEmailPage({ token, onDone, accountType = "staff" }) {
  const { theme, toggleTheme } = useTheme();
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const isCustomer = accountType === "customer";

  useEffect(() => {
    (async () => {
      try {
        const result = isCustomer
          ? await customerVerifyEmailRequest(token)
          : await verifyEmailRequest(token);
        setMessage(result.message);
      } catch (err) {
        setError(err.message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="auth-page-wrapper">
      <div className="auth-wordmark">Delivery Sync</div>
      <button className="auth-theme-toggle" onClick={toggleTheme}>
        {theme === "dark" ? "☀ Light" : "☾ Dark"}
      </button>
      <div className="auth-card">
        <h2>Verify your email</h2>

        {!message && !error && (
          <p style={{ fontSize: "13.5px", color: "var(--text-secondary)" }}>Verifying...</p>
        )}

        {message && (
          <p style={{ fontSize: "13.5px", color: "var(--status-delivered)", marginBottom: "16px" }}>
            {message}
          </p>
        )}

        {error && (
          <p className="auth-error" style={{ marginBottom: "16px" }}>{error}</p>
        )}

        {(message || error) && (
          <button className="auth-submit-btn" onClick={onDone}>
            Continue
          </button>
        )}
      </div>
    </div>
  );
}
