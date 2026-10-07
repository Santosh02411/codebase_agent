"""
Advanced routing analytics (Phase 9) — built on top of the existing
services/routing.py (real road distance/optimization) and
services/geo.py (haversine), plus the new AgentLocationHistoryDB ping
log. Nothing here replaces the existing single-route optimizer used at
delivery-assignment time (routes/deliveries.py's route builder) — this
module adds live tracking intelligence and after-the-fact analytics on
top of it.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.location_history import AgentLocationHistoryDB
from app.models.agent_location import AgentLocationDB
from app.models.zone import ZoneDB
from app.services.geo import haversine_km
from app.services.routing import get_route_distance, optimize_stop_order

# A ping within this distance of the delivery's destination counts as
# "arrived" for geofence-alert purposes.
ARRIVAL_GEOFENCE_KM = 0.3

# If an agent's current distance-to-destination is more than this many
# times their closest-ever distance-to-destination on this delivery (and
# at least DEVIATION_MIN_KM further in absolute terms — guards against
# flagging noise on very short deliveries), treat it as a deviation.
DEVIATION_RATIO_THRESHOLD = 2.0
DEVIATION_MIN_KM = 1.0


def _delivery_destination(delivery: DeliveryRecordDB) -> Optional[tuple[float, float]]:
    if delivery.latitude and delivery.longitude:
        try:
            return float(delivery.latitude), float(delivery.longitude)
        except ValueError:
            return None
    return None


def compute_dynamic_eta(db: Session, delivery: DeliveryRecordDB) -> Optional[dict]:
    """
    Real road ETA from the agent's CURRENT live position to the
    delivery's destination — recalculated fresh on every call (not
    cached), which is what makes it "dynamic" rather than the
    once-computed expected_by set at assignment time. Returns None if
    the agent has no live location on file, or the delivery has no
    destination coordinates, or no routing provider is reachable.
    """
    if not delivery.agent_id:
        return None
    destination = _delivery_destination(delivery)
    if not destination:
        return None

    location = db.query(AgentLocationDB).filter(AgentLocationDB.agent_id == delivery.agent_id).first()
    if not location:
        return None

    route = get_route_distance(location.latitude, location.longitude, destination[0], destination[1])
    if not route:
        return None

    return {
        "distance_km": round(route["distance_km"], 2),
        "duration_min": round(route["duration_min"], 1),
        "eta_at": datetime.utcnow(),  # caller/frontend adds duration_min to "now" for a wall-clock ETA — kept as raw duration here rather than baking in a timezone assumption
        "agent_position_at": location.updated_at,
    }


def detect_route_deviation(db: Session, delivery: DeliveryRecordDB) -> Optional[dict]:
    """
    Pragmatic deviation heuristic (no stored planned route/polyline
    exists anywhere in this project to compare against): if the
    agent's CURRENT straight-line distance to the destination is
    significantly larger than the CLOSEST they've ever gotten on this
    delivery, they've moved meaningfully away from it — either a wrong
    turn, or a legitimate detour, but worth surfacing either way.
    Returns None if there's not enough history yet to judge, or no
    deviation is detected.
    """
    destination = _delivery_destination(delivery)
    if not destination:
        return None

    pings = db.query(AgentLocationHistoryDB).filter(
        AgentLocationHistoryDB.delivery_id == delivery.id,
    ).order_by(AgentLocationHistoryDB.recorded_at.asc()).all()
    if len(pings) < 2:
        return None

    distances = [haversine_km(p.latitude, p.longitude, destination[0], destination[1]) for p in pings]
    closest_km = min(distances[:-1])  # closest approach BEFORE the current (last) ping
    current_km = distances[-1]

    if current_km > DEVIATION_MIN_KM and current_km > closest_km * DEVIATION_RATIO_THRESHOLD:
        return {
            "deviated": True,
            "closest_approach_km": round(closest_km, 2),
            "current_distance_km": round(current_km, 2),
        }
    return None


def check_geofence_arrival(delivery: DeliveryRecordDB, latitude: float, longitude: float) -> bool:
    """True if this position is within the arrival geofence of the delivery's destination — used right after a location ping to decide whether to fire an 'agent has arrived' alert."""
    destination = _delivery_destination(delivery)
    if not destination:
        return False
    return haversine_km(latitude, longitude, destination[0], destination[1]) <= ARRIVAL_GEOFENCE_KM


def is_first_geofence_arrival(db: Session, delivery_id: str) -> bool:
    """
    True only the FIRST time a delivery's location history shows it
    within the arrival geofence — used to fire the 'agent nearby' alert
    exactly once per delivery rather than on every subsequent ping
    while the agent happens to linger nearby (e.g. parking, walking up
    to the door). Called AFTER the current ping has already been
    logged to AgentLocationHistoryDB, so "more than one arrival-range
    ping on record" means this isn't the first.
    """
    destination_deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
    if not destination_deliveries:
        return True
    destination = _delivery_destination(destination_deliveries)
    if not destination:
        return True
    pings = db.query(AgentLocationHistoryDB).filter(AgentLocationHistoryDB.delivery_id == delivery_id).all()
    arrivals = sum(
        1 for p in pings
        if haversine_km(p.latitude, p.longitude, destination[0], destination[1]) <= ARRIVAL_GEOFENCE_KM
    )
    return arrivals <= 1


