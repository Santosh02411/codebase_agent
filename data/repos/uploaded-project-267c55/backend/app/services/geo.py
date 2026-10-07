"""
Small geo helpers.

haversine_km: great-circle distance between two lat/lon points, in
kilometers. Used by the "smart assignment" suggestion logic
(routes/deliveries.py) to rank agents by how close their last-known
GPS position is to a delivery's address - the same math
routeOptimizer.js already does client-side for route ordering, just
needed server-side here for ranking agents before assignment.

find_zone_for_point: real point-in-zone testing for the zones/
territories feature (models/zone.py) — is this delivery's coordinate
inside an admin-defined circular zone, and if so, which one.
"""

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth's mean radius, km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def find_zone_for_point(zones, latitude: float, longitude: float):
    """
    Given a list of ZoneDB rows (already filtered to one org — callers
    query that), returns the one whose circle contains this point
    (haversine distance from its center <= its radius_km), or None if
    the point falls in none of them. If a point falls inside more than
    one overlapping zone, the smallest-radius match wins — the more
    specific territory is almost always the more useful one to restrict
    assignment to (e.g. a small "downtown core" zone nested inside a
    larger "greater metro" zone).
    """
    matches = [
        zone for zone in zones
        if haversine_km(latitude, longitude, zone.center_latitude, zone.center_longitude) <= zone.radius_km
    ]
    if not matches:
        return None
    return min(matches, key=lambda z: z.radius_km)
