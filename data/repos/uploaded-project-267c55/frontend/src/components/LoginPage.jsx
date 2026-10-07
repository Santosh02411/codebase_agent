import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useCustomerAuth } from "../context/CustomerAuthContext";
import { useTheme } from "../context/ThemeContext";
import { resendTwoFactorLoginCode } from "../services/api";
import { getGoogleOAuthLoginUrl, getCustomerGoogleOAuthLoginUrl } from "../services/authApi";
import PasswordInput from "./PasswordInput";
import GoogleIcon from "./GoogleIcon";
import "../styles/auth.css";

export default function LoginPage({ onSwitchToSignup, onForgotPassword }) {
  const { login: staffLogin, completeTwoFactorLogin, demoLogin } = useAuth();
  const { login: customerLogin } = useCustomerAuth();
  const { theme, toggleTheme } = useTheme();

  const [accountType, setAccountType] = useState("staff"); // "staff" | "customer"
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDemoLoading, setIsDemoLoading] = useState(false);

  // Set once staffLogin() comes back saying this account needs a 2FA
  // code — switches the form into a second step instead of navigating
  // away, since a password alone isn't enough to finish logging in.
  const [twoFactorChallenge, setTwoFactorChallenge] = useState(null);
  const [twoFactorMethod, setTwoFactorMethod] = useState(null); // "totp" | "email"
  const [maskedEmail, setMaskedEmail] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [isResending, setIsResending] = useState(false);
  const [resendMessage, setResendMessage] = useState("");
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);

  async function handleTryDemo() {
    setError("");
    setIsDemoLoading(true);
    try {
      await demoLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsDemoLoading(false);
    }
  }

  async function handleGoogleSignIn() {
    setError("");
    setIsGoogleLoading(true);
    try {
      const url = accountType === "staff" ? await getGoogleOAuthLoginUrl() : await getCustomerGoogleOAuthLoginUrl();
      window.location.href = url;
    } catch (err) {
      setError(err.message);
      setIsGoogleLoading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      if (accountType === "staff") {
        const result = await staffLogin(identifier, password);
        if (result && result.requires_2fa) {
          setTwoFactorChallenge(result.challenge_token);
          setTwoFactorMethod(result.two_factor_method);
          setMaskedEmail(result.masked_email);
        }
      } else {
        await customerLogin(identifier, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleTwoFactorSubmit(e) {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await completeTwoFactorLogin(twoFactorChallenge, twoFactorCode.trim());
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleResend() {
    setError("");
    setResendMessage("");
    setIsResending(true);
    try {
      await resendTwoFactorLoginCode(twoFactorChallenge);
      setResendMessage("A new code is on its way to your inbox.");
    } catch (err) {
      setError(err.message);
    } finally {
      setIsResending(false);
    }
  }

  if (twoFactorChallenge) {
    return (
      <div className="auth-page-wrapper">
                <div className="auth-wordmark">Delivery Sync</div>
        <button className="auth-theme-toggle" onClick={toggleTheme}>
          {theme === "dark" ? "☀ Light" : "☾ Dark"}
        </button>
        <div className="auth-card">
          <h2>Enter your code</h2>
          {twoFactorMethod === "email" ? (
            <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
              We sent a 6-digit code to {maskedEmail || "your email"}. Enter it below — it expires in 10 minutes.
            </p>
          ) : (
            <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
              Open your authenticator app and enter the 6-digit code for this account.
            </p>
          )}
          <form onSubmit={handleTwoFactorSubmit}>
            <div className="auth-field">
              <label htmlFor="login-2fa-code">6-digit code</label>
              <input
                id="login-2fa-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={twoFactorCode}
                onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, ""))}
                required
                autoFocus
              />
            </div>

            {error && <p className="auth-error">{error}</p>}
            {resendMessage && !error && (
              <p style={{ fontSize: "12px", color: "var(--status-delivered)" }}>{resendMessage}</p>
            )}

            <button type="submit" className="auth-submit-btn" disabled={isSubmitting || twoFactorCode.length !== 6}>
              {isSubmitting ? "Verifying..." : "Verify & Log in"}
            </button>
          </form>

          {twoFactorMethod === "email" && (
            <p className="auth-switch-text">
              <button className="auth-switch-link" onClick={handleResend} disabled={isResending}>
                {isResending ? "Sending..." : "Didn't get it? Resend code"}
              </button>
            </p>
          )}

          <p className="auth-switch-text">
            <button
              className="auth-switch-link"
              onClick={() => {
                setTwoFactorChallenge(null);
                setTwoFactorMethod(null);
                setMaskedEmail(null);
                setTwoFactorCode("");
                setResendMessage("");
                setError("");
              }}
            >
              Back to login
            </button>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page-wrapper">
            <div className="auth-wordmark">Delivery Sync</div>
      <button className="auth-theme-toggle" onClick={toggleTheme}>
        {theme === "dark" ? "☀ Light" : "☾ Dark"}
      </button>
      <div className="auth-card">
        <h2>Log in</h2>

        <button
          type="button"
          className="auth-demo-btn"
          onClick={handleTryDemo}
          disabled={isDemoLoading}
        >
          {isDemoLoading ? "Loading demo..." : "▶ Try the Demo — No Signup Required"}
        </button>
        <p className="auth-demo-hint">
          Explore a fully populated dispatcher dashboard with real sample data — instantly.
        </p>
        <div className="auth-divider"><span>or log in</span></div>

        <div className="auth-field">
          <label htmlFor="login-account-type">I am a...</label>
          <select id="login-account-type" value={accountType} onChange={(e) => { setAccountType(e.target.value); setIdentifier(""); }}>
            <option value="staff">Delivery Agent / Dispatcher / Admin</option>
            <option value="customer">Customer (Track My Orders)</option>
          </select>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="auth-field">
            <label htmlFor="login-identifier">{accountType === "staff" ? "Username" : "Email"}</label>
            <input
              id="login-identifier"
              type={accountType === "staff" ? "text" : "email"}
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="auth-field">
            <label htmlFor="login-password">Password</label>
            <PasswordInput
              id="login-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error && <p className="auth-error">{error}</p>}

          <button type="submit" className="auth-submit-btn" disabled={isSubmitting}>
            {isSubmitting ? "Logging in..." : "Log in"}
          </button>
        </form>

        <div className="auth-divider"><span>or</span></div>
        <button
          type="button"
          className="auth-google-btn"
          onClick={handleGoogleSignIn}
          disabled={isGoogleLoading}
        >
          <GoogleIcon />
          {isGoogleLoading ? "Redirecting..." : "Sign in with Google"}
        </button>

        <p className="auth-switch-text">
          <button className="auth-switch-link" onClick={() => onForgotPassword(accountType)}>
            Forgot password?
          </button>
        </p>

        <p className="auth-switch-text">
          Don't have an account?{" "}
          <button className="auth-switch-link" onClick={() => onSwitchToSignup(accountType)}>
            Sign up
          </button>
        </p>
      </div>
    </div>
  );
}
