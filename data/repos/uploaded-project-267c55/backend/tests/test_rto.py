"""
Tests for Phase 7 — RTO Management:
- RTO auto-created when a reason code flagged eligible_for_rto is used
- RTO auto-created after org's rto_max_attempts threshold is reached
  (with a reason NOT flagged eligible)
- No duplicate RTO rows for the same delivery
- No RTO when neither condition is met
- Full lifecycle: eligible -> approved -> in_transit -> received_at_origin
  (with real refund/restock for a prepaid order via the reused refund service)
- COD order: received_at_origin does NOT issue a refund
- Cancel path
- Invalid transitions rejected
- Permission gating + tenant isolation
- Analytics
"""

import uuid
from datetime import datetime


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={"username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
              "role": "agent", "display_name": username, "invite_code": invite_code},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _create_reason(client, auth_headers, code, eligible_for_rto=False):
    resp = client.post(
        "/admin/failed-delivery-reasons/",
        json={"code": code, "label": code.replace("_", " ").title(), "eligible_for_rto": eligible_for_rto},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


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


def _fail_delivery(client, agent_headers, delivery_id, reason_id, out_for_delivery_first=False):
    now = datetime.utcnow().isoformat()
    if out_for_delivery_first:
        # A delivery can't fail twice in a row from the SAME status (the
        # app only logs an attempt on an actual status CHANGE — see
        # routes/deliveries.py's `if old_status != update.status:` gate)
        # — a real re-attempt cycle goes back out before failing again.
        resp = client.patch(f"/deliveries/{delivery_id}", json={"status": "out_for_delivery", "updated_at": now}, headers=agent_headers)
        assert resp.status_code == 200, resp.text
        now = datetime.utcnow().isoformat()
    resp = client.patch(
        f"/deliveries/{delivery_id}",
        json={"status": "failed_attempt", "reason_code_id": reason_id, "updated_at": now},
        headers=agent_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- Auto-creation ----------

def test_rto_created_immediately_for_rto_flagged_reason(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_flag_agent")
    reason_id = _create_reason(client, auth_headers, "WRONG_ADDRESS", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    _fail_delivery(client, agent_headers, delivery_id, reason_id)

    resp = client.get("/admin/rto/requests", headers=auth_headers)
    assert resp.status_code == 200
    matching = [r for r in resp.json() if r["delivery_id"] == delivery_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "eligible"


def test_rto_created_after_max_attempts_with_non_flagged_reason(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_attempts_agent")
    reason_id = _create_reason(client, auth_headers, "CUSTOMER_UNAVAILABLE", eligible_for_rto=False)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    # default rto_max_attempts is 3
    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    resp = client.get("/admin/rto/requests", headers=auth_headers)
    assert not [r for r in resp.json() if r["delivery_id"] == delivery_id]

    _fail_delivery(client, agent_headers, delivery_id, reason_id, out_for_delivery_first=True)
    resp = client.get("/admin/rto/requests", headers=auth_headers)
    assert not [r for r in resp.json() if r["delivery_id"] == delivery_id]

    _fail_delivery(client, agent_headers, delivery_id, reason_id, out_for_delivery_first=True)
    resp = client.get("/admin/rto/requests", headers=auth_headers)
    matching = [r for r in resp.json() if r["delivery_id"] == delivery_id]
    assert len(matching) == 1


def test_configurable_rto_max_attempts(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_configurable_agent")
    reason_id = _create_reason(client, auth_headers, "OTHER_REASON", eligible_for_rto=False)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    resp = client.patch("/admin/rto/settings", json={"rto_max_attempts": 1}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["rto_max_attempts"] == 1

    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    resp = client.get("/admin/rto/requests", headers=auth_headers)
    matching = [r for r in resp.json() if r["delivery_id"] == delivery_id]
    assert len(matching) == 1


def test_no_rto_when_no_condition_met(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_none_agent")
    reason_id = _create_reason(client, auth_headers, "TRAFFIC_DELAY", eligible_for_rto=False)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    resp = client.get("/admin/rto/requests", headers=auth_headers)
    assert not [r for r in resp.json() if r["delivery_id"] == delivery_id]


def test_no_duplicate_rto_for_same_delivery(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_dup_agent")
    reason_id = _create_reason(client, auth_headers, "REFUSED", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)

    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id, out_for_delivery_first=True)  # a second failed attempt after already eligible

    resp = client.get("/admin/rto/requests", headers=auth_headers)
    matching = [r for r in resp.json() if r["delivery_id"] == delivery_id]
    assert len(matching) == 1


# ---------- Lifecycle ----------

def test_full_rto_lifecycle_with_online_order_issues_refund(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_lifecycle_agent")
    reason_id = _create_reason(client, auth_headers, "BAD_ADDRESS_2", eligible_for_rto=True)

    product = client.post("/admin/products/", json={"name": "RTO Item", "price": 20.0, "is_active": True}, headers=auth_headers).json()
    client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    checkout_resp = client.post("/customer/checkout", json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "online"}, headers=customer_auth_headers)
    order = client.post("/customer/checkout/verify", json={"order_id": checkout_resp.json()["order_id"]}, headers=customer_auth_headers).json()
    delivery_id = order["delivery_id"]

    resp = client.patch(f"/deliveries/{delivery_id}/assign-agent", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    _fail_delivery(client, agent_headers, delivery_id, reason_id)

    resp = client.get("/admin/rto/requests", headers=auth_headers)
    rto = next(r for r in resp.json() if r["delivery_id"] == delivery_id)
    assert rto["status"] == "eligible"

    resp = client.post(f"/admin/rto/requests/{rto['id']}/approve", json={"note": "Confirmed unreachable"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    resp = client.post(f"/admin/rto/requests/{rto['id']}/in-transit", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_transit"

    resp = client.post(f"/admin/rto/requests/{rto['id']}/received", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "received_at_origin"
    assert resp.json()["refund_issued"] is True

    # ledger entry should exist too (Phase 5 integration)
    resp = client.get(f"/admin/reconciliation/payment-status/{order['id']}", headers=auth_headers)
    assert any(e["event_type"] == "refund" for e in resp.json())


def test_cod_rto_received_does_not_issue_refund(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_cod_agent")
    reason_id = _create_reason(client, auth_headers, "COD_REFUSED", eligible_for_rto=True)

    product = client.post("/admin/products/", json={"name": "RTO COD Item", "price": 20.0, "is_active": True}, headers=auth_headers).json()
    client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    checkout_resp = client.post("/customer/checkout", json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "cod"}, headers=customer_auth_headers)
    order = client.post("/customer/checkout/verify", json={"order_id": checkout_resp.json()["order_id"]}, headers=customer_auth_headers).json()
    delivery_id = order["delivery_id"]
    client.patch(f"/deliveries/{delivery_id}/assign-agent", json={"agent_id": agent_id}, headers=auth_headers)

    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    rto = next(r for r in client.get("/admin/rto/requests", headers=auth_headers).json() if r["delivery_id"] == delivery_id)

    client.post(f"/admin/rto/requests/{rto['id']}/approve", json={}, headers=auth_headers)
    client.post(f"/admin/rto/requests/{rto['id']}/in-transit", headers=auth_headers)
    resp = client.post(f"/admin/rto/requests/{rto['id']}/received", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["refund_issued"] is False


def test_invalid_transitions_rejected(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_invalid_agent")
    reason_id = _create_reason(client, auth_headers, "INVALID_TEST", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    rto = next(r for r in client.get("/admin/rto/requests", headers=auth_headers).json() if r["delivery_id"] == delivery_id)

    # can't mark in-transit before approval
    resp = client.post(f"/admin/rto/requests/{rto['id']}/in-transit", headers=auth_headers)
    assert resp.status_code == 400

    # can't mark received before in-transit
    resp = client.post(f"/admin/rto/requests/{rto['id']}/received", headers=auth_headers)
    assert resp.status_code == 400

    client.post(f"/admin/rto/requests/{rto['id']}/approve", json={}, headers=auth_headers)
    # can't approve twice
    resp = client.post(f"/admin/rto/requests/{rto['id']}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_cancel_rto(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_cancel_agent")
    reason_id = _create_reason(client, auth_headers, "CANCEL_TEST", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    rto = next(r for r in client.get("/admin/rto/requests", headers=auth_headers).json() if r["delivery_id"] == delivery_id)

    resp = client.post(f"/admin/rto/requests/{rto['id']}/cancel", json={"note": "Reattempting instead"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    resp = client.post(f"/admin/rto/requests/{rto['id']}/cancel", json={}, headers=auth_headers)
    assert resp.status_code == 400


# ---------- Permissions + isolation ----------

def test_agent_cannot_approve_rto(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_perm_agent")
    reason_id = _create_reason(client, auth_headers, "PERM_TEST", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    rto = next(r for r in client.get("/admin/rto/requests", headers=auth_headers).json() if r["delivery_id"] == delivery_id)

    resp = client.post(f"/admin/rto/requests/{rto['id']}/approve", json={}, headers=agent_headers)
    assert resp.status_code == 403


def test_rto_requests_isolated_between_organizations(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_iso_agent")
    reason_id = _create_reason(client, auth_headers, "ISO_TEST", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id)
    rto = next(r for r in client.get("/admin/rto/requests", headers=auth_headers).json() if r["delivery_id"] == delivery_id)

    other_resp = client.post(
        "/auth/signup",
        json={"username": "rto_other_org_admin", "email": "rto_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org RTO"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/admin/rto/requests/{rto['id']}", headers=other_headers)
    assert resp.status_code == 404


# ---------- Analytics ----------

def test_rto_analytics(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "rto_analytics_agent")
    reason_id = _create_reason(client, auth_headers, "ANALYTICS_TEST", eligible_for_rto=True)
    delivery_id = _create_delivery(client, auth_headers, agent_id)
    _fail_delivery(client, agent_headers, delivery_id, reason_id)

    resp = client.get("/admin/rto/analytics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("total_rto_requests", "eligible", "received_at_origin", "refunds_issued", "by_reason"):
        assert key in body
    assert body["total_rto_requests"] >= 1
