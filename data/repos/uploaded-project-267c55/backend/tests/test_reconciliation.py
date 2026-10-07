"""
Tests for Phase 5 — COD & Payment Reconciliation:
- Ledger entry auto-created on a real online checkout (charge) and on
  a real refund (refund) — proving the hooks into checkout.py/refund.py
  actually fire, not just that the service functions work in isolation.
- COD collection: lazy creation, match vs discrepancy, double-collection rejected
- Agent settlements: batching, settling, immutability once settled
- Permission gating via Phase 4's payments.* permissions
- Tenant isolation
"""

import uuid


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


def _place_cod_order(client, auth_headers, customer_auth_headers, price=50.0):
    product = client.post("/admin/products/", json={"name": "Recon Item", "price": price, "is_active": True}, headers=auth_headers).json()
    resp = client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "cod"},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = resp.json()

    resp = client.post("/customer/checkout/verify", json={"order_id": order["order_id"]}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    verified = resp.json()
    return verified["id"], verified["delivery_id"]


def _place_online_order(client, auth_headers, customer_auth_headers, price=50.0):
    product = client.post("/admin/products/", json={"name": "Online Recon Item", "price": price, "is_active": True}, headers=auth_headers).json()
    client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    resp = client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "online"},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = resp.json()
    resp = client.post("/customer/checkout/verify", json={"order_id": order["order_id"]}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # OrderOut: has .id (order id) and .delivery_id


def _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id):
    resp = client.patch(f"/deliveries/{delivery_id}/assign-agent", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 200, resp.text


# ---------- Ledger auto-population from real flows ----------

def test_online_checkout_creates_charge_ledger_entry(client, auth_headers, signed_up_admin, customer_auth_headers):
    order = _place_online_order(client, auth_headers, customer_auth_headers, price=40.0)
    order_id = order["id"]

    resp = client.get(f"/admin/reconciliation/payment-status/{order_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert any(e["event_type"] == "charge" for e in entries)


def test_cod_checkout_does_not_create_charge_ledger_entry(client, auth_headers, signed_up_admin, customer_auth_headers):
    order_id, _delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers)
    resp = client.get(f"/admin/reconciliation/payment-status/{order_id}", headers=auth_headers)
    entries = resp.json()
    assert not any(e["event_type"] == "charge" for e in entries)


def test_refund_creates_refund_ledger_entry(client, auth_headers, signed_up_admin, customer_auth_headers):
    order = _place_online_order(client, auth_headers, customer_auth_headers, price=60.0)
    order_id = order["id"]

    resp = client.get("/customer/orders", headers=customer_auth_headers)
    matching = next(o for o in resp.json() if o["id"] == order_id)
    delivery_id = matching["delivery_id"]

    resp = client.post(f"/customer/deliveries/{delivery_id}/cancel", headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/admin/reconciliation/payment-status/{order_id}", headers=auth_headers)
    entries = resp.json()
    assert any(e["event_type"] == "refund" for e in entries)


# ---------- COD collection ----------

def test_agent_can_collect_matching_cod_amount(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "recon_cod_agent")
    order_id, delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers, price=50.0)
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id)

    resp = client.get(f"/deliveries/{delivery_id}/cod", headers=agent_headers)
    assert resp.status_code == 200
    expected = resp.json()["expected_amount"]

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": expected}, headers=agent_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "collected"


def test_cod_discrepancy_flagged_when_amount_does_not_match(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "recon_discrepancy_agent")
    order_id, delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers, price=50.0)
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id)

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": 10.0, "notes": "Customer paid less"}, headers=agent_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "discrepancy"


def test_cannot_double_collect_cod(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "recon_double_agent")
    order_id, delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers, price=30.0)
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id)

    expected = client.get(f"/deliveries/{delivery_id}/cod", headers=agent_headers).json()["expected_amount"]

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": expected}, headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "collected"

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": expected}, headers=agent_headers)
    assert resp.status_code == 400


