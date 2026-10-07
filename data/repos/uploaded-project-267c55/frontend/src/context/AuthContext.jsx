import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { signupRequest, loginRequest, verifyTwoFactorLoginRequest, refreshTokenRequest, logoutRequest, exchangeOAuthLoginCode, demoLoginRequest } from "../services/authApi";

const AuthContext = createContext(null);

const STORAGE_KEY = "delivery_sync_auth";

// Access tokens are short-lived (30 minutes server-side — see
// services/auth.py) specifically so a leaked one stops being useful
// quickly. This timer proactively trades the refresh token for a new
// access/refresh pair well before that expiry, so the person never
// actually feels the 30-minute window — the session just keeps
// renewing itself quietly in the background for as long as the
// refresh token itself stays valid (30 days, or until explicit logout).
const REFRESH_INTERVAL_MS = 20 * 60 * 1000; // 20 minutes — comfortably inside the 30-minute access-token life

/**
 * Provides authentication state (current user, token) and actions
 * (login, signup, logout) to the whole app.
 *
 * Session is persisted to localStorage so refreshing the page doesn't log
 * the user out. The access token itself now expires after 30 minutes,
 * but that's invisible in normal use — see REFRESH_INTERVAL_MS above.
 * A session only actually ends when: the person logs out, the refresh
 * token itself expires (30 days of no use), or the server revokes it
 * (e.g. reuse-detection after a stolen token — see routes/auth.py's
 * /refresh docstring).
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [refreshToken, setRefreshToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTokenRef = useRef(null);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      setUser(parsed.user);
      setToken(parsed.token);
      setRefreshToken(parsed.refreshToken || null);
      refreshTokenRef.current = parsed.refreshToken || null;
    }
    setIsLoading(false);
  }, []);

  // Proactive background refresh — see REFRESH_INTERVAL_MS above.
  useEffect(() => {
    if (!refreshToken) return;

    const intervalId = setInterval(async () => {
      try {
        const data = await refreshTokenRequest(refreshTokenRef.current);
        persistTokens(data.access_token, data.refresh_token);
      } catch {
        // Refresh token expired or was revoked server-side — nothing
        // more this session can do; clear it so the person is prompted
        // to log in again next time they try an authenticated action.
        logout();
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  function persistSession(newToken, newRefreshToken, newUser) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: newToken, refreshToken: newRefreshToken, user: newUser }));
    setToken(newToken);
    setRefreshToken(newRefreshToken);
    refreshTokenRef.current = newRefreshToken;
    setUser(newUser);
  }

  function persistTokens(newToken, newRefreshToken) {
    setToken(newToken);
    setRefreshToken(newRefreshToken);
    refreshTokenRef.current = newRefreshToken;
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...parsed, token: newToken, refreshToken: newRefreshToken }));
    }
  }

  async function login(username, password) {
    const data = await loginRequest({ username, password });
    if (data.requires_2fa) {
      // Password was correct, but this account has 2FA on — hand back
      // the challenge token (plus which method, and a masked email if
      // that's the method) so LoginPage can prompt for the right kind
      // of code next, instead of persisting a session that doesn't
      // exist yet.
      return {
        requires_2fa: true,
        challenge_token: data.challenge_token,
        two_factor_method: data.two_factor_method,
        masked_email: data.masked_email,
      };
    }
    persistSession(data.access_token, data.refresh_token, data.user);
    return data.user;
  }

  async function completeTwoFactorLogin(challengeToken, code) {
    const data = await verifyTwoFactorLoginRequest(challengeToken, code);
    persistSession(data.access_token, data.refresh_token, data.user);
    return data.user;
  }

  async function completeOAuthLogin(oauthCode) {
    const data = await exchangeOAuthLoginCode(oauthCode);
    persistSession(data.access_token, data.refresh_token, data.user);
    return data.user;
  }

  async function demoLogin() {
    const data = await demoLoginRequest();
    persistSession(data.access_token, data.refresh_token, data.user);
    return data.user;
  }

  async function signup({ username, email, password, role, display_name, org_name, invite_code, captcha_token }) {
    const data = await signupRequest({ username, email, password, role, display_name, org_name, invite_code, captcha_token });
    persistSession(data.access_token, data.refresh_token, data.user);
    return data; // includes org_invite_code when a NEW org was just created
  }

  function logout() {
    if (refreshTokenRef.current) {
      logoutRequest(refreshTokenRef.current); // best-effort server-side revocation, see authApi.js
    }
    localStorage.removeItem(STORAGE_KEY);
    setUser(null);
    setToken(null);
    setRefreshToken(null);
    refreshTokenRef.current = null;
  }

  function updateUser(patch) {
    setUser((prev) => {
      if (!prev) return prev;
      const next = { ...prev, ...patch };
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...parsed, user: next }));
      }
      return next;
    });
  }

  const value = { user, token, isLoading, login, completeTwoFactorLogin, completeOAuthLogin, demoLogin, signup, logout, updateUser };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
