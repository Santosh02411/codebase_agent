"""
Real routing: actual road distance/travel time between two points, and
real multi-stop route optimization — replacing the straight-line
(haversine) distance used elsewhere in this project for ranking/sorting
purposes only.

Two providers, same "real if configured, free fallback otherwise"
pattern used throughout this project:
- Google Directions API, when GOOGLE_MAPS_API_KEY is set (same key
  already used for geocoding — Directions is a separate API under the
  same Google Cloud project, needs enabling in the console).
- OSRM's free public demo server otherwise (router.project-osrm.org) —
  no API key, but OSRM's own usage policy is explicit that the public
  demo server is for light/evaluation use, not production traffic; a
  real production deployment should self-host OSRM (it's open source)
  or switch to a paid provider via GOOGLE_MAPS_API_KEY. That tradeoff
  is disclosed here rather than glossed over.

Both a straight-line distance (haversine, services/geo.py) and a real
routed distance still matter for different jobs in this codebase:
haversine is instant and free, so it's used as a first-pass filter/sort
across many candidates (e.g. every agent in an org); real routing is
slower and rate-limited, so it's reserved for a small final candidate
set where the more accurate number actually changes the outcome — see
routes/deliveries.py's _rank_agents_for_delivery for exactly this
two-stage pattern.
"""

import os
from typing import Optional

import requests

from app.services.geo import haversine_km

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY") or None
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
OSRM_BASE_URL = "https://router.project-osrm.org"
REQUEST_TIMEOUT_SECONDS = 6


def get_route_distance(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> Optional[dict]:
    """
    Real road distance/duration between two points. Returns
    {"distance_km": float, "duration_min": float} or None if it
    couldn't be determined (no provider reachable, bad coordinates,
    etc.) — callers should fall back to haversine_km on None, not treat
    it as an error.
    """
    if GOOGLE_MAPS_API_KEY:
        result = _google_route_distance(origin_lat, origin_lon, dest_lat, dest_lon)
        if result:
            return result
    return _osrm_route_distance(origin_lat, origin_lon, dest_lat, dest_lon)


def _google_route_distance(origin_lat, origin_lon, dest_lat, dest_lon) -> Optional[dict]:
    try:
        response = requests.get(
            GOOGLE_DIRECTIONS_URL,
            params={
                "origin": f"{origin_lat},{origin_lon}",
                "destination": f"{dest_lat},{dest_lon}",
                "key": GOOGLE_MAPS_API_KEY,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("status") != "OK" or not data.get("routes"):
        return None

    leg = data["routes"][0]["legs"][0]
    return {
        "distance_km": leg["distance"]["value"] / 1000,
        "duration_min": leg["duration"]["value"] / 60,
    }


def _osrm_route_distance(origin_lat, origin_lon, dest_lat, dest_lon) -> Optional[dict]:
    try:
        # OSRM takes coordinates as lon,lat (reversed from the usual
        # lat,lon convention — a real, easy-to-get-backwards detail of
        # this specific API).
        url = f"{OSRM_BASE_URL}/route/v1/driving/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        response = requests.get(url, params={"overview": "false"}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("code") != "Ok" or not data.get("routes"):
        return None

    route = data["routes"][0]
    return {
        "distance_km": route["distance"] / 1000,
        "duration_min": route["duration"] / 60,
    }


def optimize_stop_order(stops: list[dict], start: Optional[dict] = None) -> Optional[list[str]]:
    """
    Real multi-stop route optimization (an approximate TSP solve, not
    hand-rolled nearest-neighbor) — takes stops as
    [{"id": ..., "latitude": ..., "longitude": ...}, ...] and an
    optional {"latitude", "longitude"} starting point, returns the
    stop `id`s in a real optimized visiting order, or None if no
    provider could be reached (caller falls back to the existing
    client-side nearest-neighbor heuristic — see
    frontend/src/services/routeOptimizer.js).

    Uses OSRM's dedicated /trip endpoint (a real TSP-approximation
    service, not the /route endpoint used for get_route_distance
    above) when no Google key is set, or Google Directions with
    waypoint optimization when one is. Needs at least 2 stops to mean
    anything; fewer just returns them as-is.
    """
    if len(stops) < 2:
        return [s["id"] for s in stops]

    if GOOGLE_MAPS_API_KEY:
        result = _google_optimize_stops(stops, start)
        if result:
            return result
    return _osrm_optimize_stops(stops, start)


def _osrm_optimize_stops(stops: list[dict], start: Optional[dict]) -> Optional[list[str]]:
    points = ([start] if start else []) + stops
    coord_str = ";".join(f"{p['longitude']},{p['latitude']}" for p in points)
    try:
        url = f"{OSRM_BASE_URL}/trip/v1/driving/{coord_str}"
        params = {"roundtrip": "false"}
        if start:
            params["source"] = "first"
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("code") != "Ok" or not data.get("waypoints"):
        return None

    # OSRM returns each input point's position in the optimized trip
    # via "waypoint_index" — sort the ORIGINAL points by that to get
    # real ids back in the optimized order (OSRM itself only knows
    # about coordinates, not our ids).
    indexed = sorted(zip(data["waypoints"], points), key=lambda pair: pair[0]["waypoint_index"])
    ordered_points = [point for _, point in indexed]
    if start:
        ordered_points = [p for p in ordered_points if p is not start]
    return [p["id"] for p in ordered_points]


def _google_optimize_stops(stops: list[dict], start: Optional[dict]) -> Optional[list[str]]:
    origin = start or stops[0]
    remaining = stops if start else stops[1:]
    if not remaining:
        return [s["id"] for s in stops]

    destination = remaining[-1]
    waypoints = remaining[:-1]
    waypoints_param = "optimize:true|" + "|".join(f"{w['latitude']},{w['longitude']}" for w in waypoints) if waypoints else None

    try:
        params = {
            "origin": f"{origin['latitude']},{origin['longitude']}",
            "destination": f"{destination['latitude']},{destination['longitude']}",
            "key": GOOGLE_MAPS_API_KEY,
        }
        if waypoints_param:
            params["waypoints"] = waypoints_param
        response = requests.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("status") != "OK" or not data.get("routes"):
        return None

    order = data["routes"][0].get("waypoint_order", list(range(len(waypoints))))
    ordered_waypoints = [waypoints[i] for i in order]
    result_points = ordered_waypoints + [destination]
    if start:
        result_points = [origin] + result_points if origin is not start else result_points
    return [p["id"] for p in result_points]
