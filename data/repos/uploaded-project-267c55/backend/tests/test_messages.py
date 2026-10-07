"""
Tests for Phase 6 — Customer <-> Agent Communication:
- Staff and customer can both post into the SAME delivery thread
- Read/unread tracking on both sides (staff sweep, customer sweep)
- Unread-count endpoints on both sides
- Predefined message templates
- Authorization: unassigned agent blocked; customer can't read another
  customer's delivery thread; tenant isolation
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


def _create_delivery_for_customer(client, auth_headers, agent_id, customer_email):
    delivery_id = str(uuid.uuid4())
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    resp = client.post(
        "/deliveries/",
        json={
            "id": delivery_id, "agent_id": agent_id, "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
            "status": "pending", "created_at": now, "updated_at": now, "customer_email": customer_email,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return delivery_id


# ---------- Shared thread: staff <-> customer ----------

def test_staff_and_customer_share_one_message_thread(client, signed_up_admin, auth_headers, customer_auth_headers, signed_up_customer):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "msg_agent_1")
    customer_email = signed_up_customer["payload"]["email"]
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, customer_email)

    resp = client.post(f"/deliveries/{delivery_id}/messages", json={"message": "I'm arriving in a few minutes."}, headers=agent_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/customer/deliveries/{delivery_id}/messages", json={"message": "Great, thank you!"}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    staff_view = client.get(f"/deliveries/{delivery_id}/messages", headers=agent_headers).json()
    customer_view = client.get(f"/customer/deliveries/{delivery_id}/messages", headers=customer_auth_headers).json()
    assert len(staff_view) == 2
    assert len(customer_view) == 2
    assert [m["message"] for m in staff_view] == [m["message"] for m in customer_view]
    assert staff_view[0]["sender_role"] == "agent"
    assert staff_view[1]["sender_role"] == "customer"


def test_dispatcher_can_message_any_delivery_in_org(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "msg_agent_dispatcher_test")
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, "someone@example.com")

    resp = client.post(f"/deliveries/{delivery_id}/messages", json={"message": "Dispatcher note"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text


# ---------- Read/unread state ----------

def test_staff_message_marked_read_by_customer_on_view(client, signed_up_admin, auth_headers, customer_auth_headers, signed_up_customer):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "msg_read_agent")
    customer_email = signed_up_customer["payload"]["email"]
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, customer_email)

    client.post(f"/deliveries/{delivery_id}/messages", json={"message": "Unread test"}, headers=agent_headers)

    resp = client.get(f"/customer/deliveries/{delivery_id}/messages/unread-count", headers=customer_auth_headers)
    assert resp.json()["unread_count"] == 1

    # viewing the thread marks it read
    client.get(f"/customer/deliveries/{delivery_id}/messages", headers=customer_auth_headers)

    resp = client.get(f"/customer/deliveries/{delivery_id}/messages/unread-count", headers=customer_auth_headers)
    assert resp.json()["unread_count"] == 0


def test_customer_message_marked_read_by_staff_on_view(client, signed_up_admin, auth_headers, customer_auth_headers, signed_up_customer):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "msg_read_staff_agent")
    customer_email = signed_up_customer["payload"]["email"]
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, customer_email)

    client.post(f"/customer/deliveries/{delivery_id}/messages", json={"message": "Where are you?"}, headers=customer_auth_headers)

    resp = client.get(f"/deliveries/{delivery_id}/messages/unread-count", headers=agent_headers)
    assert resp.json()["unread_count"] == 1

    client.get(f"/deliveries/{delivery_id}/messages", headers=agent_headers)

    resp = client.get(f"/deliveries/{delivery_id}/messages/unread-count", headers=agent_headers)
    assert resp.json()["unread_count"] == 0


# ---------- Predefined templates ----------

def test_predefined_message_templates_available_and_usable(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "msg_template_agent")

    resp = client.get("/message-templates", headers=agent_headers)
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    assert len(templates) >= 4
    assert any("arriving" in t.lower() for t in templates)

    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, "template_test@example.com")
    resp = client.post(f"/deliveries/{delivery_id}/messages", json={"message": templates[0]}, headers=agent_headers)
    assert resp.status_code == 200


# ---------- Authorization ----------

def test_unassigned_agent_cannot_message_delivery(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    owner_id, _ = _signup_agent(client, invite_code, "msg_owner_agent")
    _, intruder_headers = _signup_agent(client, invite_code, "msg_intruder_agent")
    delivery_id = _create_delivery_for_customer(client, auth_headers, owner_id, "owned@example.com")

    resp = client.post(f"/deliveries/{delivery_id}/messages", json={"message": "Snooping"}, headers=intruder_headers)
    assert resp.status_code == 403

    resp = client.get(f"/deliveries/{delivery_id}/messages", headers=intruder_headers)
    assert resp.status_code == 403


def test_customer_cannot_read_another_customers_delivery_thread(client, signed_up_admin, auth_headers, customer_auth_headers, signed_up_customer):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "msg_other_cust_agent")
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, "not_this_customer@example.com")

    resp = client.get(f"/customer/deliveries/{delivery_id}/messages", headers=customer_auth_headers)
    assert resp.status_code == 404

    resp = client.post(f"/customer/deliveries/{delivery_id}/messages", json={"message": "Hi"}, headers=customer_auth_headers)
    assert resp.status_code == 404


def test_messages_isolated_between_organizations(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "msg_iso_agent")
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, "iso@example.com")

    other_resp = client.post(
        "/auth/signup",
        json={"username": "msg_other_org_admin", "email": "msg_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org Msg"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/deliveries/{delivery_id}/messages", headers=other_headers)
    assert resp.status_code == 404


def test_empty_message_rejected(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "msg_empty_agent")
    delivery_id = _create_delivery_for_customer(client, auth_headers, agent_id, "empty@example.com")

    resp = client.post(f"/deliveries/{delivery_id}/messages", json={"message": "   "}, headers=agent_headers)
    assert resp.status_code == 400
