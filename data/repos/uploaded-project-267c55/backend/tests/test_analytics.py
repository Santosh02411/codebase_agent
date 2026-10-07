"""
Tests for routes/analytics.py — the admin revenue/order/fulfillment
dashboard, computed on the fly from Order/OrderItem/Delivery rows (see
that file's module docstring for why it's not a maintained rollup).

One end-to-end test exercises the real flow (cart -> checkout -> COD
verify) to prove a genuinely placed order shows up correctly. The rest
insert OrderDB/DeliveryRecordDB rows directly, since analytics.py
doesn't care how an order got there and direct inserts make the
day-bucketing / low-stock / status-breakdown assertions exact and fast.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.order import OrderDB, OrderItemDB, OrderStatus
from app.models.delivery import DeliveryRecordDB, DeliveryStatus


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _insert_paid_order(db_engine, org_id, total, created_at, product_id="prod-1", product_name="Widget", quantity=1, unit_price=None, refunded=False):
    db = _session_for(db_engine)
    try:
        order = OrderDB(
            id=str(uuid.uuid4()),
            customer_id="cust-1",
            org_id=org_id,
            status=OrderStatus.paid,
            address_line="1 Test St",
            phone="9999999999",
            subtotal=total,
            total=total,
            payment_method="cod",
            created_at=created_at,
            refund_status="refunded" if refunded else None,
        )
        db.add(order)
        db.flush()
        db.add(OrderItemDB(
            id=str(uuid.uuid4()), order_id=order.id, product_id=product_id,
            product_name=product_name, unit_price=unit_price if unit_price is not None else total, quantity=quantity,
        ))
        db.commit()
        return order.id
    finally:
        db.close()


def _insert_delivery(db_engine, org_id, status):
    db = _session_for(db_engine)
    try:
        d = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id=f"ORD-{uuid.uuid4().hex[:8]}", org_id=org_id,
            status=status, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        db.add(d)
        db.commit()
    finally:
        db.close()


def test_analytics_reflects_a_real_checkout(client, auth_headers, signed_up_admin, customer_auth_headers):
    org_id = signed_up_admin["user"]["org_id"]
    product = client.post(
        "/admin/products/", json={"name": "Real Item", "price": 40.0, "is_active": True}, headers=auth_headers
    ).json()

    resp = client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 2}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "cod"},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order_id = resp.json()["order_id"]

    resp = client.post("/customer/checkout/verify", json={"order_id": order_id}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/analytics/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_orders"] == 1
    # total_revenue reflects order.total (subtotal + delivery_fee + tax),
    # not just the product subtotal — orgs default to a $40 delivery fee
    # and 5% tax (see models/organization.py), so 2x$40 subtotal becomes
    # 80 + 40 delivery fee + 5% tax on 80 = 124.
    assert data["total_revenue"] == 124.0
    assert any(p["product_id"] == product["id"] and p["quantity_sold"] == 2 for p in data["top_products"])


def test_analytics_revenue_by_day_is_zero_filled(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    _insert_paid_order(db_engine, org_id, total=100.0, created_at=datetime.utcnow())

    resp = client.get("/admin/analytics/", headers=auth_headers, params={"days": 5})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["revenue_by_day"]) == 5
    # Exactly one day (today) has revenue; the rest are zero-filled.
    non_zero_days = [d for d in data["revenue_by_day"] if d["revenue"] > 0]
    assert len(non_zero_days) == 1
    assert non_zero_days[0]["revenue"] == 100.0


def test_analytics_excludes_orders_outside_the_window(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    _insert_paid_order(db_engine, org_id, total=50.0, created_at=datetime.utcnow() - timedelta(days=90))

    resp = client.get("/admin/analytics/", headers=auth_headers, params={"days": 30})
    assert resp.status_code == 200
    assert resp.json()["total_orders"] == 0
    assert resp.json()["total_revenue"] == 0.0


def test_analytics_refund_totals(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    _insert_paid_order(db_engine, org_id, total=60.0, created_at=datetime.utcnow(), refunded=True)
    _insert_paid_order(db_engine, org_id, total=40.0, created_at=datetime.utcnow())

    resp = client.get("/admin/analytics/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_orders"] == 2
    assert data["total_revenue"] == 100.0
    assert data["refunded_order_count"] == 1
    assert data["total_refunded"] == 60.0


def test_analytics_delivery_status_breakdown(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    _insert_delivery(db_engine, org_id, DeliveryStatus.pending)
    _insert_delivery(db_engine, org_id, DeliveryStatus.pending)
    _insert_delivery(db_engine, org_id, DeliveryStatus.delivered)

    resp = client.get("/admin/analytics/", headers=auth_headers)
    assert resp.status_code == 200
    breakdown = resp.json()["delivery_status_breakdown"]
    assert breakdown["pending"] == 2
    assert breakdown["delivered"] == 1
    assert breakdown["cancelled"] == 0


def test_analytics_low_stock_products(client, auth_headers, signed_up_admin):
    low = client.post(
        "/admin/products/", json={"name": "Almost Out", "price": 5.0, "is_active": True, "stock_quantity": 2},
        headers=auth_headers,
    ).json()
    plenty = client.post(
        "/admin/products/", json={"name": "Well Stocked", "price": 5.0, "is_active": True, "stock_quantity": 500},
        headers=auth_headers,
    ).json()

    resp = client.get("/admin/analytics/", headers=auth_headers)
    assert resp.status_code == 200
    low_stock_ids = [p["id"] for p in resp.json()["low_stock_products"]]
    assert low["id"] in low_stock_ids
    assert plenty["id"] not in low_stock_ids


def test_analytics_is_org_scoped(client, db_engine, auth_headers, admin_signup_payload):
    other_org_id = "other-org-" + uuid.uuid4().hex[:8]
    _insert_paid_order(db_engine, other_org_id, total=1000.0, created_at=datetime.utcnow())

    resp = client.get("/admin/analytics/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total_revenue"] == 0.0


def test_analytics_requires_admin_role(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_signup = client.post(
        "/auth/signup",
        json={
            "username": "analytics_agent",
            "email": "analytics_agent@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": "Analytics Agent",
            "invite_code": invite_code,
        },
    )
    agent_token = agent_signup.json()["access_token"]

    resp = client.get("/admin/analytics/", headers={"Authorization": f"Bearer {agent_token}"})
    assert resp.status_code == 403
