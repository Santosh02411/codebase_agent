/**
 * Talks to the exact same backend as the web app (backend/main.py) —
 * no mobile-specific API surface exists or is needed. Every endpoint
 * used here (POST /auth/login, GET /deliveries/mine, PATCH
 * /deliveries/{id}, PUT /users/me/location) already exists, is already
 * tested (see backend/tests/), and is already used by the web
 * frontend — this file is a second, independent CLIENT of that same
 * API, not a new backend surface.
 *
 * The one thing genuinely different from the web app: PUT
 * /users/me/location gets called from a BACKGROUND task (see
 * ../locationTask.js) that keeps running while this app is
 * backgrounded or the phone is locked — something no browser tab can
 * do (see that file's own docstring for exactly why this needs a
 * native app at all).
 */

import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { cacheDeliveries, getCachedDeliveries, getCachedDelivery, queueStatusUpdate } from "./offlineStore";

// Change this to your deployed backend's URL for a real device build —
// 10.0.2.2 is the special alias the Android emulator uses to reach
// "localhost" on the machine running the emulator; a physical device
// needs your machine's real LAN IP instead (e.g. http://192.168.1.42:8000),
// since "localhost" on a phone means the phone itself.
export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || "http://10.0.2.2:8000";

/**
 * Thin wrapper around every `fetch()` call in this file. The one thing
 * it does that a bare `fetch()` doesn't: when the request never
 * reaches a server at all (wrong/unreachable API_BASE_URL, backend not
 * running, phone and computer on different networks — by far the most
 * common failure mode reported against this app), `fetch()` itself
 * throws a raw `TypeError` whose message ("Network request failed" on
 * React Native, something similarly opaque on web) tells a user
 * nothing actionable. Every screen's catch block just does
 * `setError(err.message)` and shows that message as-is (see
 * LoginScreen.js, SignupScreen.js, etc.) — so that opaque message was
 * literally the only thing on screen. This rewrites JUST that one
 * failure mode into something someone can actually act on, quoting
 * the exact URL that was tried so a wrong EXPO_PUBLIC_API_BASE_URL is
 * obvious rather than guessed at. A real HTTP error response (401,
 * 404, 500, validation errors) is untouched — those already carry a
 * useful `detail` message from the backend, handled by each function
 * below exactly as before.
 */
async function apiFetch(url, options) {
  try {
    return await fetch(url, options);
  } catch (err) {
    throw new Error(
      `Can't reach the server at ${API_BASE_URL}. Check that the backend is running, that ` +
      `EXPO_PUBLIC_API_BASE_URL is set correctly for how you're testing this app (see README.md's ` +
      `Setup section — 10.0.2.2 only works from the Android emulator, a real phone needs your ` +
      `computer's LAN IP), and that your phone and computer are on the same Wi-Fi network.`
    );
  }
}

const TOKEN_KEY = "delivery_sync_access_token";
const REFRESH_TOKEN_KEY = "delivery_sync_refresh_token";

export async function saveTokens(accessToken, refreshToken) {
  await SecureStore.setItemAsync(TOKEN_KEY, accessToken);
  if (refreshToken) {
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken);
  }
}

