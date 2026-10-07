import { describe, it, expect } from "vitest";
import { buildSuggestedRoute, distanceKm, hasValidCoords } from "../routeOptimizer";

describe("distanceKm", () => {
  it("returns 0 for identical points", () => {
    expect(distanceKm(12.9716, 77.5946, 12.9716, 77.5946)).toBeCloseTo(0, 5);
  });

  it("computes a plausible real-world distance (Bangalore to Belagavi, ~460km)", () => {
    // Real coordinates — a sanity check against Haversine's known
    // correctness, not just internal self-consistency.
    const km = distanceKm(12.9716, 77.5946, 15.8497, 74.4977);
    expect(km).toBeGreaterThan(440);
    expect(km).toBeLessThan(480);
  });

  it("is symmetric — distance A→B equals B→A", () => {
    const ab = distanceKm(12.97, 77.59, 15.85, 74.50);
    const ba = distanceKm(15.85, 74.50, 12.97, 77.59);
    expect(ab).toBeCloseTo(ba, 8);
  });
});

describe("hasValidCoords", () => {
  it("is true for a delivery with numeric lat/long strings", () => {
    expect(hasValidCoords({ latitude: "12.97", longitude: "77.59" })).toBe(true);
  });

  it("is true for a delivery with numeric lat/long numbers", () => {
    expect(hasValidCoords({ latitude: 12.97, longitude: 77.59 })).toBe(true);
  });

  it("is false when latitude is missing", () => {
    expect(hasValidCoords({ longitude: "77.59" })).toBe(false);
  });

  it("is false when longitude is missing", () => {
    expect(hasValidCoords({ latitude: "12.97" })).toBe(false);
  });

  it("is false for a non-numeric coordinate string", () => {
    expect(hasValidCoords({ latitude: "not-a-number", longitude: "77.59" })).toBe(false);
  });
});

describe("buildSuggestedRoute", () => {
  const startPoint = { lat: 15.85, lon: 74.50 };

  it("groups deliveries by zone", () => {
    const deliveries = [
      { id: "1", zone: "Zone A", latitude: "15.85", longitude: "74.50" },
      { id: "2", zone: "Zone B", latitude: "15.86", longitude: "74.51" },
      { id: "3", zone: "Zone A", latitude: "15.87", longitude: "74.52" },
    ];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result.map((z) => z.zone)).toEqual(["Zone A", "Zone B"]);
    expect(result.find((z) => z.zone === "Zone A").deliveries).toHaveLength(2);
    expect(result.find((z) => z.zone === "Zone B").deliveries).toHaveLength(1);
  });

  it("groups deliveries with no zone under 'Unassigned Zone'", () => {
    const deliveries = [{ id: "1", zone: "", latitude: "15.85", longitude: "74.50" }];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result[0].zone).toBe("Unassigned Zone");
  });

  it("treats a whitespace-only zone the same as no zone", () => {
    const deliveries = [{ id: "1", zone: "   ", latitude: "15.85", longitude: "74.50" }];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result[0].zone).toBe("Unassigned Zone");
  });

  it("sorts zones alphabetically regardless of input order", () => {
    const deliveries = [
      { id: "1", zone: "Zone C", latitude: "15.85", longitude: "74.50" },
      { id: "2", zone: "Zone A", latitude: "15.85", longitude: "74.50" },
      { id: "3", zone: "Zone B", latitude: "15.85", longitude: "74.50" },
    ];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result.map((z) => z.zone)).toEqual(["Zone A", "Zone B", "Zone C"]);
  });

  it("orders deliveries within a zone nearest-neighbor from the start point", () => {
    // far, near, medium — nearest-neighbor from startPoint should visit
    // near -> medium -> far (each hop to whichever remaining point is
    // currently closest), not the input order.
    const near = { id: "near", zone: "Z", latitude: "15.851", longitude: "74.501" };
    const medium = { id: "medium", zone: "Z", latitude: "15.90", longitude: "74.55" };
    const far = { id: "far", zone: "Z", latitude: "16.50", longitude: "75.20" };

    const result = buildSuggestedRoute([far, near, medium], startPoint);
    const order = result[0].deliveries.map((d) => d.id);
    expect(order).toEqual(["near", "medium", "far"]);
  });

  it("attaches _distanceFromPreviousKm to coordinate-ordered deliveries", () => {
    const deliveries = [{ id: "1", zone: "Z", latitude: "15.86", longitude: "74.51" }];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result[0].deliveries[0]._distanceFromPreviousKm).toBeGreaterThanOrEqual(0);
  });

  it("appends deliveries without coordinates after coordinate-ordered ones, in original order", () => {
    const withCoords = { id: "has-coords", zone: "Z", latitude: "15.86", longitude: "74.51" };
    const noCoords1 = { id: "no-coords-1", zone: "Z" };
    const noCoords2 = { id: "no-coords-2", zone: "Z" };

    const result = buildSuggestedRoute([noCoords1, withCoords, noCoords2], startPoint);
    const order = result[0].deliveries.map((d) => d.id);
    expect(order).toEqual(["has-coords", "no-coords-1", "no-coords-2"]);
  });

  it("returns an empty array for no deliveries", () => {
    expect(buildSuggestedRoute([], startPoint)).toEqual([]);
  });

  it("handles a zone where every delivery lacks coordinates", () => {
    const deliveries = [
      { id: "1", zone: "Z" },
      { id: "2", zone: "Z" },
    ];
    const result = buildSuggestedRoute(deliveries, startPoint);
    expect(result[0].deliveries.map((d) => d.id)).toEqual(["1", "2"]);
  });
});