def test_other_agent_cannot_collect_cod_for_unassigned_delivery(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    owner_id, _ = _signup_agent(client, invite_code, "recon_owner_agent")
    _, intruder_headers = _signup_agent(client, invite_code, "recon_intruder_agent")
    order_id, delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers, price=20.0)
    _assign_delivery_to_agent(client, auth_headers, owner_id, delivery_id)

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": 20.0}, headers=intruder_headers)
    assert resp.status_code == 403


def test_collecting_cod_on_non_cod_delivery_rejected(client, auth_headers, signed_up_admin, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "recon_non_cod_agent")
    order = _place_online_order(client, auth_headers, customer_auth_headers, price=15.0)
    delivery_id = order["delivery_id"]
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id)

    resp = client.post(f"/deliveries/{delivery_id}/cod/collect", json={"collected_amount": 15.0}, headers=agent_headers)
    assert resp.status_code == 400


# ---------- Settlements ----------

def test_settlement_batches_and_settles_collections(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "recon_settle_agent")

    order_id_1, delivery_id_1 = _place_cod_order(client, auth_headers, customer_auth_headers, price=25.0)
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id_1)
    expected_1 = client.get(f"/deliveries/{delivery_id_1}/cod", headers=agent_headers).json()["expected_amount"]
    client.post(f"/deliveries/{delivery_id_1}/cod/collect", json={"collected_amount": expected_1}, headers=agent_headers)

    order_id_2, delivery_id_2 = _place_cod_order(client, auth_headers, customer_auth_headers, price=15.0)
    _assign_delivery_to_agent(client, auth_headers, agent_id, delivery_id_2)
    expected_2 = client.get(f"/deliveries/{delivery_id_2}/cod", headers=agent_headers).json()["expected_amount"]
    client.post(f"/deliveries/{delivery_id_2}/cod/collect", json={"collected_amount": expected_2}, headers=agent_headers)

    resp = client.post("/admin/reconciliation/settlements", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    settlement = resp.json()
    assert settlement["collection_count"] == 2
    assert settlement["total_collected"] == round(expected_1 + expected_2, 2)
    assert settlement["status"] == "open"

    resp = client.patch(f"/admin/reconciliation/settlements/{settlement['id']}/settle", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "settled"

    # settling twice rejected
    resp = client.patch(f"/admin/reconciliation/settlements/{settlement['id']}/settle", headers=auth_headers)
    assert resp.status_code == 400


def test_settlement_rejected_when_nothing_unsettled(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "recon_empty_agent")
    resp = client.post("/admin/reconciliation/settlements", json={"agent_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 400


# ---------- Permissions + dashboard ----------

def test_dashboard_and_ledger_require_payments_view_permission(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "recon_perm_agent")

    resp = client.get("/admin/reconciliation/dashboard", headers=agent_headers)
    assert resp.status_code == 403

    resp = client.get("/admin/reconciliation/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    for key in ("total_charged", "total_refunded", "net_revenue", "total_cod_collected", "cod_discrepancy_count"):
        assert key in resp.json()


def test_dispatcher_has_payments_view_but_not_manage_by_default(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={"username": "recon_dispatcher", "email": "recon_dispatcher@example.com", "password": "correct-horse-battery",
              "role": "dispatcher", "display_name": "Recon Dispatcher", "invite_code": invite_code},
    )
    dispatcher_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.get("/admin/reconciliation/dashboard", headers=dispatcher_headers)
    assert resp.status_code == 200  # payments.view is a dispatcher default

    resp = client.post("/admin/reconciliation/settlements", json={"agent_id": "whatever"}, headers=dispatcher_headers)
    assert resp.status_code == 403  # payments.manage is NOT a dispatcher default


# ---------- Tenant isolation ----------

def test_cod_collections_isolated_between_organizations(client, auth_headers, signed_up_admin, customer_auth_headers):
    order_id, delivery_id = _place_cod_order(client, auth_headers, customer_auth_headers, price=10.0)

    other_resp = client.post(
        "/auth/signup",
        json={"username": "recon_other_org_admin", "email": "recon_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org Recon"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/deliveries/{delivery_id}/cod", headers=other_headers)
    assert resp.status_code == 404
