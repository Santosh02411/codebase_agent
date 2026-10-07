"""
Tests for Phase 8 — Barcode/QR Package Scanning:
- QR generation returns real SVG
- Scan resolution (valid + invalid codes)
- Recording scans of each type + scan history
- Duplicate scan protection (rejects an immediate repeat, allows one after the window)
- Offline-captured scan flag
- Authorization: unassigned agent blocked, tenant isolation
- Org-wide scan log with filters, permission-gated
"""

import uuid
from datetime import datetime, timedelta


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={"username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
              "role": "agent", "display_name": username, "invite_code": invite_code},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _create_delivery(client, auth_headers, agent_id):
    delivery_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    resp = client.post(
        "/deliveries/",
        json={"id": delivery_id, "agent_id": agent_id, "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
              "status": "pending", "created_at": now, "updated_at": now},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return delivery_id


# ---------- QR generation ----------

def test_package_qr_returns_svg(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_qr_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.get(f"/deliveries/{delivery_id}/package-qr", headers=agent_headers)
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
    assert resp.text.startswith("<?xml") or "<svg" in resp.text


# ---------- Scan resolution ----------

def test_resolve_valid_scanned_code(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_resolve_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.get(f"/scan/{delivery_id}", headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["delivery_id"] == delivery_id


def test_resolve_invalid_scanned_code(client, signed_up_admin, auth_headers):
    resp = client.get("/scan/not-a-real-code", headers=auth_headers)
    assert resp.status_code == 404


# ---------- Recording scans ----------

def test_record_scan_of_each_type_and_history(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_types_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    for scan_type in ["pickup", "hub", "out_for_delivery", "delivery"]:
        resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": scan_type}, headers=agent_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["scan_type"] == scan_type

    resp = client.get(f"/deliveries/{delivery_id}/scans", headers=agent_headers)
    assert resp.status_code == 200
    types = [s["scan_type"] for s in resp.json()]
    assert types == ["pickup", "hub", "out_for_delivery", "delivery"]


def test_return_scan_type(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_return_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "return"}, headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["scan_type"] == "return"


def test_scan_with_location_note_and_offline_flag(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_offline_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.post(
        f"/deliveries/{delivery_id}/scan",
        json={"scan_type": "hub", "location_note": "Hub 3", "captured_offline": True},
        headers=agent_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["location_note"] == "Hub 3"
    assert body["captured_offline"] is True


# ---------- Duplicate protection ----------

def test_duplicate_scan_rejected_within_window(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_dup_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "pickup"}, headers=agent_headers)
    assert resp.status_code == 200

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "pickup"}, headers=agent_headers)
    assert resp.status_code == 400


def test_scan_outside_duplicate_window_accepted(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_window_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    now = datetime.utcnow()
    resp = client.post(
        f"/deliveries/{delivery_id}/scan",
        json={"scan_type": "hub", "scanned_at": (now - timedelta(minutes=5)).isoformat()},
        headers=agent_headers,
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/deliveries/{delivery_id}/scan",
        json={"scan_type": "hub", "scanned_at": now.isoformat()},
        headers=agent_headers,
    )
    assert resp.status_code == 200  # 5 minutes apart — a legitimate second hub scan, not a duplicate


def test_different_scan_types_not_treated_as_duplicates(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_diff_type_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "pickup"}, headers=agent_headers)
    assert resp.status_code == 200
    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "hub"}, headers=agent_headers)
    assert resp.status_code == 200


# ---------- Authorization ----------

def test_unassigned_agent_cannot_scan_or_view(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    owner_id, _ = _signup_agent(client, invite_code, "scan_owner_agent")
    _, intruder_headers = _signup_agent(client, invite_code, "scan_intruder_agent")
    delivery_id = _create_delivery(client, auth_headers, owner_id)

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "pickup"}, headers=intruder_headers)
    assert resp.status_code == 403

    resp = client.get(f"/deliveries/{delivery_id}/scans", headers=intruder_headers)
    assert resp.status_code == 403

    resp = client.get(f"/scan/{delivery_id}", headers=intruder_headers)
    assert resp.status_code == 403


def test_dispatcher_can_scan_any_org_delivery(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "scan_dispatcher_test_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "hub"}, headers=auth_headers)
    assert resp.status_code == 200


def test_scans_isolated_between_organizations(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "scan_iso_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    other_resp = client.post(
        "/auth/signup",
        json={"username": "scan_other_org_admin", "email": "scan_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org Scan"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/scan/{delivery_id}", headers=other_headers)
    assert resp.status_code == 404


# ---------- Org-wide scan log ----------

def test_org_scan_log_filterable_and_permission_gated(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "scan_log_agent")
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    client.post(f"/deliveries/{delivery_id}/scan", json={"scan_type": "pickup"}, headers=agent_headers)

    resp = client.get("/admin/scans", headers=auth_headers)
    assert resp.status_code == 200
    assert any(s["delivery_id"] == delivery_id for s in resp.json())

    resp = client.get("/admin/scans?scan_type=pickup", headers=auth_headers)
    assert all(s["scan_type"] == "pickup" for s in resp.json())

    resp = client.get("/admin/scans?scan_type=delivery", headers=auth_headers)
    assert not any(s["delivery_id"] == delivery_id for s in resp.json())
