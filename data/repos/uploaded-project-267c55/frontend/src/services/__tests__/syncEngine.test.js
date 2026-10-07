import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mocked BEFORE importing syncEngine so its own top-level `import`s of
// these modules resolve to the mocks below — vi.mock is hoisted above
// imports by Vitest specifically to make this ordering work.
vi.mock("../indexedDb", () => ({
  getPendingDeliveries: vi.fn(),
  markAsSynced: vi.fn(),
}));
vi.mock("../api", () => ({
  syncPendingDeliveries: vi.fn(),
}));

import { describeConflict, runSync, startAutoSync } from "../syncEngine";
import { getPendingDeliveries, markAsSynced } from "../indexedDb";
import { syncPendingDeliveries } from "../api";

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
    expect(message).toContain("ORD-2");
  });
});

describe("runSync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns success with syncedCount 0 when there's nothing pending", async () => {
    getPendingDeliveries.mockResolvedValue([]);
    const result = await runSync();
    expect(result).toEqual({ success: true, syncedCount: 0 });
    expect(syncPendingDeliveries).not.toHaveBeenCalled();
  });

  it("syncs pending records and reconciles each resolved record into IndexedDB", async () => {
    const pending = [{ id: "1" }, { id: "2" }];
    getPendingDeliveries.mockResolvedValue(pending);
    syncPendingDeliveries.mockResolvedValue({
      resolved_records: [{ id: "1", status: "delivered" }, { id: "2", status: "picked_up" }],
      errors: [],
      conflicts: [],
    });

    const result = await runSync();

    expect(syncPendingDeliveries).toHaveBeenCalledWith(pending);
    expect(markAsSynced).toHaveBeenCalledTimes(2);
    expect(markAsSynced).toHaveBeenCalledWith("1", { id: "1", status: "delivered" });
    expect(markAsSynced).toHaveBeenCalledWith("2", { id: "2", status: "picked_up" });
    expect(result).toMatchObject({ success: true, syncedCount: 2, errorCount: 0 });
  });

  it("surfaces conflicts and errors returned by the backend without treating them as failure", async () => {
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    syncPendingDeliveries.mockResolvedValue({
      resolved_records: [{ id: "1" }],
      errors: [{ id: "1", message: "validation failed" }],
      conflicts: [{ order_id: "ORD-1", your_status: "a", kept_status: "b", kept_by: "X" }],
    });

    const result = await runSync();
    expect(result.success).toBe(true);
    expect(result.errorCount).toBe(1);
    expect(result.errors).toHaveLength(1);
    expect(result.conflicts).toHaveLength(1);
  });

  it("retries on failure and eventually succeeds without exhausting retries", async () => {
    vi.useFakeTimers();
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    syncPendingDeliveries
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ resolved_records: [{ id: "1" }], errors: [], conflicts: [] });

    const resultPromise = runSync();
    // Let the first attempt's rejection be handled, then fast-forward
    // past the fixed retry delay so the second attempt actually runs.
    await vi.advanceTimersByTimeAsync(3000);
    const result = await resultPromise;

    expect(syncPendingDeliveries).toHaveBeenCalledTimes(2);
    expect(result.success).toBe(true);
    vi.useRealTimers();
  });

  it("gives up after MAX_RETRIES consecutive failures and reports the last error", async () => {
    vi.useFakeTimers();
    getPendingDeliveries.mockResolvedValue([{ id: "1" }]);
    syncPendingDeliveries.mockRejectedValue(new Error("still down"));

    const resultPromise = runSync();
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(3000);
    const result = await resultPromise;

    expect(syncPendingDeliveries).toHaveBeenCalledTimes(3);
    expect(result).toEqual({ success: false, syncedCount: 0, error: "still down" });
    vi.useRealTimers();
  });
});

describe("startAutoSync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("triggers a sync immediately on startup while online", async () => {
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    getPendingDeliveries.mockResolvedValue([]);

    const stop = startAutoSync();
    await vi.runOnlyPendingTimersAsync();

    expect(getPendingDeliveries).toHaveBeenCalled();
    stop();
  });

  it("does not sync on startup while offline", async () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });

    const stop = startAutoSync();
    await vi.runOnlyPendingTimersAsync();

    expect(getPendingDeliveries).not.toHaveBeenCalled();
    stop();
  });

  it("calls onSyncComplete with the sync result", async () => {
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    getPendingDeliveries.mockResolvedValue([]);
    const onSyncComplete = vi.fn();

    const stop = startAutoSync(onSyncComplete);
    await vi.runOnlyPendingTimersAsync();

    expect(onSyncComplete).toHaveBeenCalledWith({ success: true, syncedCount: 0 });
    stop();
  });

  it("returns a cleanup function that removes the online listener and stops the interval", () => {
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    getPendingDeliveries.mockResolvedValue([]);
    const removeSpy = vi.spyOn(window, "removeEventListener");

    const stop = startAutoSync();
    stop();

    expect(removeSpy).toHaveBeenCalledWith("online", expect.any(Function));
  });
});
