/**
 * Tests offlineStore.js against a real (in-memory, jest-expo-provided)
 * AsyncStorage mock — not a hand-rolled stub — so these tests exercise
 * the actual read/write/JSON-serialize round trip, not just whether
 * the right mock function got called.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  setActiveUser,
  cacheDeliveries,
  getCachedDeliveries,
  getCachedDelivery,
  queueStatusUpdate,
  getPendingDeliveries,
  getPendingCount,
  markAsSynced,
  clearAll,
} from "../offlineStore";

beforeEach(async () => {
  await AsyncStorage.clear();
  setActiveUser("agent-1");
});

describe("cacheDeliveries", () => {
  it("stores deliveries retrievable via getCachedDeliveries", async () => {
    await cacheDeliveries([
      { id: "d1", order_id: "ORD-1", status: "picked_up" },
      { id: "d2", order_id: "ORD-2", status: "pending" },
    ]);
    const cached = await getCachedDeliveries();
    expect(cached).toHaveLength(2);
    expect(cached.find((d) => d.id === "d1").sync_status).toBe("synced");
  });

  it("does not overwrite a locally-pending record with server data for the same id", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1", status: "picked_up" }]);
    await queueStatusUpdate("d1", { status: "out_for_delivery" });

    // A background refetch of the OLD server state must not clobber
    // the not-yet-synced local edit.
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1", status: "picked_up" }]);

    const record = await getCachedDelivery("d1");
    expect(record.status).toBe("out_for_delivery");
    expect(record.sync_status).toBe("pending");
  });

  it("scopes storage per user — a different user sees no data", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1" }]);
    setActiveUser("agent-2");
    expect(await getCachedDeliveries()).toEqual([]);
  });
});

describe("queueStatusUpdate", () => {
  it("applies the patch and marks the record pending", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1", status: "picked_up", agent_id: "agent-1" }]);
    const updated = await queueStatusUpdate("d1", { status: "delivered", updated_at: "2026-01-01T00:00:00Z" });

    expect(updated.status).toBe("delivered");
    expect(updated.sync_status).toBe("pending");
    expect(updated.agent_id).toBe("agent-1"); // untouched fields survive the patch
  });

  it("throws when queuing an update for a delivery that was never cached", async () => {
    await expect(queueStatusUpdate("unknown-id", { status: "delivered" })).rejects.toThrow(
      "never cached"
    );
  });
});

describe("getPendingDeliveries / getPendingCount", () => {
  it("returns only pending records, not synced ones", async () => {
    await cacheDeliveries([
      { id: "d1", order_id: "ORD-1" },
      { id: "d2", order_id: "ORD-2" },
    ]);
    await queueStatusUpdate("d1", { status: "delivered" });

    const pending = await getPendingDeliveries();
    expect(pending).toHaveLength(1);
    expect(pending[0].id).toBe("d1");
    expect(await getPendingCount()).toBe(1);
  });

  it("returns 0/empty when nothing is queued", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1" }]);
    expect(await getPendingCount()).toBe(0);
  });
});

describe("markAsSynced", () => {
  it("replaces the local record with the server's resolved version and clears pending status", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1", status: "picked_up" }]);
    await queueStatusUpdate("d1", { status: "out_for_delivery" });

    // Server resolved a conflict in favor of someone else's newer change.
    await markAsSynced("d1", { id: "d1", order_id: "ORD-1", status: "delivered" });

    const record = await getCachedDelivery("d1");
    expect(record.status).toBe("delivered");
    expect(record.sync_status).toBe("synced");
    expect(await getPendingCount()).toBe(0);
  });
});

describe("clearAll", () => {
  it("wipes all cached data for the active user", async () => {
    await cacheDeliveries([{ id: "d1", order_id: "ORD-1" }]);
    await clearAll();
    expect(await getCachedDeliveries()).toEqual([]);
  });
});