export async function getAccessToken() {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function getRefreshToken() {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export async function clearTokens() {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
}

// Cached alongside the tokens (AsyncStorage, not SecureStore — a
// profile isn't sensitive the way a token is) so a session can be
// restored while OFFLINE at app launch. Without this, opening the
// app with no connectivity would look identical to an expired/invalid
// token and log the agent out — exactly the scenario an agent
// starting their shift with no signal would actually hit, undermining
// the whole point of this app's offline support.
const CACHED_PROFILE_KEY = "delivery_sync_cached_profile";

async function cacheProfile(profile) {
  await AsyncStorage.setItem(CACHED_PROFILE_KEY, JSON.stringify(profile));
}

export async function getCachedProfile() {
  const raw = await AsyncStorage.getItem(CACHED_PROFILE_KEY);
  return raw ? JSON.parse(raw) : null;
}

export async function clearCachedProfile() {
  await AsyncStorage.removeItem(CACHED_PROFILE_KEY);
}

async function authHeaders() {
  const token = await getAccessToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Staff login — identical request/response shape to the web app's
 * loginRequest() in frontend/src/services/authApi.js. Only agents are
 * a realistic audience for this app (dispatchers/admins need the full
 * console, not a phone screen), but the backend doesn't distinguish —
 * a dispatcher COULD log in here too, they'd just see an empty
 * delivery list since none would be assigned to them.
 */
export async function login(username, password) {
  const response = await apiFetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Login failed.");
  }
  if (data.user) await cacheProfile(data.user);
  return data; // { access_token, refresh_token, user } OR { requires_2fa: true, challenge_token }
}

/**
 * Same POST /auth/signup the web app's SignupPage.jsx calls. Provide
 * exactly one of orgName (create a new org, becoming its admin
 * automatically) or inviteCode (join an existing one as `role`) — see
 * UserSignup's own docstring in backend/app/models/user.py.
 * captchaToken comes from <Captcha /> (see ../components/Captcha.js) —
 * omit it (or leave it null) and this still works exactly as before,
 * since the backend only actually enforces the check when
 * RECAPTCHA_SECRET_KEY is configured server-side (services/captcha.py).
 */
export async function signup({ username, email, password, displayName, role, orgName, inviteCode, captchaToken }) {
  const response = await apiFetch(`${API_BASE_URL}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username, email, password,
      display_name: displayName,
      role,
      org_name: orgName || undefined,
      invite_code: inviteCode || undefined,
      captcha_token: captchaToken || undefined,
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Signup failed.");
  }
  if (data.user) await cacheProfile(data.user);
  return data; // { access_token, refresh_token, user, org_invite_code }
}

/**
 * Same POST /auth/forgot-password the web app's ForgotPasswordPage.jsx
 * calls. The reset link in that email opens the web app by default,
 * but now also carries a `deliverysync://reset-password?token=...`
 * "open in app" option on that page (mobile browsers) which lands on
 * this app's own ResetPasswordScreen (see AppNavigator/App.js's deep
 * link handling and ../screens/ResetPasswordScreen.js) — the second
 * half of the flow this app previously had no screen for at all.
 * captchaToken comes from <Captcha /> the same way signup()'s does.
 */
export async function forgotPassword(email, captchaToken) {
  const response = await apiFetch(`${API_BASE_URL}/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, captcha_token: captchaToken || undefined }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data; // { message }
}

/**
 * Same POST /auth/reset-password the web app's ResetPasswordPage.jsx
 * calls to complete the flow forgotPassword() above started — given a
 * valid, unused, unexpired token (lifted from the deep-link URL by
 * App.js), sets the new password. No auth header: a password reset is
 * deliberately usable while logged out (that's the whole point).
 */
export async function resetPassword(token, newPassword) {
  const response = await apiFetch(`${API_BASE_URL}/auth/reset-password`, {
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

export async function verifyTwoFactorLogin(challengeToken, code) {
  const response = await apiFetch(`${API_BASE_URL}/auth/2fa/verify-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_token: challengeToken, code }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Verification failed.");
  }
  if (data.user) await cacheProfile(data.user);
  return data;
}

/**
 * True for the specific case React Native's fetch throws when there's
 * genuinely no network path to the server at all (airplane mode, no
 * signal, wrong LAN IP) — as opposed to the server itself responding
 * with an error (bad request, permission denied, validation failure),
 * which comes back as a normal Response with response.ok === false
 * and should NOT be treated as "retry later", since retrying an
 * actual rejection changes nothing. React Native's underlying fetch
 * polyfill throws a TypeError with this exact message for the
 * network-unreachable case — matched by message rather than an error
 * code because neither the Fetch spec nor React Native expose a more
 * structured way to distinguish it.
 */
export function isNetworkError(error) {
  return error instanceof TypeError && /network request failed/i.test(error.message);
}

export async function fetchMyDeliveries() {
  try {
    const response = await apiFetch(`${API_BASE_URL}/deliveries/mine`, {
      headers: await authHeaders(),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Failed to load deliveries.");
    await cacheDeliveries(data);
    return { fromCache: false, deliveries: data };
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    // Offline — fall back to whatever was last successfully fetched
    // (or already-queued locally), rather than a blank error screen.
    return { fromCache: true, deliveries: await getCachedDeliveries() };
  }
}

export async function getDelivery(deliveryId) {
  try {
    const response = await apiFetch(`${API_BASE_URL}/deliveries/${deliveryId}`, {
      headers: await authHeaders(),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Failed to load delivery.");
    await cacheDeliveries([data]);
    return { fromCache: false, delivery: data };
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    const cached = await getCachedDelivery(deliveryId);
    if (!cached) throw new Error("This delivery hasn't been loaded yet and you're offline.");
    return { fromCache: true, delivery: cached };
  }
}

/**
 * Same PATCH /deliveries/{id} the web app's own online-mode calls
 * hit — `updated_at` is required by the backend (see
 * DeliveryRecordUpdate in backend/app/models/delivery.py) as the
 * client-supplied timestamp its conflict-resolution logic compares
 * against.
 *
 * The genuinely new behavior versus the web app's direct PATCH call:
 * if this fails specifically because there's no network path to the
 * server at all, the change is applied to the local cache and queued
 * for ../offlineSync.js to actually send (via POST /sync, the same
 * endpoint the web app's own offline queue already uses) the next
 * time connectivity is available — instead of just failing with an
 * error and losing the agent's update. A genuine server-side
 * rejection (validation failure, permission denied) is NOT queued —
 * see isNetworkError's own docstring for why that distinction matters.
 *
 * `delivery` is the full current delivery object (from a prior fetch),
 * not just its id — a complete record is required to build a valid
 * POST /sync payload later (agent_id, org_id, created_at, zone, etc. —
 * see backend/app/routes/sync.py's SyncRecordIn), not just the one
 * changed field.
 */
export async function updateDeliveryStatus(delivery, status, extra = {}) {
  const patch = { status, updated_at: new Date().toISOString(), ...extra };
  try {
    const response = await apiFetch(`${API_BASE_URL}/deliveries/${delivery.id}`, {
      method: "PATCH",
      headers: await authHeaders(),
      body: JSON.stringify(patch),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Failed to update delivery.");
    await cacheDeliveries([data]);
    return { queued: false, delivery: data };
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    const queuedRecord = await queueStatusUpdate(delivery.id, patch);
    return { queued: true, delivery: queuedRecord };
  }
}

/**
 * Same GET /deliveries/reason-codes/active the web app's failed-
 * attempt picker uses — org-scoped, active-only reason codes an agent
 * can pick from when marking a delivery as a failed attempt (see
 * backend/app/models/failed_delivery_reason.py).
 */
export async function fetchActiveReasonCodes() {
  const response = await apiFetch(`${API_BASE_URL}/deliveries/reason-codes/active`, {
    headers: await authHeaders(),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load reason codes.");
  return data;
}

/**
 * Same POST /deliveries/{id}/pod the web app's proof-of-delivery
 * capture calls — does NOT itself change the delivery's status; the
 * subsequent PATCH /deliveries/{id} (via updateDeliveryStatus above,
 * with status="delivered") is what actually marks it delivered, and
 * that call will fail with a clear message if the organization
 * requires POD fields this submission didn't include (see
 * backend/app/services/pod.py's missing_pod_requirements — this app
 * doesn't try to predict those requirements client-side, it just
 * surfaces whatever the backend says is missing).
 */
export async function submitProofOfDelivery(deliveryId, { recipientName, signatureDataUrl, photoDataUrl, latitude, longitude, notes } = {}) {
  const response = await apiFetch(`${API_BASE_URL}/deliveries/${deliveryId}/pod`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({
      recipient_name: recipientName || undefined,
      signature_data_url: signatureDataUrl || undefined,
      photo_data_url: photoDataUrl || undefined,
      latitude: latitude != null ? String(latitude) : undefined,
      longitude: longitude != null ? String(longitude) : undefined,
      notes: notes || undefined,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit proof of delivery.");
  return data;
}

/**
 * Same GET/POST /deliveries/{id}/messages the web app's per-delivery
 * chat thread uses — this IS the "dispatcher ↔ agent messaging"
 * feature (see backend/app/models/delivery_message.py's own comment:
 * "the original agent<->dispatcher thread", later extended to include
 * customers too). No real-time transport on the mobile side yet (no
 * websocket client) — MessagesScreen polls instead; see that screen's
 * own comment for why that's an acceptable, honestly-scoped trade-off.
 */
export async function fetchDeliveryMessages(deliveryId) {
  const response = await apiFetch(`${API_BASE_URL}/deliveries/${deliveryId}/messages`, {
    headers: await authHeaders(),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load messages.");
  return data;
}

export async function sendDeliveryMessage(deliveryId, message) {
  const response = await apiFetch(`${API_BASE_URL}/deliveries/${deliveryId}/messages`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ message }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send message.");
  return data;
}

/**
 * Same GET /scan/{code} the web app's scan flow uses to resolve a
 * scanned QR code back to a delivery — the code IS the delivery's own
 * id (see backend/app/models/scan.py's own comment), so this just
 * confirms it's real and fetches the delivery in one call.
 */
export async function resolveScannedCode(code) {
  const response = await apiFetch(`${API_BASE_URL}/scan/${encodeURIComponent(code)}`, {
    headers: await authHeaders(),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "That code doesn't match any delivery.");
  return data;
}

export async function recordScan(deliveryId, scanType) {
  const response = await apiFetch(`${API_BASE_URL}/deliveries/${deliveryId}/scan`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ scan_type: scanType }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record scan.");
  return data;
}

/**
 * The one call this app makes that the web app effectively can't make
 * reliably in the background — see ../locationTask.js.
 */
export async function pushMyLocation(latitude, longitude) {
  const response = await apiFetch(`${API_BASE_URL}/users/me/location`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify({ latitude, longitude }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to push location.");
  }
  return response.json();
}

export async function registerExpoPushToken(token) {
  const response = await apiFetch(`${API_BASE_URL}/users/me/expo-push-token`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to register for push notifications.");
  }
  return response.json();
}

export async function unregisterExpoPushToken(token) {
  const response = await apiFetch(`${API_BASE_URL}/users/me/expo-push-token`, {
    method: "DELETE",
    headers: await authHeaders(),
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to unregister from push notifications.");
  }
  return response.json();
}

export async function fetchMyProfile() {
  const response = await apiFetch(`${API_BASE_URL}/auth/me`, {
    headers: await authHeaders(),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load profile.");
  await cacheProfile(data);
  return data;
}
