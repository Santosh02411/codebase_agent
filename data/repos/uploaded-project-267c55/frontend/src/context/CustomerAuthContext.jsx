import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { customerRefreshTokenRequest, customerLogoutRequest, exchangeCustomerOAuthLoginCode } from "../services/authApi";

const CustomerAuthContext = createContext(null);
const STORAGE_KEY = "delivery_sync_customer_auth";
const API_BASE_URL = "http://127.0.0.1:8000";

// See AuthContext.jsx's identical constant for the full explanation —
// same short-access-token / long-refresh-token / proactive-renewal
// design, mirrored here for the customer side.
const REFRESH_INTERVAL_MS = 20 * 60 * 1000;

/**
 * Customer session state — completely separate from the staff
 * AuthContext (different localStorage key, different backend endpoints,
 * different token shape). A customer and a staff member could even be
 * logged in simultaneously in two different tabs without interfering
 * with each other.
 */
export function CustomerAuthProvider({ children }) {
  const [customer, setCustomer] = useState(null);
  const [token, setToken] = useState(null);
  const [refreshToken, setRefreshToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTokenRef = useRef(null);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      setCustomer(parsed.customer);
      setToken(parsed.token);
      setRefreshToken(parsed.refreshToken || null);
      refreshTokenRef.current = parsed.refreshToken || null;
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    if (!refreshToken) return;

    const intervalId = setInterval(async () => {
      try {
        const data = await customerRefreshTokenRequest(refreshTokenRef.current);
        persistTokens(data.access_token, data.refresh_token);
      } catch {
        logout();
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  function persistSession(newToken, newRefreshToken, newCustomer) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: newToken, refreshToken: newRefreshToken, customer: newCustomer }));
    setToken(newToken);
    setRefreshToken(newRefreshToken);
    refreshTokenRef.current = newRefreshToken;
    setCustomer(newCustomer);
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

  async function signup(email, password, name, captchaToken) {
    const response = await fetch(`${API_BASE_URL}/customer/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name, captcha_token: captchaToken }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Signup failed.");
    persistSession(data.access_token, data.refresh_token, data.customer);
    return data.customer;
  }

  async function login(email, password) {
    const response = await fetch(`${API_BASE_URL}/customer/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Login failed.");
    persistSession(data.access_token, data.refresh_token, data.customer);
    return data.customer;
  }

  async function completeOAuthLogin(oauthCode) {
    const data = await exchangeCustomerOAuthLoginCode(oauthCode);
    persistSession(data.access_token, data.refresh_token, data.customer);
    return data.customer;
  }

  function logout() {
    if (refreshTokenRef.current) {
      customerLogoutRequest(refreshTokenRef.current); // best-effort server-side revocation
    }
    localStorage.removeItem(STORAGE_KEY);
    setCustomer(null);
    setToken(null);
    setRefreshToken(null);
    refreshTokenRef.current = null;
  }

  function updateCustomer(patch) {
    setCustomer((prev) => {
      if (!prev) return prev;
      const next = { ...prev, ...patch };
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...parsed, customer: next }));
      }
      return next;
    });
  }

  return (
    <CustomerAuthContext.Provider value={{ customer, token, isLoading, signup, login, completeOAuthLogin, logout, updateCustomer }}>
      {children}
    </CustomerAuthContext.Provider>
  );
}

export function useCustomerAuth() {
  const context = useContext(CustomerAuthContext);
  if (!context) {
    throw new Error("useCustomerAuth must be used within a CustomerAuthProvider");
  }
  return context;
}
