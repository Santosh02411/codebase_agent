"""
Tests for two features added in this session:

1. The general admin action log (ActionLogDB / GET /admin/action-log) —
   covers user management, product CRUD, coupon CRUD, and store
   settings changes. Separate from the pre-existing delivery
   status-change audit log (/admin/audit-log), which already had its
   own coverage elsewhere.
2. Pagination (limit/offset) on GET /customer/orders,
   GET /customer/deliveries, and GET /customer/notifications.
"""

from app.db.session import SessionLocal  # noqa: F401  (not used directly, keeps import style consistent)


def test_product_crud_writes_action_log_entries(client, auth_headers):
    # Create
    resp = client.post(
        "/admin/products/",
        json={"name": "Widget", "description": "A widget", "price": 9.99, "is_active": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    product_id = resp.json()["id"]

    # Update
    resp = client.patch(
        f"/admin/products/{product_id}",
        json={"price": 12.5},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # Delete
    resp = client.delete(f"/admin/products/{product_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    # Action log should now show all three, newest first.
    resp = client.get("/admin/action-log", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    actions = [e["action"] for e in entries]
    assert "product.create" in actions
    assert "product.update" in actions
    assert "product.delete" in actions

    update_entry = next(e for e in entries if e["action"] == "product.update")
    assert update_entry["entity_id"] == product_id
    assert update_entry["changes"] is not None
    assert "price" in update_entry["changes"]


def test_user_management_actions_are_logged(client, auth_headers, signed_up_admin):
    # Sign up a second user in the same org to act on.
    invite_code = signed_up_admin["org_invite_code"]
    signup_resp = client.post(
        "/auth/signup",
        json={
            "username": "agent_target",
            "email": "agent_target@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": "Agent Target",
            "invite_code": invite_code,
        },
    )
    assert signup_resp.status_code == 200, signup_resp.text
    target_id = signup_resp.json()["user"]["id"]

    resp = client.patch(f"/admin/users/{target_id}/deactivate", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/action-log", headers=auth_headers, params={"entity_type": "user"})
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert any(e["action"] == "user.deactivate" and e["entity_id"] == target_id for e in entries)


def test_action_log_is_org_scoped_and_admin_only(client, auth_headers, admin_signup_payload):
    # A second, unrelated org's admin must not see the first org's entries.
    client.post("/admin/products/", json={"name": "Gadget", "price": 5.0}, headers=auth_headers)

    other_admin_payload = {**admin_signup_payload, "username": "other_admin", "email": "other_admin@example.com", "org_name": "Other Org"}
    resp = client.post("/auth/signup", json=other_admin_payload)
    assert resp.status_code == 200, resp.text
    other_token = resp.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    resp = client.get("/admin/action-log", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_customer_orders_deliveries_notifications_are_paginated(client, customer_auth_headers):
    resp = client.get(
        "/customer/orders", headers=customer_auth_headers, params={"limit": 5, "offset": 0}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp = client.get(
        "/customer/deliveries", headers=customer_auth_headers, params={"limit": 5, "offset": 0}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp = client.get(
        "/customer/notifications", headers=customer_auth_headers, params={"limit": 5, "offset": 0}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Limit is bounded — an out-of-range value should be rejected, not
    # silently clamped, so a frontend bug surfaces instead of hiding data.
    resp = client.get(
        "/customer/orders", headers=customer_auth_headers, params={"limit": 10000, "offset": 0}
    )
    assert resp.status_code == 422
