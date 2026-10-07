"""
Tests for the rest of the delivery lifecycle feature group:
- Failed-delivery reason codes: admin CRUD + enforcement on PATCH /deliveries/{id}
- Delivery-attempts logging (GET /deliveries/{id}/attempts)
- Reschedule workflow (POST /deliveries/{id}/reschedule)
- Partial-delivery marking (is_partial on PATCH /deliveries/{id})
- Priority-based sorting in the dispatcher queue (GET /deliveries/, /unassigned)
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _make_delivery(db_engine, org_id, status, agent_id=None, order_id=None, priority="normal", created_at=None):
    db = _session_for(db_engine)
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()),
            order_id=order_id or f"ORD-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            status=status,
            agent_id=agent_id,
            zone="Zone A",
            priority=priority,
            created_at=created_at or datetime.utcnow(),
            updated_at=created_at or datetime.utcnow(),
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery.id
    finally:
        db.close()


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": username.replace("_", " ").title(),
            "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _create_reason(client, auth_headers, code="CUST_UNAVAILABLE", label="Customer unavailable"):
    resp = client.post(
        "/admin/failed-delivery-reasons/",
        json={"code": code, "label": label},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- Reason code CRUD ----------

def test_admin_can_create_list_update_and_delete_reason_codes(client, auth_headers):
    created = _create_reason(client, auth_headers, code="wrong address", label="Wrong address")
    assert created["code"] == "WRONG_ADDRESS"  # normalized: uppercased, spaces -> underscores
    assert created["active"] is True

    resp = client.get("/admin/failed-delivery-reasons/", headers=auth_headers)
    assert resp.status_code == 200
    assert any(r["id"] == created["id"] for r in resp.json())

    resp = client.patch(
        f"/admin/failed-delivery-reasons/{created['id']}",
        json={"label": "Wrong delivery address", "active": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] == "Wrong delivery address"
    assert resp.json()["active"] is False

    resp = client.delete(f"/admin/failed-delivery-reasons/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/admin/failed-delivery-reasons/", headers=auth_headers)
    assert not any(r["id"] == created["id"] for r in resp.json())


def test_duplicate_reason_code_is_rejected(client, auth_headers):
    _create_reason(client, auth_headers, code="DUPLICATE", label="First")
    resp = client.post(
        "/admin/failed-delivery-reasons/",
        json={"code": "duplicate", "label": "Second"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_non_admin_cannot_manage_reason_codes(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "reasons_agent")

    resp = client.post(
        "/admin/failed-delivery-reasons/",
        json={"code": "X", "label": "X"},
        headers=agent_headers,
    )
    assert resp.status_code == 403


def test_active_reason_codes_endpoint_excludes_inactive(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "picker_agent")

    active_reason = _create_reason(client, auth_headers, code="ACTIVE_ONE", label="Active one")
    inactive_reason = _create_reason(client, auth_headers, code="INACTIVE_ONE", label="Inactive one")
    client.patch(
        f"/admin/failed-delivery-reasons/{inactive_reason['id']}",
        json={"active": False},
        headers=auth_headers,
    )

    resp = client.get("/deliveries/reason-codes/active", headers=agent_headers)
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert active_reason["id"] in ids
    assert inactive_reason["id"] not in ids


def test_reason_codes_are_org_scoped(client, auth_headers, admin_signup_payload):
    reason = _create_reason(client, auth_headers, code="ORG_A_REASON", label="Org A reason")

    other_admin_payload = dict(admin_signup_payload)
    other_admin_payload["username"] = "other_admin_" + uuid.uuid4().hex[:8]
    other_admin_payload["email"] = other_admin_payload["username"] + "@example.com"
    other_admin_payload["org_name"] = "OtherOrg-" + uuid.uuid4().hex[:8]
    resp = client.post("/auth/signup", json=other_admin_payload)
    assert resp.status_code == 200, resp.text
    other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.get("/admin/failed-delivery-reasons/", headers=other_headers)
    assert resp.status_code == 200
    assert not any(r["id"] == reason["id"] for r in resp.json())


# ---------- Enforcement on PATCH /deliveries/{id} ----------

def test_marking_failed_without_reason_code_is_rejected(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.patch(
        f"/deliveries/{d1}",
        json={"status": "failed_attempt", "updated_at": datetime.utcnow().isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "reason code" in resp.json()["detail"].lower()


def test_marking_failed_with_invalid_reason_code_is_rejected(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.patch(
        f"/deliveries/{d1}",
        json={
            "status": "failed_attempt",
            "updated_at": datetime.utcnow().isoformat(),
            "reason_code_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_marking_failed_with_inactive_reason_code_is_rejected(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)
    reason = _create_reason(client, auth_headers, code="RETIRED", label="Retired reason")
    client.patch(f"/admin/failed-delivery-reasons/{reason['id']}", json={"active": False}, headers=auth_headers)

    resp = client.patch(
        f"/deliveries/{d1}",
        json={"status": "failed_attempt", "updated_at": datetime.utcnow().isoformat(), "reason_code_id": reason["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_marking_failed_with_valid_reason_code_succeeds_and_logs_attempt(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)
    reason = _create_reason(client, auth_headers, code="NO_ANSWER", label="No answer at door")

    resp = client.patch(
        f"/deliveries/{d1}",
        json={
            "status": "failed_attempt",
            "updated_at": datetime.utcnow().isoformat(),
            "reason_code_id": reason["id"],
            "notes": "Knocked twice, no response",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "failed_attempt"
    assert resp.json()["attempt_count"] == 1

    resp = client.get(f"/deliveries/{d1}/attempts", headers=auth_headers)
    assert resp.status_code == 200
    attempts = resp.json()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "failed_attempt"
    assert attempts[0]["reason_label"] == "No answer at door"
    assert attempts[0]["attempt_number"] == 1


def test_bulk_status_update_rejects_failed_attempt(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.patch(
        "/deliveries/bulk-status",
        json={"delivery_ids": [d1], "status": "failed_attempt"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# ---------- Partial delivery marking ----------

def test_marking_delivered_partial_sets_flag_and_logs_partial_attempt(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.patch(
        f"/deliveries/{d1}",
        json={
            "status": "delivered",
            "updated_at": datetime.utcnow().isoformat(),
            "is_partial": True,
            "partial_notes": "1 of 3 items missing from the vehicle",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "delivered"
    assert body["is_partial"] is True
    assert body["partial_notes"] == "1 of 3 items missing from the vehicle"

    resp = client.get(f"/deliveries/{d1}/attempts", headers=auth_headers)
    attempts = resp.json()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "partial_delivery"


def test_marking_delivered_without_partial_clears_flag(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.patch(
        f"/deliveries/{d1}",
        json={"status": "delivered", "updated_at": datetime.utcnow().isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_partial"] is False
    assert resp.json()["partial_notes"] is None


# ---------- Reschedule workflow ----------

def test_dispatcher_can_reschedule_a_delivery(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)
    new_date = (datetime.utcnow() + timedelta(days=1)).isoformat()

    resp = client.post(
        f"/deliveries/{d1}/reschedule",
        json={"rescheduled_to": new_date, "reason": "Customer asked for tomorrow"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed_attempt"
    assert body["reschedule_reason"] == "Customer asked for tomorrow"
    assert body["reschedule_count"] == 1
    assert body["rescheduled_to"] is not None

    resp = client.get(f"/deliveries/{d1}/attempts", headers=auth_headers)
    attempts = resp.json()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "failed_attempt"

    resp = client.get(f"/deliveries/{d1}/history", headers=auth_headers)
    history = resp.json()
    assert any("Rescheduled" in (h.get("note") or "") for h in history)


def test_reschedule_requires_a_reason(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery)

    resp = client.post(
        f"/deliveries/{d1}/reschedule",
        json={"rescheduled_to": datetime.utcnow().isoformat(), "reason": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_cannot_reschedule_a_delivered_delivery(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.delivered)

    resp = client.post(
        f"/deliveries/{d1}/reschedule",
        json={"rescheduled_to": datetime.utcnow().isoformat(), "reason": "Too late"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_agent_can_reschedule_only_their_own_delivery(client, db_engine, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "reschedule_agent")
    other_agent_id, other_headers = _signup_agent(client, invite_code, "other_reschedule_agent")

    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery, agent_id=agent_id)

    resp = client.post(
        f"/deliveries/{d1}/reschedule",
        json={"rescheduled_to": datetime.utcnow().isoformat(), "reason": "Not home"},
        headers=other_headers,
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/deliveries/{d1}/reschedule",
        json={"rescheduled_to": datetime.utcnow().isoformat(), "reason": "Not home"},
        headers=agent_headers,
    )
    assert resp.status_code == 200, resp.text


# ---------- Priority ----------

def test_dispatcher_can_update_priority(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.pending)

    resp = client.patch(f"/deliveries/{d1}/priority", json={"priority": "urgent"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["priority"] == "urgent"


def test_dispatcher_queue_is_sorted_by_priority_then_age(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    now = datetime.utcnow()

    d_low = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, priority="low", created_at=now - timedelta(hours=3))
    d_normal_older = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, priority="normal", created_at=now - timedelta(hours=2))
    d_normal_newer = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, priority="normal", created_at=now - timedelta(hours=1))
    d_urgent = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, priority="urgent", created_at=now)

    resp = client.get("/deliveries/", headers=auth_headers)
    assert resp.status_code == 200
    ids_in_order = [d["id"] for d in resp.json()]

    assert ids_in_order.index(d_urgent) < ids_in_order.index(d_normal_older)
    assert ids_in_order.index(d_normal_older) < ids_in_order.index(d_normal_newer)
    assert ids_in_order.index(d_normal_newer) < ids_in_order.index(d_low)


def test_unassigned_queue_is_also_priority_sorted(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    now = datetime.utcnow()

    d_normal = _make_delivery(db_engine, org_id, DeliveryStatus.pending, priority="normal", created_at=now - timedelta(hours=1))
    d_high = _make_delivery(db_engine, org_id, DeliveryStatus.pending, priority="high", created_at=now)

    resp = client.get("/deliveries/unassigned", headers=auth_headers)
    assert resp.status_code == 200
    ids_in_order = [d["id"] for d in resp.json()]
    assert ids_in_order.index(d_high) < ids_in_order.index(d_normal)


# ---------- Offline sync path threads reason codes / partial through ----------

def test_sync_logs_failed_attempt_with_reason_and_partial_delivery(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "sync_extras_agent")
    reason = _create_reason(client, auth_headers, code="SYNC_FAILED", label="Failed via sync")

    delivery_id = str(uuid.uuid4())
    base = {
        "id": delivery_id,
        "agent_id": agent_id,
        "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
        "created_at": datetime.utcnow().isoformat(),
    }

    # First sync creates the record as picked_up.
    resp = client.post("/sync", json={"records": [{
        **base, "status": "picked_up", "updated_at": datetime.utcnow().isoformat(),
    }]})
    assert resp.status_code == 200, resp.text

    # Second sync (later timestamp) marks it failed_attempt with a reason code.
    later = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    resp = client.post("/sync", json={"records": [{
        **base, "status": "failed_attempt", "updated_at": later, "reason_code_id": reason["id"],
        "notes": "No one home",
    }]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolved_records"][0]["status"] == "failed_attempt"

    resp = client.get(f"/deliveries/{delivery_id}/attempts", headers=auth_headers)
    attempts = resp.json()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "failed_attempt"
    assert attempts[0]["reason_label"] == "Failed via sync"

    # Third sync (even later) marks it delivered, partially.
    even_later = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    resp = client.post("/sync", json={"records": [{
        **base, "status": "delivered", "updated_at": even_later,
        "is_partial": True, "partial_notes": "Missing one item",
    }]})
    assert resp.status_code == 200, resp.text
    resolved = resp.json()["resolved_records"][0]
    assert resolved["status"] == "delivered"
    assert resolved["is_partial"] is True
    assert resolved["partial_notes"] == "Missing one item"

    resp = client.get(f"/deliveries/{delivery_id}/attempts", headers=auth_headers)
    attempts = resp.json()
    assert len(attempts) == 2
    assert attempts[-1]["outcome"] == "partial_delivery"


def test_new_delivery_defaults_to_normal_priority(client, db_engine, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "priority_default_agent")

    resp = client.post(
        "/deliveries/",
        json={
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
            "status": "picked_up",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["priority"] == "normal"
    assert resp.json()["attempt_count"] == 0
