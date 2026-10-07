import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  fetchTwoFactorStatus,
  setupTwoFactor,
  enableTwoFactor,
  setupEmailTwoFactor,
  enableEmailTwoFactor,
  disableTwoFactor,
} from "../services/api";
import PasswordInput from "./PasswordInput";

/**
 * Lets a staff user (agent/dispatcher/admin) turn two-factor
 * authentication on or off, choosing between two methods:
 *
 * - "Authenticator app" (TOTP): scan a QR code with a dedicated
 *   authenticator app — Google Authenticator, Microsoft Authenticator,
 *   Authy, 1Password, etc. IMPORTANT: this has to be an authenticator
 *   app's own built-in QR scanner, not a phone's general camera app or
 *   Google Lens/Search. Those just read the QR as a block of text and
 *   try to web-search it (since otpauth:// isn't a URL scheme they know
 *   how to open) — that's not a bug in this app, it's the wrong tool
 *   for this kind of QR code. The manual key entry below the QR code
 *   is the fallback either way.
 *
 * - "Email code" (no app needed): a 6-digit code gets emailed to the
 *   account's own address at login time. Simpler to use, but only as
 *   secure as that inbox.
 *
 * Setup is two steps either way, on purpose: starting setup doesn't
 * turn anything on yet; only a confirmed real code (from the freshly-
 * scanned app, or the freshly-sent email) does. This means an abandoned
 * setup attempt can't accidentally lock the account out.
 */
