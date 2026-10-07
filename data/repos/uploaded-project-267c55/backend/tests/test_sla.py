"""
Tests for Phase 2 — SLA Management:
- Policy CRUD (admin-only) + tenant isolation
- Policy matching/specificity (zone+priority beats org default, etc.)
- Deadline computation on delivery creation, and on-completion classification (met/missed)
- Background scan: on_track -> at_risk -> breached transitions
- Dispatcher SLA dashboard + analytics
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.sla import SLAPolicyDB
from app.services.sla import select_policy_for_delivery, assign_sla, classify_on_completion
from app.services.sla_monitor import run_sla_scan


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


def _create_policy(client, auth_headers, **overrides):
    payload = {"name": "Default", "target_minutes": 60, "warning_threshold_percent": 80}
    payload.update(overrides)
    resp = client.post("/admin/sla/policies", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_delivery(client, auth_headers, agent_id, zone=None, priority="normal", created_at=None):
    delivery_id = str(uuid.uuid4())
    now = created_at or datetime.utcnow()
    resp = client.post(
        "/deliveries/",
        json={
            "id": delivery_id,
            "agent_id": agent_id,
            "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "zone": zone,
            "priority": priority,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return delivery_id


# ---------- Policy CRUD ----------

def test_admin_can_create_list_update_delete_policy(client, auth_headers):
    policy = _create_policy(client, auth_headers, name="Standard", target_minutes=90)
    assert policy["target_minutes"] == 90

    resp = client.get("/admin/sla/policies", headers=auth_headers)
    assert resp.status_code == 200
    assert any(p["id"] == policy["id"] for p in resp.json())

    resp = client.patch(f"/admin/sla/policies/{policy['id']}", json={"target_minutes": 45}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["target_minutes"] == 45

    resp = client.delete(f"/admin/sla/policies/{policy['id']}", headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/admin/sla/policies", headers=auth_headers)
    assert not any(p["id"] == policy["id"] for p in resp.json())


def test_non_admin_cannot_manage_policies(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "sla_policy_agent")
    resp = client.post("/admin/sla/policies", json={"name": "X", "target_minutes": 30}, headers=agent_headers)
    assert resp.status_code == 403


def test_policies_are_isolated_between_organizations(client, auth_headers, signed_up_admin):
    policy = _create_policy(client, auth_headers)

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "sla_other_org_admin",
            "email": "sla_other_org_admin@example.com",
            "password": "correct-horse-battery",
            "role": "admin",
            "display_name": "Other Admin",
            "org_name": "Other Org SLA",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.patch(f"/admin/sla/policies/{policy['id']}", json={"target_minutes": 5}, headers=other_headers)
    assert resp.status_code == 404


# ---------- Matching / specificity ----------

def test_policy_matching_prefers_more_specific_policy(client, auth_headers, signed_up_admin, db_engine):
    org_id = signed_up_admin["user"]["org_id"]
    _create_policy(client, auth_headers, name="Org default", target_minutes=120)
    _create_policy(client, auth_headers, name="Urgent priority", target_minutes=30, priority="urgent")
    _create_policy(client, auth_headers, name="Zone A urgent", target_minutes=15, zone="Zone A", priority="urgent")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        # generic delivery -> org default
        generic = DeliveryRecordDB(id="d1", order_id="o1", org_id=org_id, status=DeliveryStatus.pending,
                                    priority="normal", zone=None, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        matched = select_policy_for_delivery(db, org_id, generic)
        assert matched.name == "Org default"

        # urgent, no zone -> urgent priority policy
        urgent = DeliveryRecordDB(id="d2", order_id="o2", org_id=org_id, status=DeliveryStatus.pending,
                                   priority="urgent", zone=None, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        matched = select_policy_for_delivery(db, org_id, urgent)
        assert matched.name == "Urgent priority"

        # urgent AND zone A -> most specific
        urgent_zone = DeliveryRecordDB(id="d3", order_id="o3", org_id=org_id, status=DeliveryStatus.pending,
                                        priority="urgent", zone="Zone A", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        matched = select_policy_for_delivery(db, org_id, urgent_zone)
        assert matched.name == "Zone A urgent"
    finally:
        db.close()


# ---------- Deadline assignment + completion classification ----------

def test_delivery_gets_sla_deadline_on_creation(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "sla_deadline_agent")
    _create_policy(client, auth_headers, name="60min", target_minutes=60)

    delivery_id = _create_delivery(client, auth_headers, agent_id)
    resp = client.get(f"/deliveries/{delivery_id}", headers=auth_headers) if False else None
    # no single-delivery GET route exists; check via the list endpoint instead
    resp = client.get("/deliveries/", headers=auth_headers)
    match = next(d for d in resp.json() if d["id"] == delivery_id)
    assert match["sla_target_at"] is not None
    assert match["sla_status"] == "on_track"


def test_delivery_with_no_matching_policy_is_not_applicable(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "sla_none_agent")
    # no policies created for this org at all
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    resp = client.get("/deliveries/", headers=auth_headers)
    match = next(d for d in resp.json() if d["id"] == delivery_id)
    assert match["sla_target_at"] is None
    assert match["sla_status"] == "not_applicable"


def test_classify_on_completion_met_vs_missed():
    target = datetime(2026, 1, 1, 12, 0, 0)
    on_time = DeliveryRecordDB(sla_target_at=target)
    classify_on_completion(on_time, datetime(2026, 1, 1, 11, 59, 0))
    assert on_time.sla_status == "met"

    late = DeliveryRecordDB(sla_target_at=target)
    classify_on_completion(late, datetime(2026, 1, 1, 12, 1, 0))
    assert late.sla_status == "missed"

    no_target = DeliveryRecordDB(sla_target_at=None)
    classify_on_completion(no_target, datetime(2026, 1, 1, 12, 0, 0))
    assert no_target.sla_status == "not_applicable"


def test_mark_delivered_records_met_or_missed(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "sla_complete_agent")
    _create_policy(client, auth_headers, name="Long window", target_minutes=600)  # 10 hours, won't breach in-test

    delivery_id = _create_delivery(client, auth_headers, agent_id)
    now = datetime.utcnow().isoformat()
    resp = client.patch(f"/deliveries/{delivery_id}", json={"status": "delivered", "updated_at": now}, headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["sla_status"] == "met"


# ---------- Background scan ----------

def test_sla_scan_flags_at_risk_and_breached(client, signed_up_admin, auth_headers, db_engine):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "sla_scan_agent")
    _create_policy(client, auth_headers, name="60min", target_minutes=60, warning_threshold_percent=80)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        org_id = signed_up_admin["user"]["org_id"]

        # created 50 minutes ago against a 60-minute target -> 83% elapsed -> at_risk
        near = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id="AT-RISK", org_id=org_id, status=DeliveryStatus.pending,
            agent_id=agent_id, priority="normal", zone=None,
            created_at=datetime.utcnow() - timedelta(minutes=50),
            updated_at=datetime.utcnow() - timedelta(minutes=50),
        )
        assign_sla(db, near)
        db.add(near)

        # created 90 minutes ago against a 60-minute target -> already past deadline -> breached
        overdue = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id="BREACHED", org_id=org_id, status=DeliveryStatus.picked_up,
            agent_id=agent_id, priority="normal", zone=None,
            created_at=datetime.utcnow() - timedelta(minutes=90),
            updated_at=datetime.utcnow() - timedelta(minutes=90),
        )
        assign_sla(db, overdue)
        db.add(overdue)
        db.commit()

        changed = run_sla_scan(db)
        assert changed == 2

        db.refresh(near)
        db.refresh(overdue)
        assert near.sla_status == "at_risk"
        assert overdue.sla_status == "breached"
        assert overdue.sla_breach_notified is True
    finally:
        db.close()

    # dispatcher dashboard should now list both
    resp = client.get("/admin/sla/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    statuses = {d["order_id"]: d["sla_status"] for d in resp.json()}
    assert statuses.get("BREACHED") == "breached"
    assert statuses.get("AT-RISK") == "at_risk"


def test_sla_analytics_returns_expected_shape(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "sla_analytics_agent")
    _create_policy(client, auth_headers, name="Analytics window", target_minutes=600)

    delivery_id = _create_delivery(client, auth_headers, agent_id)
    now = datetime.utcnow().isoformat()
    client.patch(f"/deliveries/{delivery_id}", json={"status": "delivered", "updated_at": now}, headers=agent_headers)

    resp = client.get("/admin/sla/analytics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("sla_percentage", "completed", "met", "missed", "avg_delivery_minutes", "avg_delay_minutes", "by_agent", "by_zone"):
        assert key in body
    assert body["completed"] >= 1


def test_public_tracking_exposes_sla_status(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "sla_public_agent")
    _create_policy(client, auth_headers, name="Public window", target_minutes=60)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.get(f"/track/{delivery_id}")
    assert resp.status_code == 200
    assert resp.json()["sla_status"] == "on_track"
