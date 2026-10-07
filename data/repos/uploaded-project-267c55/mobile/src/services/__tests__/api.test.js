/**
 * Tests the request-shape and error-handling logic of the new API
 * functions added for signup/password-reset, proof-of-delivery,
 * reason codes, messaging, and scanning — mocking fetch directly
 * (these functions are thin request builders, not complex enough to
 * warrant the fuller service-layer mocking style offlineSync.test.js
 * uses) and expo-secure-store, since every one of these calls goes
 * through authHeaders() -> getAccessToken() first.
 */

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn().mockResolvedValue("fake-access-token"),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock")
);

import {
  signup,
  login,
  forgotPassword,
  resetPassword,
  fetchActiveReasonCodes,
  submitProofOfDelivery,
  fetchDeliveryMessages,
  sendDeliveryMessage,
  resolveScannedCode,
  recordScan,
  API_BASE_URL,
} from "../api";

function mockFetchOnce(status, body) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

/**
 * The one thing apiFetch() (api.js's internal fetch wrapper — see its
 * own doc comment) changes: when the request never reaches a server
 * at all, rewrite React Native's opaque "Network request failed"
 * TypeError into something a user looking at LoginScreen.js's plain
 * `setError(err.message)` can actually act on.
 */
describe("network-unreachable errors", () => {
  it("rewrites a raw fetch failure into an actionable message naming the configured API_BASE_URL", async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError("Network request failed"));
    await expect(login("agent1", "pw")).rejects.toThrow(API_BASE_URL);
  });

  it("leaves a real HTTP error response untouched (still surfaces the backend's own detail message)", async () => {
    mockFetchOnce(401, { detail: "Incorrect username or password." });
    await expect(login("agent1", "wrong-pw")).rejects.toThrow("Incorrect username or password.");
  });
});

describe("signup", () => {
  it("sends invite-code join fields and returns a real session", async () => {
    mockFetchOnce(200, { access_token: "t", refresh_token: "r", user: { id: "u1" } });

    const result = await signup({
      username: "jane", email: "jane@example.com", password: "pw", displayName: "Jane",
      role: "agent", inviteCode: "ABC12345",
    });

    const [url, options] = global.fetch.mock.calls[0];
    const body = JSON.parse(options.body);
    expect(url).toBe("http://10.0.2.2:8000/auth/signup");
    expect(body).toMatchObject({ username: "jane", role: "agent", invite_code: "ABC12345" });
    expect(body.org_name).toBeUndefined();
    expect(result.user.id).toBe("u1");
  });

  it("throws the backend's error message on failure", async () => {
    mockFetchOnce(400, { detail: "That invite code doesn't match any organization." });
    await expect(signup({ username: "x", email: "x@example.com", password: "x", displayName: "X", role: "agent", inviteCode: "BAD" }))
      .rejects.toThrow("That invite code doesn't match any organization.");
  });

  it("includes the captcha token from <Captcha /> when one was captured", async () => {
    mockFetchOnce(200, { access_token: "t", refresh_token: "r", user: { id: "u1" } });
    await signup({
      username: "jane", email: "jane@example.com", password: "pw", displayName: "Jane",
      role: "agent", inviteCode: "ABC12345", captchaToken: "recaptcha-token-abc",
    });
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.captcha_token).toBe("recaptcha-token-abc");
  });

  it("omits captcha_token rather than sending null when no widget is configured", async () => {
    mockFetchOnce(200, { access_token: "t", refresh_token: "r", user: { id: "u1" } });
    await signup({ username: "jane", email: "jane@example.com", password: "pw", displayName: "Jane", role: "agent", inviteCode: "ABC12345" });
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.captcha_token).toBeUndefined();
  });
});

