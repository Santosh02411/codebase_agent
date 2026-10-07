"""
Tests for two features added in this session:

1. Customer self-service password reset (POST /customer/forgot-password,
   POST /customer/reset-password) — mirrors the pre-existing staff flow
   in routes/auth.py, but against CustomerDB/CustomerPasswordResetTokenDB.
2. Live agent location on the public (no-login) tracking page
   (GET /track/{delivery_id}/agent-location) — only available while a
   delivery is picked_up/out_for_delivery, and never reveals agent
   identity.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.customer_password_reset import CustomerPasswordResetTokenDB
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.agent_location import AgentLocationDB


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def test_customer_forgot_password_is_generic_for_unknown_email(client):
    resp = client.post("/customer/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert "If that email is registered" in resp.json()["message"]


def test_customer_forgot_password_full_reset_cycle(client, db_engine, signed_up_customer):
    email = signed_up_customer["payload"]["email"]

    resp = client.post("/customer/forgot-password", json={"email": email})
    assert resp.status_code == 200, resp.text

    # Pull the token straight from the DB — there's no SMTP configured in
    # tests, so the "email" is just the console-log path in services/email.py.
    db = _session_for(db_engine)
    try:
        token_row = (
            db.query(CustomerPasswordResetTokenDB)
            .filter(CustomerPasswordResetTokenDB.customer_id == signed_up_customer["customer"]["id"])
            .order_by(CustomerPasswordResetTokenDB.created_at.desc())
            .first()
        )
        assert token_row is not None
        token = token_row.token
    finally:
        db.close()

    resp = client.post(
        "/customer/reset-password",
        json={"token": token, "new_password": "a-brand-new-password"},
    )
    assert resp.status_code == 200, resp.text

    # Old password should no longer work; new one should.
    resp = client.post("/customer/login", json={"email": email, "password": "correct-horse-battery"})
    assert resp.status_code == 401

    resp = client.post("/customer/login", json={"email": email, "password": "a-brand-new-password"})
    assert resp.status_code == 200, resp.text

    # The same token can't be reused a second time.
    resp = client.post(
        "/customer/reset-password",
        json={"token": token, "new_password": "yet-another-password"},
    )
    assert resp.status_code == 400


def test_customer_reset_password_rejects_expired_or_invalid_token(client, db_engine, signed_up_customer):
    resp = client.post(
        "/customer/reset-password",
        json={"token": "not-a-real-token", "new_password": "whatever12345"},
    )
    assert resp.status_code == 400

    db = _session_for(db_engine)
    try:
        expired = CustomerPasswordResetTokenDB(
            customer_id=signed_up_customer["customer"]["id"],
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        db.add(expired)
        db.commit()
        db.refresh(expired)
        expired_token = expired.token
    finally:
        db.close()

    resp = client.post(
        "/customer/reset-password",
        json={"token": expired_token, "new_password": "whatever12345"},
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def _make_delivery(db_engine, status, agent_id=None):
    db = _session_for(db_engine)
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()),
            order_id=f"ORD-{uuid.uuid4().hex[:8]}",
            org_id="test-org",
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


def _set_agent_location(db_engine, agent_id, lat=12.97, lng=77.59):
    db = _session_for(db_engine)
    try:
        loc = AgentLocationDB(agent_id=agent_id, latitude=lat, longitude=lng, updated_at=datetime.utcnow())
        db.add(loc)
        db.commit()
    finally:
        db.close()


def test_public_tracking_agent_location_available_while_out_for_delivery(client, db_engine):
    agent_id = str(uuid.uuid4())
    delivery_id = _make_delivery(db_engine, DeliveryStatus.out_for_delivery, agent_id=agent_id)
    _set_agent_location(db_engine, agent_id)

    resp = client.get(f"/track/{delivery_id}/agent-location")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["latitude"] == 12.97
    assert body["longitude"] == 77.59
    # Never leaks agent identity.
    assert "agent_id" not in body
    assert "agent" not in body


def test_public_tracking_agent_location_unavailable_before_pickup(client, db_engine):
    agent_id = str(uuid.uuid4())
    delivery_id = _make_delivery(db_engine, DeliveryStatus.pending, agent_id=agent_id)
    _set_agent_location(db_engine, agent_id)

    resp = client.get(f"/track/{delivery_id}/agent-location")
    assert resp.status_code == 404


def test_public_tracking_agent_location_unavailable_after_delivered(client, db_engine):
    agent_id = str(uuid.uuid4())
    delivery_id = _make_delivery(db_engine, DeliveryStatus.delivered, agent_id=agent_id)
    _set_agent_location(db_engine, agent_id)

    resp = client.get(f"/track/{delivery_id}/agent-location")
    assert resp.status_code == 404


def test_public_tracking_agent_location_404_for_unknown_delivery(client):
    resp = client.get(f"/track/{uuid.uuid4()}/agent-location")
    assert resp.status_code == 404
