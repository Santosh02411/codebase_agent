"""
Tests for Phase 10 - Customer Communication & Notifications:
- Notification template CRUD (view defaults, customize, reset to default)
- Permission gating (settings.view / settings.manage)
- Tenant isolation
- refund_processed notification actually fires on a real refund (in-app)
- return_approved notification actually fires on a real approval (in-app)
- Delivery reminder scan: sends once, respects the window, never double-sends
- Subscription reminder scan: sends once, respects the window
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.subscription import SubscriptionDB, SubscriptionStatus
from app.services.reminder_scheduler import run_delivery_reminder_scan, run_subscription_reminder_scan


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={"username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
              "role": "agent", "display_name": username, "invite_code": invite_code},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def test_list_effective_templates_returns_defaults_initially(client, auth_headers):
    resp = client.get("/admin/notification-templates/", headers=auth_headers)
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) == 5
    assert all(t["is_default"] for t in templates)
    refund_template = next(t for t in templates if t["event_type"] == "refund_processed")
    assert refund_template["body"]


def test_customize_and_reset_template(client, auth_headers):
    resp = client.put(
        "/admin/notification-templates/refund_processed",
        json={"subject": "Refund done!", "body": "We refunded order {order_id}.", "email_enabled": True, "sms_enabled": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_default"] is False
    assert resp.json()["subject"] == "Refund done!"
    assert resp.json()["sms_enabled"] is True

    resp = client.get("/admin/notification-templates/", headers=auth_headers)
    refund_template = next(t for t in resp.json() if t["event_type"] == "refund_processed")
    assert refund_template["is_default"] is False
    assert refund_template["subject"] == "Refund done!"

    resp = client.delete("/admin/notification-templates/refund_processed", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/admin/notification-templates/", headers=auth_headers)
    refund_template = next(t for t in resp.json() if t["event_type"] == "refund_processed")
    assert refund_template["is_default"] is True


def test_unknown_event_type_rejected(client, auth_headers):
    resp = client.put(
        "/admin/notification-templates/not_a_real_event",
        json={"subject": "X", "body": "Y"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_dispatcher_can_view_but_not_edit_templates(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={"username": "notif_dispatcher", "email": "notif_dispatcher@example.com", "password": "correct-horse-battery",
              "role": "dispatcher", "display_name": "Notif Dispatcher", "invite_code": invite_code},
    )
    dispatcher_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.get("/admin/notification-templates/", headers=dispatcher_headers)
    assert resp.status_code == 200

    resp = client.put("/admin/notification-templates/refund_processed", json={"subject": "X", "body": "Y"}, headers=dispatcher_headers)
    assert resp.status_code == 403


def test_templates_isolated_between_organizations(client, auth_headers, signed_up_admin):
    client.put("/admin/notification-templates/refund_processed", json={"subject": "Org A wording", "body": "X {order_id}"}, headers=auth_headers)

    other_resp = client.post(
        "/auth/signup",
        json={"username": "notif_other_org_admin", "email": "notif_other_org_admin@example.com",
              "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
              "org_name": "Other Org Notif"},
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get("/admin/notification-templates/", headers=other_headers)
    refund_template = next(t for t in resp.json() if t["event_type"] == "refund_processed")
    assert refund_template["is_default"] is True


def test_refund_processed_notification_fires_on_real_refund(client, signed_up_admin, auth_headers, customer_auth_headers):
    client.put(
        "/admin/notification-templates/refund_processed",
        json={"subject": "Refunded", "body": "REFUND_MARKER for order {order_id}"},
        headers=auth_headers,
    )

    product = client.post("/admin/products/", json={"name": "Notif Refund Item", "price": 15.0, "is_active": True}, headers=auth_headers).json()
    client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    checkout_resp = client.post("/customer/checkout", json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "online"}, headers=customer_auth_headers)
    order = client.post("/customer/checkout/verify", json={"order_id": checkout_resp.json()["order_id"]}, headers=customer_auth_headers).json()

    resp = client.post(f"/customer/deliveries/{order['delivery_id']}/cancel", headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/customer/notifications", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert any("REFUND_MARKER" in n["message"] for n in resp.json())


def test_return_approved_notification_fires_on_real_approval(client, signed_up_admin, auth_headers, customer_auth_headers):
    client.put(
        "/admin/notification-templates/return_approved",
        json={"subject": "Return OK", "body": "RETURN_MARKER for order {order_id}"},
        headers=auth_headers,
    )
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "notif_return_agent")

    product = client.post("/admin/products/", json={"name": "Notif Return Item", "price": 12.0, "is_active": True}, headers=auth_headers).json()
    client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    checkout_resp = client.post("/customer/checkout", json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "online"}, headers=customer_auth_headers)
    order = client.post("/customer/checkout/verify", json={"order_id": checkout_resp.json()["order_id"]}, headers=customer_auth_headers).json()
    delivery_id = order["delivery_id"]

    client.patch(f"/deliveries/{delivery_id}/assign-agent", json={"agent_id": agent_id}, headers=auth_headers)
    now = datetime.utcnow().isoformat()
    client.patch(f"/deliveries/{delivery_id}", json={"status": "out_for_delivery", "updated_at": now}, headers=agent_headers)
    now = datetime.utcnow().isoformat()
    client.patch(f"/deliveries/{delivery_id}", json={"status": "delivered", "updated_at": now}, headers=agent_headers)

    resp = client.post(
        "/customer/return-requests",
        json={"order_id": order["id"], "delivery_id": delivery_id, "reason": "Changed my mind", "request_type": "return"},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    request_id = resp.json()["id"]

    resp = client.post(f"/admin/return-requests/{request_id}/approve", json={"resolution_note": "Approved"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/customer/notifications", headers=customer_auth_headers)
    assert any("RETURN_MARKER" in n["message"] for n in resp.json())


def test_delivery_reminder_sent_once_within_window(client, signed_up_admin, auth_headers, db_engine):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "notif_reminder_agent")
    org_id = signed_up_admin["user"]["org_id"]

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        now = datetime.utcnow()
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id="REMIND-1", org_id=org_id, status=DeliveryStatus.pending,
            agent_id=agent_id, customer_id="fake-customer-id", customer_email="reminder_test@example.com",
            created_at=now, updated_at=now, slot_start=now + timedelta(hours=5), slot_end=now + timedelta(hours=6),
        )
        db.add(delivery)
        db.commit()

        sent = run_delivery_reminder_scan(db)
        assert sent == 1

        db.refresh(delivery)
        assert delivery.reminder_sent_at is not None

        sent_again = run_delivery_reminder_scan(db)
        assert sent_again == 0
    finally:
        db.close()


def test_delivery_reminder_respects_window(client, signed_up_admin, auth_headers, db_engine):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "notif_reminder_window_agent")
    org_id = signed_up_admin["user"]["org_id"]

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        now = datetime.utcnow()
        far_delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id="REMIND-FAR", org_id=org_id, status=DeliveryStatus.pending,
            agent_id=agent_id, customer_id="fake-customer-id-2", customer_email="reminder_far@example.com",
            created_at=now, updated_at=now, slot_start=now + timedelta(days=5), slot_end=now + timedelta(days=5, hours=1),
        )
        db.add(far_delivery)
        db.commit()

        run_delivery_reminder_scan(db)
        db.refresh(far_delivery)
        assert far_delivery.reminder_sent_at is None
    finally:
        db.close()


def test_subscription_reminder_sent_once_within_window(client, signed_up_admin, auth_headers, db_engine):
    org_id = signed_up_admin["user"]["org_id"]
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        now = datetime.utcnow()
        subscription = SubscriptionDB(
            id=str(uuid.uuid4()), customer_id="fake-sub-customer", org_id=org_id, status=SubscriptionStatus.active,
            interval_days=30, next_run_date=now + timedelta(days=1),
            address_line="1 Test St", phone="9999999999", payment_method="online",
            created_at=now,
        )
        db.add(subscription)
        db.commit()

        sent = run_subscription_reminder_scan(db)
        assert sent == 1
        db.refresh(subscription)
        assert subscription.reminder_sent_at is not None

        sent_again = run_subscription_reminder_scan(db)
        assert sent_again == 0
    finally:
        db.close()
