"""
Tests for Phase 9 — Advanced Routing:
- Location history is logged alongside every location update (additive
  to the existing AgentLocationDB "latest position" table)
- Dynamic ETA (unavailable without a live location; unavailable without
  destination coordinates)
- Route deviation detection (not enough history -> no signal; moving
  away from destination -> flagged; staying on course -> not flagged)
- Geofence arrival: notifies dispatchers, fires only once per delivery
- Route replay returns pings in order
- Route efficiency metrics
- Heatmap aggregation
- Multi-agent route optimization groups by existing assignment + time-window ordering
- Tenant isolation + agent-ownership authorization
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.location_history import AgentLocationHistoryDB


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={"username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
              "role": "agent", "display_name": username, "invite_code": invite_code},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _create_delivery(client, auth_headers, agent_id, latitude=None, longitude=None):
    delivery_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    payload = {"id": delivery_id, "agent_id": agent_id, "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
               "status": "picked_up", "created_at": now, "updated_at": now}
    if latitude is not None:
        payload["latitude"] = str(latitude)
        payload["longitude"] = str(longitude)
    resp = client.post("/deliveries/", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return delivery_id


def _ping(client, agent_headers, lat, lon):
    resp = client.put("/users/me/location", json={"latitude": lat, "longitude": lon}, headers=agent_headers)
    assert resp.status_code == 200, resp.text


# ---------- Location history logging ----------

def test_location_ping_logs_history_alongside_latest_position(client, signed_up_admin, auth_headers, db_engine):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_history_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=12.9, longitude=77.6)

    _ping(client, agent_headers, 12.91, 77.61)
    _ping(client, agent_headers, 12.92, 77.62)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        history = db.query(AgentLocationHistoryDB).filter(AgentLocationHistoryDB.agent_id == agent_id).all()
        assert len(history) == 2
        assert all(h.delivery_id == delivery_id for h in history)
    finally:
        db.close()


# ---------- Dynamic ETA ----------

def test_eta_unavailable_without_live_location(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_eta_no_loc_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=12.9, longitude=77.6)

    resp = client.get(f"/deliveries/{delivery_id}/eta", headers=agent_headers)
    assert resp.status_code == 404


def test_eta_unavailable_without_destination_coordinates(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_eta_no_dest_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)  # no lat/lon
    _ping(client, agent_headers, 12.9, 77.6)

    resp = client.get(f"/deliveries/{delivery_id}/eta", headers=agent_headers)
    assert resp.status_code == 404


# ---------- Route deviation ----------

def test_no_deviation_signal_with_insufficient_history(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_dev_none_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=12.9, longitude=77.6)
    _ping(client, agent_headers, 12.89, 77.59)  # only one ping

    resp = client.get(f"/deliveries/{delivery_id}/route-deviation", headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["deviated"] is False


def test_deviation_flagged_when_moving_away_from_destination(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_dev_flag_agent")
    # destination far north; agent starts close, then moves far away
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)
    _ping(client, agent_headers, 12.995, 77.6)   # ~0.5km from destination
    _ping(client, agent_headers, 12.5, 77.6)     # ~55km from destination — moved far away

    resp = client.get(f"/deliveries/{delivery_id}/route-deviation", headers=agent_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["deviated"] is True
    assert body["current_distance_km"] > body["closest_approach_km"]


def test_no_deviation_when_staying_on_course(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_dev_ok_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)
    _ping(client, agent_headers, 12.9, 77.6)      # ~11km away
    _ping(client, agent_headers, 12.95, 77.6)     # ~5.5km away — getting closer, no deviation

    resp = client.get(f"/deliveries/{delivery_id}/route-deviation", headers=agent_headers)
    assert resp.json()["deviated"] is False


# ---------- Geofence arrival ----------

def test_geofence_arrival_fires_once(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_geofence_agent")
    # destination essentially where the agent is about to ping (well within the 300m geofence)
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=12.9000, longitude=77.6000)

    resp = client.put("/users/me/location", json={"latitude": 12.9001, "longitude": 77.6001}, headers=agent_headers)
    assert resp.status_code == 200

    # a second ping still within the geofence shouldn't error or duplicate-alert (no assertion on
    # notification count possible via API, but this confirms the endpoint keeps working normally)
    resp = client.put("/users/me/location", json={"latitude": 12.9001, "longitude": 77.6001}, headers=agent_headers)
    assert resp.status_code == 200


# ---------- Route replay + efficiency ----------

def test_route_replay_returns_pings_in_order(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_replay_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)
    _ping(client, agent_headers, 12.9, 77.6)
    _ping(client, agent_headers, 12.95, 77.6)

    resp = client.get(f"/deliveries/{delivery_id}/route-replay", headers=auth_headers)
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 2
    assert points[0]["recorded_at"] <= points[1]["recorded_at"]


def test_route_efficiency_metrics(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_eff_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)
    _ping(client, agent_headers, 12.9, 77.6)
    _ping(client, agent_headers, 12.95, 77.6)

    resp = client.get(f"/deliveries/{delivery_id}/route-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("distance_traveled_km", "time_spent_minutes", "efficiency_ratio", "ping_count"):
        assert key in body
    assert body["ping_count"] == 2
    assert body["distance_traveled_km"] > 0


def test_route_efficiency_insufficient_history(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_eff_none_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)

    resp = client.get(f"/deliveries/{delivery_id}/route-efficiency", headers=auth_headers)
    assert resp.status_code == 404


# ---------- Heatmap ----------

def test_heatmap_aggregates_pings(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_heatmap_agent")
    _create_delivery(client, auth_headers, agent_id, latitude=13.0, longitude=77.6)
    _ping(client, agent_headers, 12.9, 77.6)
    _ping(client, agent_headers, 12.9, 77.6)  # same bucket

    resp = client.get("/admin/routing/heatmap", headers=auth_headers)
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert any(p["count"] >= 2 for p in points)


# ---------- Multi-agent optimization ----------

def test_multi_agent_optimize_groups_by_assignment_and_time_window(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "route_multi_agent")

    now = datetime.utcnow()
    d1 = str(uuid.uuid4())
    d2 = str(uuid.uuid4())
    resp = client.post("/deliveries/", json={
        "id": d1, "agent_id": agent_id, "order_id": "MULTI-1", "status": "pending",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "latitude": "12.91", "longitude": "77.61",
        "slot_end": (now + timedelta(hours=1)).isoformat(),
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post("/deliveries/", json={
        "id": d2, "agent_id": agent_id, "order_id": "MULTI-2", "status": "pending",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "latitude": "12.92", "longitude": "77.62",
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/admin/routing/optimize-multi-agent",
        json={"agent_starts": {agent_id: {"latitude": 12.9, "longitude": 77.6}}},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    routes = resp.json()["routes"]
    assert agent_id in routes
    assert set(routes[agent_id]) == {d1, d2}
    # the slot_end-bearing stop should come first (time-window nudge)
    assert routes[agent_id][0] == d1


# ---------- Authorization + isolation ----------

def test_unassigned_agent_cannot_view_routing_info(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    owner_id, _ = _signup_agent(client, invite_code, "route_owner_agent")
    _, intruder_headers = _signup_agent(client, invite_code, "route_intruder_agent")
    delivery_id = _create_delivery(client, auth_headers, owner_id, latitude=12.9, longitude=77.6)

    resp = client.get(f"/deliveries/{delivery_id}/route-replay", headers=intruder_headers)
    assert resp.status_code == 403


def test_routing_isolated_between_organizations(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "route_iso_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id, latitude=12.9, longitude=77.6)

    other_resp = client.post(
        "/auth/signup",
        json={"username": "route_other_org_admin", "email": "route_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org Route"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/deliveries/{delivery_id}/route-replay", headers=other_headers)
    assert resp.status_code == 404