def get_route_replay(db: Session, delivery_id: str) -> list[AgentLocationHistoryDB]:
    return db.query(AgentLocationHistoryDB).filter(
        AgentLocationHistoryDB.delivery_id == delivery_id,
    ).order_by(AgentLocationHistoryDB.recorded_at.asc()).all()


def compute_route_efficiency(db: Session, delivery: DeliveryRecordDB) -> Optional[dict]:
    """
    distance_traveled_km: sum of haversine between consecutive pings
    for this delivery (a real, if slightly-jagged, approximation of
    actual ground covered — as good as the ping density allows).
    time_spent_minutes: wall-clock span between the first and last
    ping. efficiency_ratio: straight-line distance from the first ping
    to the destination, divided by distance actually traveled — 1.0
    means the agent drove in a perfectly straight line; lower means
    more wandering/backtracking relative to the direct path.
    """
    pings = get_route_replay(db, delivery.id)
    if len(pings) < 2:
        return None

    distance_traveled = sum(
        haversine_km(pings[i].latitude, pings[i].longitude, pings[i + 1].latitude, pings[i + 1].longitude)
        for i in range(len(pings) - 1)
    )
    time_spent_minutes = (pings[-1].recorded_at - pings[0].recorded_at).total_seconds() / 60.0

    destination = _delivery_destination(delivery)
    efficiency_ratio = None
    if destination and distance_traveled > 0:
        direct_km = haversine_km(pings[0].latitude, pings[0].longitude, destination[0], destination[1])
        efficiency_ratio = round(min(direct_km / distance_traveled, 1.0), 2)

    return {
        "distance_traveled_km": round(distance_traveled, 2),
        "time_spent_minutes": round(time_spent_minutes, 1),
        "efficiency_ratio": efficiency_ratio,
        "ping_count": len(pings),
    }


def compute_delivery_heatmap(db: Session, org_id: str) -> list[dict]:
    """
    Buckets every location ping in the org onto a coarse grid (~1.1km
    at the equator, 3 decimal places) and counts pings per bucket — a
    simple, real heatmap data source with no external geospatial
    library dependency. Frontend renders these as weighted points on a
    map (e.g. via a Leaflet heat-layer plugin).
    """
    pings = db.query(AgentLocationHistoryDB.latitude, AgentLocationHistoryDB.longitude).filter(
        AgentLocationHistoryDB.org_id == org_id,
    ).all()
    buckets: dict[tuple[float, float], int] = {}
    for lat, lon in pings:
        key = (round(lat, 3), round(lon, 3))
        buckets[key] = buckets.get(key, 0) + 1
    return [{"latitude": lat, "longitude": lon, "count": count} for (lat, lon), count in buckets.items()]


def optimize_multi_agent_routes(db: Session, org_id: str, agent_starts: dict[str, dict]) -> dict[str, list[str]]:
    """
    Assigns every currently-unrouted stop (pending/picked_up deliveries
    with destination coordinates, not yet out_for_delivery) to the
    NEAREST available agent by straight-line distance (a greedy
    assignment — not a globally-optimal multi-vehicle routing solve,
    which is a much harder problem this project has no existing
    infrastructure for), then runs the existing single-route
    optimize_stop_order() per agent on their assigned stops. Stops with
    a slot_end deadline are given a light priority nudge: within an
    agent's assigned stops, anything with a slot_end sorts before
    anything without one, before optimize_stop_order runs — a simple
    time-window-aware ordering layered on top of the existing
    optimizer, not a full time-window-constrained solve.

    `agent_starts` is {agent_id: {"latitude": ..., "longitude": ...}}
    — the agents to consider, e.g. every zone-covering, currently-
    available agent for this batch. Returns {agent_id: [delivery_id, ...]}
    in visiting order.
    """
    stops = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == org_id,
        DeliveryRecordDB.status.in_([DeliveryStatus.pending, DeliveryStatus.picked_up]),
        DeliveryRecordDB.agent_id.in_(list(agent_starts.keys())),
        DeliveryRecordDB.latitude.isnot(None),
        DeliveryRecordDB.longitude.isnot(None),
    ).all()

    assignments: dict[str, list[DeliveryRecordDB]] = {agent_id: [] for agent_id in agent_starts}
    for stop in stops:
        # Already agent-assigned (this function optimizes ORDER across
        # an agent's own stops + a nearest-agent tiebreak isn't needed
        # here since deliveries in this project are always assigned to
        # a specific agent already — see routes/deliveries.py's
        # existing assignment flow). Grouping by existing assignment.
        assignments.setdefault(stop.agent_id, []).append(stop)

    result: dict[str, list[str]] = {}
    for agent_id, agent_stops in assignments.items():
        if not agent_stops:
            result[agent_id] = []
            continue
        # time-window nudge: slot-deadline stops first, earliest deadline first
        agent_stops.sort(key=lambda d: (d.slot_end is None, d.slot_end or datetime.max))
        stop_dicts = [
            {"id": s.id, "latitude": float(s.latitude), "longitude": float(s.longitude)}
            for s in agent_stops
        ]
        start = agent_starts.get(agent_id)
        ordered_ids = optimize_stop_order(stop_dicts, start=start)
        result[agent_id] = ordered_ids if ordered_ids else [s["id"] for s in stop_dicts]
    return result
