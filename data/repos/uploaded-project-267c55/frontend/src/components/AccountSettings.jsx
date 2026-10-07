import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { updateMyStaffProfile, changeMyStaffPassword, setMyStaffPassword } from "../services/api";
import PasswordInput from "./PasswordInput";

/**
 * Self-service "my account" settings for a logged-in staff user
 * (admin/dispatcher/agent) — edit your own display name/email, and
 * change your own password. Mirrors CustomerDashboard.jsx's
 * ProfilePanel exactly, since it's the same feature for the other side
 * of the app: before this existed, staff had no way to do either of
 * these without an admin acting on their account for them (deactivate/
 * reactivate/reset-password in AdminPanel.jsx), which doesn't help you
 * change your own password while you're already logged in and know it.
 *
 * Lives at the "account" nav entry, next to "Security" (TwoFactorSettings) —
 * deliberately a separate page rather than merged into it, since 2FA
 * setup and "who am I / what's my password" are different concerns a
 * user might visit independently.
 */
export default function AccountSettings() {
  const { token, user, updateUser } = useAuth();

  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState(null);
  const [profileSuccess, setProfileSuccess] = useState(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState(null);
  const [passwordSuccess, setPasswordSuccess] = useState(null);

  const [newPasswordToSet, setNewPasswordToSet] = useState("");
  const [isSettingPassword, setIsSettingPassword] = useState(false);
  const [setPasswordFormError, setSetPasswordFormError] = useState(null);
  const [setPasswordFormSuccess, setSetPasswordFormSuccess] = useState(null);

  async function handleSaveProfile(e) {
    e.preventDefault();
    setProfileError(null);
    setProfileSuccess(null);
    setIsSavingProfile(true);
    try {
      const updated = await updateMyStaffProfile(token, {
        display_name: displayName.trim(),
        email: email.trim(),
      });
      updateUser({ display_name: updated.display_name, email: updated.email });
      setProfileSuccess("Profile updated.");
    } catch (err) {
      setProfileError(err.message);
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleChangePassword(e) {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);
    setIsChangingPassword(true);
    try {
      await changeMyStaffPassword(token, currentPassword, newPassword);
      setPasswordSuccess("Password changed.");
      setCurrentPassword("");
      setNewPassword("");
    } catch (err) {
      setPasswordError(err.message);
    } finally {
      setIsChangingPassword(false);
    }
  }

  async function handleSetPassword(e) {
    e.preventDefault();
    setSetPasswordFormError(null);
    setSetPasswordFormSuccess(null);
    setIsSettingPassword(true);
    try {
      await setMyStaffPassword(token, newPasswordToSet);
      setSetPasswordFormSuccess("Password set. You can now log in with it, in addition to Google Sign-In.");
      setNewPasswordToSet("");
      updateUser({ has_usable_password: true });
    } catch (err) {
      setSetPasswordFormError(err.message);
    } finally {
      setIsSettingPassword(false);
    }
  }

  return (
    <div>
      <h2 className="page-title">My Account</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "16px", maxWidth: "500px" }}>
        <div className="card">
          <strong style={{ fontSize: "13.5px" }}>Profile</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px", marginBottom: "12px" }}>
            Your username ({user.username}) is fixed — it's what you log in with. Your display
            name and email can be changed anytime.
          </p>
          <form onSubmit={handleSaveProfile}>
            <div className="auth-field">
              <label htmlFor="account-display-name">Display Name</label>
              <input
                id="account-display-name"
                className="input"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </div>
            <div className="auth-field">
              <label htmlFor="account-email">Email</label>
              <input
                id="account-email"
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            {profileError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{profileError}</p>}
            {profileSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{profileSuccess}</p>}
            <button type="submit" className="btn btn-primary" disabled={isSavingProfile}>
              {isSavingProfile ? "Saving..." : "Save Changes"}
            </button>
          </form>
        </div>

        {user.has_usable_password === false ? (
          <div className="card">
            <strong style={{ fontSize: "13.5px" }}>Set a Password</strong>
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px", marginBottom: "12px" }}>
              Your account currently only logs in via Google Sign-In. Add a password so you still
              have a way in if Google Sign-In is ever unavailable.
            </p>
            <form onSubmit={handleSetPassword}>
              <div className="auth-field">
                <label htmlFor="account-set-new-password">New Password</label>
                <PasswordInput
                  id="account-set-new-password"
                  className="input"
                  value={newPasswordToSet}
                  onChange={(e) => setNewPasswordToSet(e.target.value)}
                  required
                  minLength={6}
                />
              </div>
              {setPasswordFormError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{setPasswordFormError}</p>}
              {setPasswordFormSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{setPasswordFormSuccess}</p>}
              <button type="submit" className="btn btn-primary" disabled={isSettingPassword}>
                {isSettingPassword ? "Setting..." : "Set Password"}
              </button>
            </form>
          </div>
        ) : (
          <div className="card">
            <strong style={{ fontSize: "13.5px" }}>Change Password</strong>
            <form onSubmit={handleChangePassword} style={{ marginTop: "12px" }}>
              <div className="auth-field">
                <label htmlFor="account-current-password">Current Password</label>
                <PasswordInput
                  id="account-current-password"
                  className="input"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                />
              </div>
              <div className="auth-field">
                <label htmlFor="account-change-new-password">New Password</label>
                <PasswordInput
                  id="account-change-new-password"
                  className="input"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                />
              </div>
              {passwordError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{passwordError}</p>}
              {passwordSuccess && <p style={{ color: "var(--status-delivered)", fontSize: "12px" }}>{passwordSuccess}</p>}
              <button type="submit" className="btn btn-primary" disabled={isChangingPassword}>
                {isChangingPassword ? "Changing..." : "Change Password"}
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
