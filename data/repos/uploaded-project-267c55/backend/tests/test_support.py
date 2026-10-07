"""
Tests for Phase 12 — Customer Support:
- Customer can create a ticket tied to a real order, list/view their own tickets
- Customer cannot see another customer's ticket, or internal notes
- Customer reply reopens a resolved ticket
- Staff: list/filter, reply (auto in_progress on first non-internal reply),
  internal notes hidden from customer, assign (must be dispatcher/admin
  in-org), resolve, tenant isolation
- Analytics counts
"""


def _signup_dispatcher(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
            "role": "dispatcher", "display_name": username, "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _place_order(client, auth_headers, customer_auth_headers, price=50.0):
    product = client.post("/admin/products/", json={"name": "Support Item", "price": price, "is_active": True}, headers=auth_headers).json()
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
    return resp.json()["id"]


def _create_ticket(client, customer_auth_headers, order_id, **kwargs):
    payload = {"subject": "Missing item", "description": "One item was missing from my order.", "order_id": order_id}
    payload.update(kwargs)
    resp = client.post("/customer/support/tickets", json=payload, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- Customer side ----------

def test_customer_can_create_and_list_own_tickets(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id, category="order_issue")
    assert ticket["status"] == "open"
    assert ticket["order_id"] == order_id

    resp = client.get("/customer/support/tickets", headers=customer_auth_headers)
    assert any(t["id"] == ticket["id"] for t in resp.json())


def test_invalid_category_rejected(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    resp = client.post(
        "/customer/support/tickets",
        json={"subject": "x", "description": "y", "order_id": order_id, "category": "not_a_real_category"},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 400


def test_customer_cannot_see_other_customers_ticket(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    other_resp = client.post("/customer/signup", json={"email": "other_support_cust@example.com", "password": "correct-horse-battery", "name": "Other"})
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}

    resp = client.get(f"/customer/support/tickets/{ticket['id']}", headers=other_headers)
    assert resp.status_code == 404


def test_customer_message_thread_hides_internal_notes(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    resp = client.post(f"/admin/support/tickets/{ticket['id']}/messages", json={"message": "Looking into it", "is_internal_note": False}, headers=auth_headers)
    assert resp.status_code == 200
    resp = client.post(f"/admin/support/tickets/{ticket['id']}/messages", json={"message": "Customer seems upset, escalate", "is_internal_note": True}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get(f"/customer/support/tickets/{ticket['id']}/messages", headers=customer_auth_headers)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 1
    assert "Looking into it" in messages[0]["message"]

    resp = client.get(f"/admin/support/tickets/{ticket['id']}/messages", headers=auth_headers)
    assert len(resp.json()) == 2


def test_customer_reply_reopens_resolved_ticket(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    resp = client.post(f"/admin/support/tickets/{ticket['id']}/resolve", json={"resolution_notes": "Refund issued."}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    resp = client.post(f"/customer/support/tickets/{ticket['id']}/messages", json={"message": "Actually it's still wrong"}, headers=customer_auth_headers)
    assert resp.status_code == 200

    resp = client.get(f"/customer/support/tickets/{ticket['id']}", headers=customer_auth_headers)
    assert resp.json()["status"] == "in_progress"


def test_cannot_reply_to_closed_ticket(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)
    client.patch(f"/admin/support/tickets/{ticket['id']}", json={"status": "closed"}, headers=auth_headers)

    resp = client.post(f"/customer/support/tickets/{ticket['id']}/messages", json={"message": "hello?"}, headers=customer_auth_headers)
    assert resp.status_code == 400


# ---------- Staff side ----------

def test_staff_reply_moves_open_to_in_progress(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)
    assert ticket["status"] == "open"

    resp = client.post(f"/admin/support/tickets/{ticket['id']}/messages", json={"message": "On it"}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get(f"/admin/support/tickets/{ticket['id']}", headers=auth_headers)
    assert resp.json()["status"] == "in_progress"


def test_internal_note_does_not_change_status(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    client.post(f"/admin/support/tickets/{ticket['id']}/messages", json={"message": "internal only", "is_internal_note": True}, headers=auth_headers)
    resp = client.get(f"/admin/support/tickets/{ticket['id']}", headers=auth_headers)
    assert resp.json()["status"] == "open"


def test_assign_requires_dispatcher_or_admin_in_org(client, signed_up_admin, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)
    invite_code = signed_up_admin["org_invite_code"]
    dispatcher_id, _ = _signup_dispatcher(client, invite_code, "support_dispatcher")

    resp = client.patch(f"/admin/support/tickets/{ticket['id']}", json={"assigned_to_user_id": dispatcher_id}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["assigned_to_user_id"] == dispatcher_id

    resp = client.patch(f"/admin/support/tickets/{ticket['id']}", json={"assigned_to_user_id": "not-a-real-id"}, headers=auth_headers)
    assert resp.status_code == 400


def test_resolve_sets_resolution_and_timestamp(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    resp = client.post(f"/admin/support/tickets/{ticket['id']}/resolve", json={"resolution_notes": "Sent replacement item."}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution_notes"] == "Sent replacement item."
    assert body["resolved_at"] is not None

    resp = client.patch(f"/admin/support/tickets/{ticket['id']}", json={"status": "closed"}, headers=auth_headers)
    resp = client.post(f"/admin/support/tickets/{ticket['id']}/resolve", json={"resolution_notes": "x"}, headers=auth_headers)
    assert resp.status_code == 400


def test_dispute_flag_and_analytics(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id, is_dispute=True, category="payment_issue")
    assert ticket["is_dispute"] is True

    resp = client.get("/admin/support/analytics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tickets"] >= 1
    assert body["open_disputes"] >= 1
    assert body["by_category"]["payment_issue"] >= 1


def test_tickets_isolated_between_organizations(client, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "support_other_org_admin", "email": "support_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org Support",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/admin/support/tickets/{ticket['id']}", headers=other_headers)
    assert resp.status_code == 404


def test_agent_cannot_access_staff_support_routes(client, signed_up_admin, auth_headers, customer_auth_headers):
    order_id = _place_order(client, auth_headers, customer_auth_headers)
    ticket = _create_ticket(client, customer_auth_headers, order_id)
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "support_agent_noperm", "email": "support_agent_noperm@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Agent", "invite_code": invite_code,
        },
    )
    agent_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = client.get(f"/admin/support/tickets/{ticket['id']}", headers=agent_headers)
    assert resp.status_code == 403