export default function TwoFactorSettings() {
  const { token, updateUser } = useAuth();
  const { showToast } = useToast();

  const [status, setStatus] = useState(null); // { totp_enabled, two_factor_method }
  const [isLoading, setIsLoading] = useState(true);

  // Which method the user is currently setting up — null means "not
  // mid-setup", showing the two method-choice buttons instead.
  const [settingUpMethod, setSettingUpMethod] = useState(null); // "totp" | "email" | null
  const [totpSetupData, setTotpSetupData] = useState(null); // { secret, otpauth_uri }
  const [emailMaskedAddress, setEmailMaskedAddress] = useState(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [isConfirming, setIsConfirming] = useState(false);

  const [showDisableForm, setShowDisableForm] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [isDisabling, setIsDisabling] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setIsLoading(true);
    try {
      const data = await fetchTwoFactorStatus(token);
      setStatus(data);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  }

  function resetSetupState() {
    setSettingUpMethod(null);
    setTotpSetupData(null);
    setEmailMaskedAddress(null);
    setConfirmCode("");
  }

  async function handleStartTotpSetup() {
    try {
      const data = await setupTwoFactor(token);
      setTotpSetupData(data);
      setSettingUpMethod("totp");
      setConfirmCode("");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleStartEmailSetup() {
    try {
      const data = await setupEmailTwoFactor(token);
      setEmailMaskedAddress(data.masked_email);
      setSettingUpMethod("email");
      setConfirmCode("");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleConfirmSetup(e) {
    e.preventDefault();
    setIsConfirming(true);
    try {
      if (settingUpMethod === "totp") {
        await enableTwoFactor(token, confirmCode);
      } else {
        await enableEmailTwoFactor(token, confirmCode);
      }
      showToast("Two-factor authentication is now on.", "success");
      const enabledMethod = settingUpMethod;
      resetSetupState();
      updateUser({ totp_enabled: true, two_factor_method: enabledMethod });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsConfirming(false);
    }
  }

  async function handleDisable(e) {
    e.preventDefault();
    setIsDisabling(true);
    try {
      await disableTwoFactor(token, disablePassword);
      showToast("Two-factor authentication is now off.", "success");
      setShowDisableForm(false);
      setDisablePassword("");
      updateUser({ totp_enabled: false, two_factor_method: "totp" });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsDisabling(false);
    }
  }

  if (isLoading) return null;

  return (
    <div>
      <h2 className="page-title">Security</h2>

      <div className="card" style={{ maxWidth: "500px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <strong style={{ fontSize: "14px" }}>Two-Factor Authentication</strong>
          <span
            style={{
              fontSize: "12px",
              fontWeight: 600,
              color: status?.totp_enabled ? "var(--status-delivered)" : "var(--text-secondary)",
            }}
          >
            {status?.totp_enabled
              ? `Enabled (${status.two_factor_method === "email" ? "email code" : "authenticator app"})`
              : "Disabled"}
          </span>
        </div>
        <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "14px" }}>
          Adds a second step at login, on top of your password — either a code from an
          authenticator app, or a code emailed to you.
        </p>

        {status?.totp_enabled && !showDisableForm && (
          <button className="btn-danger-outline" onClick={() => setShowDisableForm(true)}>
            Turn off two-factor authentication
          </button>
        )}

        {status?.totp_enabled && showDisableForm && (
          <form onSubmit={handleDisable}>
            <div className="auth-field">
              <label htmlFor="tfa-disable-password">Confirm your password to turn it off</label>
              <PasswordInput
                id="tfa-disable-password"
                className="input"
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
                style={{ width: "100%" }}
                required
                autoFocus
              />
            </div>
            <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
              <button type="submit" className="btn-danger-outline" disabled={isDisabling}>
                {isDisabling ? "Turning off..." : "Confirm & Turn Off"}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setShowDisableForm(false);
                  setDisablePassword("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {!status?.totp_enabled && !settingUpMethod && (
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={handleStartTotpSetup}>
              Set up with an authenticator app
            </button>
            <button className="btn" onClick={handleStartEmailSetup}>
              Set up with email codes
            </button>
          </div>
        )}

        {!status?.totp_enabled && settingUpMethod === "totp" && totpSetupData && (
          <div>
            <p style={{ fontSize: "12.5px", marginBottom: "6px" }}>
              Open an <strong>authenticator app</strong> (Google Authenticator, Microsoft
              Authenticator, Authy, or 1Password) and use its "Scan QR code" option to scan this.
            </p>
            <p style={{ fontSize: "11.5px", color: "var(--text-muted)", marginBottom: "10px" }}>
              Don't use your phone's regular camera or Google Lens/Search on it — those will just
              try to web-search the code's text instead of adding it to an authenticator, since
              they don't recognize this type of QR code.
            </p>
            <img
              src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(totpSetupData.otpauth_uri)}`}
              alt="Two-factor authentication QR code"
              style={{ display: "block", marginBottom: "10px", borderRadius: "6px" }}
            />
            <p style={{ fontSize: "11.5px", color: "var(--text-muted)", marginBottom: "12px" }}>
              Can't scan it? Enter this key manually in the app instead:{" "}
              <span className="mono" style={{ fontWeight: 600 }}>{totpSetupData.secret}</span>
            </p>
            <form onSubmit={handleConfirmSetup}>
              <div className="auth-field">
                <label htmlFor="tfa-code-totp">6-digit code from the app</label>
                <input
                  id="tfa-code-totp"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={confirmCode}
                  onChange={(e) => setConfirmCode(e.target.value.replace(/\D/g, ""))}
                  required
                  autoFocus
                />
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button type="submit" className="btn btn-primary" disabled={isConfirming || confirmCode.length !== 6}>
                  {isConfirming ? "Confirming..." : "Confirm & Enable"}
                </button>
                <button type="button" className="btn" onClick={resetSetupState}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {!status?.totp_enabled && settingUpMethod === "email" && (
          <div>
            <p style={{ fontSize: "12.5px", marginBottom: "12px" }}>
              We sent a 6-digit code to <strong>{emailMaskedAddress}</strong> to confirm you can
              receive it. Enter it below to turn email codes on.
            </p>
            <form onSubmit={handleConfirmSetup}>
              <div className="auth-field">
                <label htmlFor="tfa-code-email">6-digit code from your email</label>
                <input
                  id="tfa-code-email"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={confirmCode}
                  onChange={(e) => setConfirmCode(e.target.value.replace(/\D/g, ""))}
                  required
                  autoFocus
                />
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button type="submit" className="btn btn-primary" disabled={isConfirming || confirmCode.length !== 6}>
                  {isConfirming ? "Confirming..." : "Confirm & Enable"}
                </button>
                <button type="button" className="btn" onClick={resetSetupState}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
