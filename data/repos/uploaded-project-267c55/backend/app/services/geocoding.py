"""
Reverse geocoding: turns a raw GPS coordinate into a real, human-readable
area name (e.g. "Koramangala, Bengaluru") — used to give an agent a real
"my area" on their profile from their own device's GPS, rather than
asking them to type a zone name in by hand.

Two clarifications worth being explicit about, since they're easy to
conflate:
- The raw COORDINATE (how accurate the lat/lon itself is) comes from
  the agent's own device — its GPS chip, WiFi, or cell signal, via the
  browser's Geolocation API (navigator.geolocation on the frontend). No
  API key, ours or anyone else's, changes that: it's determined by the
  device's hardware and OS location services, not by anything server-
  side. A laptop with no GPS chip, using WiFi/IP-based positioning, will
  be less precise than a phone with real GPS regardless of what happens
  here.
- What an API key DOES improve is turning that coordinate into an
  ADDRESS — this file's actual job. Free providers like Nominatim
  (OpenStreetMap) are usable with zero setup but their address data is
  volunteer-maintained and can be sparse or a bit off in some areas.
  Google's Maps Geocoding API is generally more complete/accurate and
  is the "real" upgrade path here, at the cost of needing an API key
  and a billing account (Google's free tier covers normal usage for a
  project this size, but it's not a no-account-needed service the way
  Nominatim is).

Uses Google's Geocoding API when GOOGLE_MAPS_API_KEY is set, falling
back to free Nominatim otherwise — same "real if configured, free
fallback otherwise" pattern used throughout this project for SMTP,
Twilio, and Razorpay.
"""

import os

import requests

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY") or None
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "DeliverySync-PortfolioProject/1.0 (reverse geocoding for agent area assignment)"
REQUEST_TIMEOUT_SECONDS = 6


def reverse_geocode_area(latitude: float, longitude: float) -> str | None:
    """
    Returns a short, human-readable area name for a coordinate, or None
    if it couldn't be resolved (network issue, rate limit, or a
    coordinate with no nearby address data). Callers should treat None
    as "try again," not a crash.
    """
    if GOOGLE_MAPS_API_KEY:
        result = _reverse_geocode_google(latitude, longitude)
        if result:
            return result
        # Falls through to Nominatim below on a Google failure (bad key,
        # quota exceeded, network issue) rather than returning nothing —
        # a configured-but-currently-failing paid provider shouldn't be
        # worse than not having one at all.

    return _reverse_geocode_nominatim(latitude, longitude)


def _reverse_geocode_google(latitude: float, longitude: float) -> str | None:
    """
    Prefers Google's "sublocality"/"neighborhood" result types (the
    finest-grained useful level — matches Nominatim's suburb/
    neighbourhood preference below) paired with the locality (city), so
    an agent in a big city gets "Koramangala, Bengaluru" rather than
    just "Bengaluru" — same reasoning as the Nominatim path, just
    sourced from Google's more complete address database instead.
    """
    try:
        response = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"latlng": f"{latitude},{longitude}", "key": GOOGLE_MAPS_API_KEY},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("status") != "OK" or not data.get("results"):
        # Common non-crash outcomes: ZERO_RESULTS (coordinate with no
        # nearby address), REQUEST_DENIED (bad/missing API key or
        # billing not enabled), OVER_QUERY_LIMIT (free-tier quota hit).
        return None

    locality = None
    city = None
    for result in data["results"]:
        types = set(result.get("types", []))
        if not locality and (types & {"sublocality", "sublocality_level_1", "neighborhood"}):
            locality = result.get("address_components", [{}])[0].get("long_name")
        if not city and "locality" in types:
            city = result.get("address_components", [{}])[0].get("long_name")
        if locality and city:
            break

    if locality and city and locality != city:
        return f"{locality}, {city}"
    if locality:
        return locality
    if city:
        return city
    return None


def _reverse_geocode_nominatim(latitude: float, longitude: float) -> str | None:
    """
    OpenStreetMap's Nominatim (https://nominatim.org) — free, no API
    key, no billing account, which matters for a zero-budget project.
    Nominatim's usage policy requires a descriptive User-Agent
    identifying the application (not a browser UA string) and a max of
    ~1 request/second from a single client; both are respected here —
    this is only ever called once per agent per "detect my area" click,
    nowhere near that limit.

    Prefers the smallest well-known locality Nominatim returns
    (suburb/neighbourhood), falling back to progressively broader ones,
    so an agent in a big city gets "Koramangala" rather than just
    "Bengaluru" when that finer-grained data is available — that's the
    level of detail that actually helps a dispatcher tell two agents in
    the same city apart when matching them to a delivery zone.
    """
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={
                "format": "json",
                "lat": latitude,
                "lon": longitude,
                "zoom": 14,  # suburb/neighbourhood level of detail
                "addressdetails": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    address = data.get("address") or {}

    locality = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or address.get("city_district")
        or address.get("town")
        or address.get("village")
    )
    city = address.get("city") or address.get("county") or address.get("state")

    if locality and city and locality != city:
        return f"{locality}, {city}"
    if locality:
        return locality
    if city:
        return city

    # Nothing structured enough to use — the raw display_name is a full
    # postal-style address, too verbose to be a useful "area", so this
    # counts as a failed lookup rather than falling back to it.
    return None
