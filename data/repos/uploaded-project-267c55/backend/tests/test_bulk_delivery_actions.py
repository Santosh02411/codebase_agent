"""
Tests for bulk dispatcher actions on deliveries:
PATCH /deliveries/bulk-status and PATCH /deliveries/bulk-assign-agent.

Both endpoints reuse the same side-effect helpers (history entries,
customer notifications, refund-on-cancel, websocket broadcasts) the
single-record PATCH /deliveries/{id} and PATCH /deliveries/{id}/assign-agent
endpoints already use — these tests focus on what's actually new: the
per-item partial-success shape, org isolation, and status-transition
rules bulk reassignment adds on top of the single-record version.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _make_delivery(db_engine, org_id, status, agent_id=None, order_id=None):
    db = _session_for(db_engine)
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()),
            order_id=order_id or f"ORD-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            status=status,
            agent_id=agent_id,
            zone="Zone A",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
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
    return resp.json()["user"]["id"]


def test_bulk_status_update_applies_to_multiple_deliveries(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up)
    d2 = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up)

    resp = client.patch(
        "/deliveries/bulk-status",
        json={"delivery_ids": [d1, d2], "status": "out_for_delivery"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_count"] == 2
    assert body["failure_count"] == 0

    for did in (d1, d2):
        resp = client.get(f"/deliveries/{did}", headers=auth_headers)
        assert resp.json()["status"] == "out_for_delivery"


def test_bulk_status_update_partial_success_on_unknown_id(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up)
    fake_id = str(uuid.uuid4())

    resp = client.patch(
        "/deliveries/bulk-status",
        json={"delivery_ids": [d1, fake_id], "status": "delivered"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_count"] == 1
    assert body["failure_count"] == 1
    fake_result = next(r for r in body["results"] if r["delivery_id"] == fake_id)
    assert fake_result["success"] is False
    assert fake_result["error"]


def test_bulk_status_update_is_org_scoped(client, db_engine, auth_headers, admin_signup_payload):
    # A delivery belonging to a DIFFERENT org must not be touchable.
    other_org_id = "some-other-org-" + uuid.uuid4().hex[:8]
    other_delivery = _make_delivery(db_engine, other_org_id, DeliveryStatus.picked_up)

    resp = client.patch(
        "/deliveries/bulk-status",
        json={"delivery_ids": [other_delivery], "status": "delivered"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 0
    assert body["failure_count"] == 1


def test_bulk_reassign_moves_pending_to_picked_up(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "bulk_agent_one")

    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.pending)

    resp = client.patch(
        "/deliveries/bulk-assign-agent",
        json={"delivery_ids": [d1], "agent_id": agent_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success_count"] == 1

    resp = client.get(f"/deliveries/{d1}", headers=auth_headers)
    data = resp.json()
    assert data["status"] == "picked_up"
    assert data["agent_id"] == agent_id


def test_bulk_reassign_swaps_agent_without_changing_in_progress_status(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    old_agent_id = _signup_agent(client, invite_code, "bulk_agent_sick")
    new_agent_id = _signup_agent(client, invite_code, "bulk_agent_cover")

    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.out_for_delivery, agent_id=old_agent_id)

    resp = client.patch(
        "/deliveries/bulk-assign-agent",
        json={"delivery_ids": [d1], "agent_id": new_agent_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success_count"] == 1

    resp = client.get(f"/deliveries/{d1}", headers=auth_headers)
    data = resp.json()
    assert data["agent_id"] == new_agent_id
    assert data["status"] == "out_for_delivery"  # unchanged — was already in progress


def test_bulk_reassign_rejects_completed_deliveries(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "bulk_agent_two")

    delivered = _make_delivery(db_engine, org_id, DeliveryStatus.delivered)
    cancelled = _make_delivery(db_engine, org_id, DeliveryStatus.cancelled)

    resp = client.patch(
        "/deliveries/bulk-assign-agent",
        json={"delivery_ids": [delivered, cancelled], "agent_id": agent_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_count"] == 0
    assert body["failure_count"] == 2


def test_bulk_reassign_rejects_unknown_agent(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.pending)

    resp = client.patch(
        "/deliveries/bulk-assign-agent",
        json={"delivery_ids": [d1], "agent_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_bulk_endpoints_require_dispatcher_role(client, db_engine, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]

    # An agent (not a dispatcher/admin) should not be able to call these.
    agent_signup = client.post(
        "/auth/signup",
        json={
            "username": "plain_agent",
            "email": "plain_agent@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": "Plain Agent",
            "invite_code": invite_code,
        },
    )
    agent_token = agent_signup.json()["access_token"]
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up)

    resp = client.patch(
        "/deliveries/bulk-status",
        json={"delivery_ids": [d1], "status": "delivered"},
        headers=agent_headers,
    )
    assert resp.status_code == 403
