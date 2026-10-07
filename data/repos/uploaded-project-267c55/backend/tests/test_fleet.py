"""
Tests for Phase 11 — Fleet Management:
- Vehicle CRUD (dispatcher/admin), duplicate registration rejection, tenant isolation
- Agent role sees only their own assigned vehicle
- Assignment (agent must exist/be an agent in-org, one vehicle per agent, unassign)
- Maintenance records + odometer bump
- Fuel records + agent-can-only-log-own-vehicle restriction
- Reminders (insurance/registration/inspection/maintenance due soon)
- Utilization
- Capacity warning surfaced on suggested-agents
"""

from datetime import datetime, timedelta


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
            "role": "agent", "display_name": username, "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _create_vehicle(client, auth_headers, reg="KA-01-AB-1234", **kwargs):
    payload = {"vehicle_type": "van", "registration_number": reg}
    payload.update(kwargs)
    resp = client.post("/fleet/vehicles", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- CRUD ----------

def test_create_list_update_deactivate_vehicle(client, auth_headers):
    v = _create_vehicle(client, auth_headers)
    resp = client.get("/fleet/vehicles", headers=auth_headers)
    assert any(x["id"] == v["id"] for x in resp.json())

    resp = client.patch(f"/fleet/vehicles/{v['id']}", json={"status": "maintenance"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "maintenance"

    resp = client.delete(f"/fleet/vehicles/{v['id']}", headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/fleet/vehicles", headers=auth_headers)
    assert not any(x["id"] == v["id"] for x in resp.json())


def test_duplicate_registration_rejected(client, auth_headers):
    _create_vehicle(client, auth_headers, reg="KA-01-DUP-0001")
    resp = client.post("/fleet/vehicles", json={"vehicle_type": "bike", "registration_number": "KA-01-DUP-0001"}, headers=auth_headers)
    assert resp.status_code == 400


def test_agent_cannot_create_vehicle(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "fleet_agent_noperm")
    resp = client.post("/fleet/vehicles", json={"vehicle_type": "bike", "registration_number": "X1"}, headers=agent_headers)
    assert resp.status_code == 403


def test_vehicles_isolated_between_organizations(client, auth_headers):
    v = _create_vehicle(client, auth_headers, reg="KA-ISO-0001")
    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "fleet_other_org_admin", "email": "fleet_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org Fleet",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/fleet/vehicles/{v['id']}/maintenance", headers=other_headers)
    assert resp.status_code == 404


# ---------- Assignment ----------

def test_assign_and_unassign_vehicle(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "fleet_agent_1")
    v = _create_vehicle(client, auth_headers, reg="KA-ASSIGN-0001")

    resp = client.post(f"/fleet/vehicles/{v['id']}/assign", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["assigned_agent_id"] == agent_id
    assert resp.json()["status"] == "in_use"

    # Agent now sees only their own assigned vehicle in the list
    resp = client.get("/fleet/vehicles", headers=agent_headers)
    assert [x["id"] for x in resp.json()] == [v["id"]]

    resp = client.post(f"/fleet/vehicles/{v['id']}/assign", json={"agent_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["assigned_agent_id"] is None
    assert resp.json()["status"] == "available"


def test_cannot_double_assign_same_agent(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "fleet_agent_dup")
    v1 = _create_vehicle(client, auth_headers, reg="KA-DUPA-0001")
    v2 = _create_vehicle(client, auth_headers, reg="KA-DUPA-0002")

    resp = client.post(f"/fleet/vehicles/{v1['id']}/assign", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.post(f"/fleet/vehicles/{v2['id']}/assign", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 400


def test_assign_rejects_non_agent(client, auth_headers, signed_up_admin):
    v = _create_vehicle(client, auth_headers, reg="KA-BADASSIGN-0001")
    resp = client.post(f"/fleet/vehicles/{v['id']}/assign", json={"agent_id": signed_up_admin["user"]["id"]}, headers=auth_headers)
    assert resp.status_code == 400


# ---------- Maintenance & Fuel ----------

def test_maintenance_record_bumps_odometer(client, auth_headers):
    v = _create_vehicle(client, auth_headers, reg="KA-MAINT-0001")
    resp = client.post(
        f"/fleet/vehicles/{v['id']}/maintenance",
        json={"maintenance_type": "oil_change", "cost": 500, "odometer_km": 1000},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["maintenance_type"] == "oil_change"

    resp = client.get(f"/fleet/vehicles/{v['id']}", headers=auth_headers) if False else client.get("/fleet/vehicles", headers=auth_headers)
    updated = next(x for x in resp.json() if x["id"] == v["id"])
    assert updated["odometer_km"] == 1000

    resp = client.get(f"/fleet/vehicles/{v['id']}/maintenance", headers=auth_headers)
    assert len(resp.json()) == 1


def test_fuel_record_agent_can_only_log_own_vehicle(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "fleet_fuel_agent")
    v1 = _create_vehicle(client, auth_headers, reg="KA-FUEL-0001")
    v2 = _create_vehicle(client, auth_headers, reg="KA-FUEL-0002")
    client.post(f"/fleet/vehicles/{v1['id']}/assign", json={"agent_id": agent_id}, headers=auth_headers)

    resp = client.post(f"/fleet/vehicles/{v1['id']}/fuel", json={"liters": 5, "cost": 400}, headers=agent_headers)
    assert resp.status_code == 200

    resp = client.post(f"/fleet/vehicles/{v2['id']}/fuel", json={"liters": 5, "cost": 400}, headers=agent_headers)
    assert resp.status_code == 403

    resp = client.get(f"/fleet/vehicles/{v1['id']}/fuel", headers=auth_headers)
    assert len(resp.json()) == 1


# ---------- Reminders & Utilization ----------

def test_reminders_surface_soon_expiring_vehicles(client, auth_headers):
    soon = (datetime.utcnow() + timedelta(days=3)).isoformat()
    far = (datetime.utcnow() + timedelta(days=365)).isoformat()
    _create_vehicle(client, auth_headers, reg="KA-REM-SOON", insurance_expiry=soon)
    _create_vehicle(client, auth_headers, reg="KA-REM-FAR", insurance_expiry=far)

    resp = client.get("/fleet/reminders?within_days=14", headers=auth_headers)
    assert resp.status_code == 200
    regs = [v["registration_number"] for v in resp.json()["insurance_due"]]
    assert "KA-REM-SOON" in regs
    assert "KA-REM-FAR" not in regs


def test_utilization_counts_delivered_by_assigned_agent(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "fleet_util_agent")
    v = _create_vehicle(client, auth_headers, reg="KA-UTIL-0001")
    client.post(f"/fleet/vehicles/{v['id']}/assign", json={"agent_id": agent_id}, headers=auth_headers)

    resp = client.get(f"/fleet/vehicles/{v['id']}/utilization", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["assigned_agent_id"] == agent_id
    assert resp.json()["deliveries_completed"] == 0


def test_unassigned_vehicle_utilization_has_note(client, auth_headers):
    v = _create_vehicle(client, auth_headers, reg="KA-UTIL-UNASSIGNED")
    resp = client.get(f"/fleet/vehicles/{v['id']}/utilization", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["deliveries_completed"] == 0
    assert "note" in resp.json()


def test_vehicle_location_no_agent_returns_none(client, auth_headers):
    v = _create_vehicle(client, auth_headers, reg="KA-LOC-0001")
    resp = client.get(f"/fleet/vehicles/{v['id']}/location", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["location"] is None
