"""
Tests for PATCH /deliveries/{delivery_id}/return-to-pool — lets a
dispatcher pull a customer order back off its currently-assigned agent
and drop it back into the unassigned pool (GET /deliveries/unassigned).
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _make_delivery(db_engine, org_id, status, agent_id=None, customer_id=None, order_id=None):
    db = _session_for(db_engine)
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()),
            order_id=order_id or f"ORD-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            status=status,
            agent_id=agent_id,
            customer_id=customer_id,
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


def _signup_agent(client, invite_code, username="agent_one"):
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


def test_return_to_pool_unassigns_agent_and_reappears_in_unassigned(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code)

    delivery_id = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, agent_id=agent_id, customer_id=str(uuid.uuid4()))

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["agent_id"] is None

    resp = client.get("/deliveries/unassigned", headers=auth_headers)
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert delivery_id in ids

    resp = client.get(f"/deliveries/{delivery_id}/history", headers=auth_headers)
    assert resp.status_code == 200
    notes = [h["note"] for h in resp.json() if h.get("note")]
    assert any("Returned to unassigned pool" in n for n in notes)


def test_return_to_pool_rejects_manually_created_delivery(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "agent_two")

    delivery_id = _make_delivery(db_engine, org_id, DeliveryStatus.picked_up, agent_id=agent_id, customer_id=None)

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 400
    assert "customer-placed" in resp.json()["detail"]


def test_return_to_pool_rejects_out_for_delivery(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "agent_three")

    delivery_id = _make_delivery(
        db_engine, org_id, DeliveryStatus.out_for_delivery, agent_id=agent_id, customer_id=str(uuid.uuid4())
    )

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 400
    assert "just-assigned" in resp.json()["detail"]


def test_return_to_pool_rejects_delivered(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "agent_four")

    delivery_id = _make_delivery(
        db_engine, org_id, DeliveryStatus.delivered, agent_id=agent_id, customer_id=str(uuid.uuid4())
    )

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 400


def test_return_to_pool_requires_dispatcher_or_admin(client, db_engine, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]

    agent_resp = client.post(
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
    assert agent_resp.status_code == 200, agent_resp.text
    agent_id = agent_resp.json()["user"]["id"]
    agent_token = agent_resp.json()["access_token"]
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    delivery_id = _make_delivery(
        db_engine, org_id, DeliveryStatus.picked_up, agent_id=agent_id, customer_id=str(uuid.uuid4())
    )

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=agent_headers)
    assert resp.status_code == 403


def test_return_to_pool_notifies_the_old_agent(client, db_engine, auth_headers, signed_up_admin, monkeypatch):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "agent_notify")

    delivery_id = _make_delivery(
        db_engine, org_id, DeliveryStatus.picked_up, agent_id=agent_id, customer_id=str(uuid.uuid4())
    )

    calls = []

    def fake_notify(db, delivery_id, order_id, agent_id):
        calls.append((delivery_id, order_id, agent_id))

    monkeypatch.setattr("app.routes.deliveries.notify_agent_of_unassignment", fake_notify)

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1
    assert calls[0][0] == delivery_id
    assert calls[0][2] == agent_id


def test_return_to_pool_org_isolation(client, db_engine, auth_headers):
    other_org_id = str(uuid.uuid4())
    delivery_id = _make_delivery(
        db_engine, other_org_id, DeliveryStatus.picked_up, agent_id=str(uuid.uuid4()), customer_id=str(uuid.uuid4())
    )

    resp = client.patch(f"/deliveries/{delivery_id}/return-to-pool", headers=auth_headers)
    assert resp.status_code == 404
