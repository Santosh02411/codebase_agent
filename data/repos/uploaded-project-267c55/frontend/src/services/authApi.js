/**
 * Handles signup/login HTTP calls to the backend's /auth endpoints.
 */

const API_BASE_URL = "http://127.0.0.1:8000";

export async function signupRequest({ username, email, password, role, display_name, org_name, invite_code, captcha_token }) {
  const response = await fetch(`${API_BASE_URL}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password, role, display_name, org_name, invite_code, captcha_token }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Signup failed.");
  }
  return data; // { access_token, refresh_token, token_type, user, org_invite_code }
}

export async function loginRequest({ username, password }) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Login failed.");
  }
  return data; // { access_token, refresh_token, user } OR { requires_2fa: true, challenge_token }
}

export async function demoLoginRequest() {
  const response = await fetch(`${API_BASE_URL}/auth/demo-login`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "The demo isn't available right now. Please try again shortly.");
  }
  return data; // { access_token, refresh_token, user }
}

export async function getGoogleOAuthLoginUrl({ orgName, inviteCode, role } = {}) {
  const params = new URLSearchParams();
  if (orgName) params.set("org_name", orgName);
  if (inviteCode) params.set("invite_code", inviteCode);
  if (role) params.set("role", role);
  const qs = params.toString();
  const response = await fetch(`${API_BASE_URL}/auth/oauth/google/login${qs ? `?${qs}` : ""}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Google sign-in isn't available right now.");
  }
  return data.authorization_url;
}

export async function exchangeOAuthLoginCode(code) {
  const response = await fetch(`${API_BASE_URL}/auth/oauth/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Google sign-in failed.");
  }
  return data; // { access_token, refresh_token, user }
}

export async function verifyTwoFactorLoginRequest(challengeToken, code) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/verify-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_token: challengeToken, code }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Verification failed.");
  }
  return data; // { access_token, refresh_token, token_type, user }
}

export async function refreshTokenRequest(refreshToken) {
  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Session refresh failed.");
  }
  return data; // { access_token, refresh_token }
}

export async function logoutRequest(refreshToken) {
  // Best-effort — a failed logout call server-side should never block
  // the frontend from clearing its own local session.
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // ignore — see comment above
  }
}

export async function verifyEmailRequest(token) {
  const response = await fetch(`${API_BASE_URL}/auth/verify-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Verification failed.");
  return data; // { message }
}

export async function resendVerificationRequest(token) {
  const response = await fetch(`${API_BASE_URL}/auth/resend-verification`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to resend verification email.");
  return data; // { message }
}

export async function forgotPasswordRequest(email, captchaToken) {
  const response = await fetch(`${API_BASE_URL}/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, captcha_token: captchaToken }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data; // { message }
}

export async function resetPasswordRequest(token, newPassword) {
  const response = await fetch(`${API_BASE_URL}/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Reset failed.");
  }
  return data; // { message }
}

export async function customerRefreshTokenRequest(refreshToken) {
  const response = await fetch(`${API_BASE_URL}/customer/refresh-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Session refresh failed.");
  return data; // { access_token, refresh_token }
}

export async function customerLogoutRequest(refreshToken) {
  try {
    await fetch(`${API_BASE_URL}/customer/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // best-effort, see logoutRequest's comment above
  }
}

export async function customerVerifyEmailRequest(token) {
  const response = await fetch(`${API_BASE_URL}/customer/verify-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Verification failed.");
  return data; // { message }
}

export async function customerResendVerificationRequest(token) {
  const response = await fetch(`${API_BASE_URL}/customer/resend-verification`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to resend verification email.");
  return data; // { message }
}

export async function customerForgotPasswordRequest(email, captchaToken) {
  const response = await fetch(`${API_BASE_URL}/customer/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, captcha_token: captchaToken }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data; // { message }
}

export async function customerResetPasswordRequest(token, newPassword) {
  const response = await fetch(`${API_BASE_URL}/customer/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Reset failed.");
  }
  return data; // { message }
}

export async function getCustomerGoogleOAuthLoginUrl() {
  const response = await fetch(`${API_BASE_URL}/customer/oauth/google/login`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Google sign-in isn't available right now.");
  }
  return data.authorization_url;
}

export async function exchangeCustomerOAuthLoginCode(code) {
  const response = await fetch(`${API_BASE_URL}/customer/oauth/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Google sign-in failed.");
  }
  return data; // { access_token, refresh_token, customer }
}
