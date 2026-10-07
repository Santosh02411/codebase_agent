import React, { useState } from "react";
import { forgotPasswordRequest, customerForgotPasswordRequest } from "../services/authApi";
import { useTheme } from "../context/ThemeContext";
import Captcha from "./Captcha";
import "../styles/auth.css";

export default function ForgotPasswordPage({ onBackToLogin, accountType = "staff" }) {
  const { theme, toggleTheme } = useTheme();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [captchaToken, setCaptchaToken] = useState(null);
  const isCustomer = accountType === "customer";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setMessage("");
    setIsSubmitting(true);
    try {
      const result = isCustomer
        ? await customerForgotPasswordRequest(email, captchaToken)
        : await forgotPasswordRequest(email, captchaToken);
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
        <h2>Reset your password</h2>
        <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "16px" }}>
          Enter the email you signed up with. If it's registered, we'll send
          a reset link.
        </p>

        {!message && (
          <form onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="forgot-password-email">Email</label>
              <input
                id="forgot-password-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>

            <Captcha onVerify={setCaptchaToken} />

            {error && <p className="auth-error">{error}</p>}

            <button type="submit" className="auth-submit-btn" disabled={isSubmitting}>
              {isSubmitting ? "Sending..." : "Send Reset Link"}
            </button>
          </form>
        )}

        {message && (
          <p style={{ fontSize: "13.5px", color: "var(--status-delivered)" }}>{message}</p>
        )}

        <p className="auth-switch-text">
          <button className="auth-switch-link" onClick={onBackToLogin}>
            Back to log in
          </button>
        </p>
      </div>
    </div>
  );
}