describe("forgotPassword", () => {
  it("posts the email and returns the confirmation message", async () => {
    mockFetchOnce(200, { message: "If that email exists, a reset link has been sent." });
    const result = await forgotPassword("agent@example.com");
    expect(result.message).toContain("reset link");
  });

  it("includes the captcha token when one was captured", async () => {
    mockFetchOnce(200, { message: "If that email exists, a reset link has been sent." });
    await forgotPassword("agent@example.com", "recaptcha-token-xyz");
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body).toEqual({ email: "agent@example.com", captcha_token: "recaptcha-token-xyz" });
  });
});

describe("resetPassword", () => {
  it("posts the token and new password with the field names the backend expects", async () => {
    mockFetchOnce(200, { message: "Your password has been reset." });
    const result = await resetPassword("reset-token-123", "newSecurePw1");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("http://10.0.2.2:8000/auth/reset-password");
    expect(JSON.parse(options.body)).toEqual({ token: "reset-token-123", new_password: "newSecurePw1" });
    expect(result.message).toContain("reset");
  });

  it("throws the backend's error message for an expired or invalid token", async () => {
    mockFetchOnce(400, { detail: "This reset link has expired. Request a new one." });
    await expect(resetPassword("stale-token", "newSecurePw1")).rejects.toThrow("expired");
  });
});

describe("fetchActiveReasonCodes", () => {
  it("returns the org's active reason codes", async () => {
    mockFetchOnce(200, [{ id: "r1", code: "REFUSED", label: "Refused by customer", active: true }]);
    const result = await fetchActiveReasonCodes();
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe("Refused by customer");
  });

  it("throws on a non-ok response", async () => {
    mockFetchOnce(403, { detail: "Not authorized." });
    await expect(fetchActiveReasonCodes()).rejects.toThrow("Not authorized.");
  });
});

describe("submitProofOfDelivery", () => {
  it("omits undefined optional fields rather than sending nulls", async () => {
    mockFetchOnce(200, { id: "pod1" });
    await submitProofOfDelivery("d1", { recipientName: "Rahul" });

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("http://10.0.2.2:8000/deliveries/d1/pod");
    const body = JSON.parse(options.body);
    expect(body.recipient_name).toBe("Rahul");
    expect(body.signature_data_url).toBeUndefined();
    expect(body.photo_data_url).toBeUndefined();
  });

  it("stringifies coordinates for the backend's string lat/long fields", async () => {
    mockFetchOnce(200, { id: "pod1" });
    await submitProofOfDelivery("d1", { latitude: 12.97, longitude: 77.59 });

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.latitude).toBe("12.97");
    expect(body.longitude).toBe("77.59");
  });
});

describe("delivery messaging", () => {
  it("fetches the message thread for a delivery", async () => {
    mockFetchOnce(200, [{ id: "m1", message: "On my way", sender_display_name: "Ravi" }]);
    const result = await fetchDeliveryMessages("d1");
    expect(result[0].message).toBe("On my way");
  });

  it("sends a message with the correct field name (message, not body)", async () => {
    mockFetchOnce(200, { id: "m2", message: "Got it" });
    await sendDeliveryMessage("d1", "Got it");

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body).toEqual({ message: "Got it" });
  });
});

describe("scanning", () => {
  it("resolves a scanned code to a delivery", async () => {
    mockFetchOnce(200, { id: "d1", order_id: "ORD-1", status: "pending" });
    const result = await resolveScannedCode("d1");
    expect(result.order_id).toBe("ORD-1");
  });

  it("throws a clear error for a code that doesn't match anything", async () => {
    mockFetchOnce(404, { detail: "Delivery not found." });
    await expect(resolveScannedCode("bad-code")).rejects.toThrow("Delivery not found.");
  });

  it("falls back to a clear default message when the backend gives no detail", async () => {
    mockFetchOnce(404, {});
    await expect(resolveScannedCode("bad-code")).rejects.toThrow(/doesn't match/);
  });

  it("records a scan event against a delivery", async () => {
    mockFetchOnce(200, { id: "s1", scan_type: "pickup" });
    await recordScan("d1", "pickup");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("http://10.0.2.2:8000/deliveries/d1/scan");
    expect(JSON.parse(options.body)).toEqual({ scan_type: "pickup" });
  });
});
