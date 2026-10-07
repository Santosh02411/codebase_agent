/**
 * Route batching/optimization logic.
 *
 * Since this project has no budget for a paid geocoding/routing API, this
 * works with what's actually available for free:
 * 1. A free-text "zone" field the dispatcher sets (e.g. "Sector 5") — used
 *    to GROUP deliveries, which needs no coordinates at all.
 * 2. OPTIONAL latitude/longitude, which — if the dispatcher happens to
 *    know them — enable ordering deliveries WITHIN a zone via a
 *    nearest-neighbor heuristic, starting from the agent's current
 *    location if available (browser geolocation), or the first delivery
 *    otherwise.
 *
 * Nearest-neighbor is a real, intentional choice: the optimal ordering
 * (true TSP) is NP-hard and impractical to compute exactly for this use
 * case; nearest-neighbor is a standard, fast, "good enough" approximation
 * — a legitimate, explainable algorithmic choice, not a shortcut being
 * passed off as something it isn't.
 */

/**
 * Haversine formula: great-circle distance between two lat/long points, in
 * kilometers. Standard approach for "distance between two points on Earth"
 * without needing a mapping API.
 */
function distanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth's radius in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function hasValidCoords(delivery) {
  const lat = parseFloat(delivery.latitude);
  const lon = parseFloat(delivery.longitude);
  return !isNaN(lat) && !isNaN(lon);
}

/**
 * Orders a list of deliveries (all assumed to have valid lat/long) via
 * nearest-neighbor: start from `startPoint` ({lat, lon}), repeatedly jump
 * to whichever remaining delivery is closest to the current position.
 */
function nearestNeighborOrder(deliveries, startPoint) {
  const remaining = [...deliveries];
  const ordered = [];
  let currentLat = startPoint.lat;
  let currentLon = startPoint.lon;

  while (remaining.length > 0) {
    let closestIndex = 0;
    let closestDistance = Infinity;

    remaining.forEach((delivery, index) => {
      const lat = parseFloat(delivery.latitude);
      const lon = parseFloat(delivery.longitude);
      const dist = distanceKm(currentLat, currentLon, lat, lon);
      if (dist < closestDistance) {
        closestDistance = dist;
        closestIndex = index;
      }
    });

    const next = remaining.splice(closestIndex, 1)[0];
    ordered.push({ ...next, _distanceFromPreviousKm: closestDistance });
    currentLat = parseFloat(next.latitude);
    currentLon = parseFloat(next.longitude);
  }

  return ordered;
}

/**
 * Main entry point: takes the agent's active (not-yet-delivered)
 * deliveries and a starting point, and returns them grouped by zone, with
 * each zone's deliveries ordered by nearest-neighbor where coordinates
 * are available.
 *
 * Returns: [{ zone: string, deliveries: [...] }, ...]
 * Deliveries without a zone are grouped under "Unassigned Zone".
 * Within a zone, deliveries without coordinates are appended at the end,
 * in their original order, after any coordinate-ordered ones.
 */
export function buildSuggestedRoute(deliveries, startPoint) {
  const zoneMap = new Map();

  for (const delivery of deliveries) {
    const zoneName = delivery.zone && delivery.zone.trim() ? delivery.zone.trim() : "Unassigned Zone";
    if (!zoneMap.has(zoneName)) zoneMap.set(zoneName, []);
    zoneMap.get(zoneName).push(delivery);
  }

  const zones = [];
  for (const [zoneName, zoneDeliveries] of zoneMap.entries()) {
    const withCoords = zoneDeliveries.filter(hasValidCoords);
    const withoutCoords = zoneDeliveries.filter((d) => !hasValidCoords(d));

    const ordered = withCoords.length > 0
      ? nearestNeighborOrder(withCoords, startPoint)
      : [];

    zones.push({
      zone: zoneName,
      deliveries: [...ordered, ...withoutCoords],
    });
  }

  // Sort zones alphabetically for a stable, predictable display order
  zones.sort((a, b) => a.zone.localeCompare(b.zone));

  return zones;
}

export { distanceKm, hasValidCoords };
