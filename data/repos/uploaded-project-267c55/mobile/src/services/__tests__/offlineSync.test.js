/**
 * Mirrors frontend/src/services/__tests__/syncEngine.test.js's
 * approach closely (mock the storage layer + the network call, drive
 * retries with real fake timers) — same underlying logic being
 * tested, ported to this file's actual dependencies (expo-network's
 * connectivity check and React Native's AppState in place of
 * navigator.onLine and the browser's "online" event).
 */

jest.mock("../offlineStore", () => ({
  getPendingDeliveries: jest.fn(),
  markAsSynced: jest.fn(),
}));
jest.mock("expo-network", () => ({
  getNetworkStateAsync: jest.fn(),
}));
jest.mock("../api", () => ({
  API_BASE_URL: "http://test-server",
}));

import { AppState } from "react-native";
import * as Network from "expo-network";
import { getPendingDeliveries, markAsSynced } from "../offlineStore";
import { describeConflict, runSync, startAutoSync } from "../offlineSync";

describe("describeConflict", () => {
  it("names who overrode the change when kept_by is present", () => {
    const message = describeConflict({
      order_id: "ORD-1",
      your_status: "picked_up",
      kept_status: "delivered",
      kept_by: "Rahul K.",
    });
    expect(message).toBe(
      'Order ORD-1: your change to "picked_up" was overridden — Rahul K. already updated it to "delivered" more recently, so that\'s what was kept.'
    );
  });

  it("falls back to a generic phrase when kept_by is missing", () => {
    const message = describeConflict({
      order_id: "ORD-2",
      your_status: "out_for_delivery",
      kept_status: "delivered",
      kept_by: null,
    });
    expect(message).toContain("it was already updated");
  });
});

describe("runSync", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn();
  });

  it("returns success with syncedCount 0 when there's nothing pending", async () => {
    getPendingDeliveries.mockResolvedValue([]);
    const result = await runSync();
    expect(result).toEqual({ success: true, syncedCount: 0 });
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("POSTs pending records to /sync with no Authorization header (matches the backend's unauthenticated endpoint)", async () => {
    const pending = [{ id: "1" }];
    getPendingDeliveries.mockResolvedValue(pending);
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ resolved_records: [{ id: "1", status: "delivered" }], errors: [], conflicts: [] }),
    });

    await runSync();

    expect(global.fetch).toHaveBeenCalledWith(
      "http://test-server/sync",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records: pending }),
      })
    );
    expect(markAsSynced).toHaveBeenCalledWith("1", { id: "1", status: "delivered" });
  });

  it("surfaces conflicts and errors from the backend without treating them as failure", async () => {
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        resolved_records: [{ id: "1" }],
        errors: [{ id: "1", error: "validation failed" }],
        conflicts: [{ order_id: "ORD-1", your_status: "a", kept_status: "b", kept_by: "X" }],
      }),
    });

    const result = await runSync();
    expect(result.success).toBe(true);
    expect(result.errorCount).toBe(1);
    expect(result.conflicts).toHaveLength(1);
  });

  it("retries on failure and eventually succeeds", async () => {
    jest.useFakeTimers();
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    global.fetch
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ resolved_records: [{ id: "1" }], errors: [], conflicts: [] }) });

    const resultPromise = runSync();
    await jest.advanceTimersByTimeAsync(3000);
    const result = await resultPromise;

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(result.success).toBe(true);
    jest.useRealTimers();
  });

  it("gives up after 3 consecutive failures and reports the last error", async () => {
    jest.useFakeTimers();
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    global.fetch.mockRejectedValue(new TypeError("Network request failed"));

    const resultPromise = runSync();
    await jest.advanceTimersByTimeAsync(3000);
    await jest.advanceTimersByTimeAsync(3000);
    const result = await resultPromise;

    expect(global.fetch).toHaveBeenCalledTimes(3);
    expect(result).toEqual({ success: false, syncedCount: 0, error: "Network request failed" });
    jest.useRealTimers();
  });

  it("throws a plain error (not silently swallowed) when the server responds but not ok", async () => {
    jest.useFakeTimers();
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    global.fetch.mockResolvedValue({ ok: false, json: async () => ({}) });

    const resultPromise = runSync();
    await jest.advanceTimersByTimeAsync(3000);
    await jest.advanceTimersByTimeAsync(3000);
    const result = await resultPromise;

    expect(result.success).toBe(false);
    expect(result.error).toBe("Sync request failed");
    jest.useRealTimers();
  });
});

describe("startAutoSync", () => {
  let appStateListeners;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    global.fetch = jest.fn();
    appStateListeners = [];
    jest.spyOn(AppState, "addEventListener").mockImplementation((event, handler) => {
      appStateListeners.push(handler);
      return { remove: jest.fn() };
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("triggers a sync immediately on startup when connected", async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: true, isInternetReachable: true });
    getPendingDeliveries.mockResolvedValue([]);

    const stop = startAutoSync();
    await jest.runOnlyPendingTimersAsync();

    expect(getPendingDeliveries).toHaveBeenCalled();
    stop();
  });

  it("does not sync on startup when not connected", async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: false, isInternetReachable: false });

    const stop = startAutoSync();
    await jest.runOnlyPendingTimersAsync();

    expect(getPendingDeliveries).not.toHaveBeenCalled();
    stop();
  });

  it("triggers a sync when the app becomes active again", async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: true, isInternetReachable: true });
    getPendingDeliveries.mockResolvedValue([]);

    const stop = startAutoSync();
    await jest.runOnlyPendingTimersAsync();
    getPendingDeliveries.mockClear();

    // Simulate the registered AppState listener firing with "active".
    appStateListeners.forEach((handler) => handler("active"));
    await jest.runOnlyPendingTimersAsync();

    expect(getPendingDeliveries).toHaveBeenCalled();
    stop();
  });

  it("does not trigger a sync when the app goes to background", async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: true, isInternetReachable: true });
    getPendingDeliveries.mockResolvedValue([]);

    const stop = startAutoSync();
    await jest.runOnlyPendingTimersAsync();
    getPendingDeliveries.mockClear();

    // Flush microtasks only — deliberately NOT advancing fake timers
    // here, since doing so would also let the independent periodic
    // sync interval fire and contaminate this assertion with an
    // unrelated trigger path.
    appStateListeners.forEach((handler) => handler("background"));
    await Promise.resolve();
    await Promise.resolve();

    expect(getPendingDeliveries).not.toHaveBeenCalled();
    stop();
  });

  it("returns a cleanup function that removes the AppState listener and stops the interval", async () => {
    Network.getNetworkStateAsync.mockResolvedValue({ isConnected: true, isInternetReachable: true });
    getPendingDeliveries.mockResolvedValue([]);
    const removeSpy = jest.fn();
    AppState.addEventListener.mockReturnValue({ remove: removeSpy });

    const stop = startAutoSync();
    await jest.runOnlyPendingTimersAsync();
    stop();

    expect(removeSpy).toHaveBeenCalled();
  });
});
