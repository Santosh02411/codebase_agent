import React, { createContext, useContext, useEffect, useState } from "react";
import * as api from "../services/api";
import { stopBackgroundLocationTracking } from "../locationTask";
import { setActiveUser, clearAll as clearOfflineCache } from "../services/offlineStore";
import { unregisterCurrentDeviceFromPushNotifications } from "../services/pushNotifications";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  function applyUser(profile) {
    setActiveUser(profile.id);
    setUser(profile);
  }

  useEffect(() => {
    (async () => {
      const token = await api.getAccessToken();
      if (token) {
        try {
          const profile = await api.fetchMyProfile();
          applyUser(profile);
        } catch (err) {
          if (api.isNetworkError(err)) {
            // Offline at app launch — a real, expected scenario for an
            // agent starting their shift with no signal, and NOT the
            // same thing as an expired/invalid token. Restore the
            // session from the last profile fetchMyProfile successfully
            // cached, so the agent can still see their cached
            // deliveries and queue offline updates — logging them out
            // here would defeat the entire point of offline support.
            const cached = await api.getCachedProfile();
            if (cached) {
              applyUser(cached);
            }
          } else {
            // A genuine auth failure (expired/invalid/revoked token) —
            // same "fall back to logged out" behavior as the web app's
            // own AuthContext.
            await api.clearTokens();
          }
        }
      }
      setIsLoading(false);
    })();
  }, []);

  async function login(username, password) {
    const data = await api.login(username, password);
    if (data.requires_2fa) {
      return data; // { requires_2fa: true, challenge_token } — LoginScreen handles the next step
    }
    await api.saveTokens(data.access_token, data.refresh_token);
    applyUser(data.user);
    return data;
  }

  async function completeTwoFactorLogin(challengeToken, code) {
    const data = await api.verifyTwoFactorLogin(challengeToken, code);
    await api.saveTokens(data.access_token, data.refresh_token);
    applyUser(data.user);
    return data.user;
  }

  async function signup(fields) {
    const data = await api.signup(fields);
    await api.saveTokens(data.access_token, data.refresh_token);
    applyUser(data.user);
    return data; // includes org_invite_code when a new org was just created
  }

  async function logout() {
    await unregisterCurrentDeviceFromPushNotifications();
    await stopBackgroundLocationTracking();
    await api.clearTokens();
    await api.clearCachedProfile();
    await clearOfflineCache();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, completeTwoFactorLogin, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
