"""
Tests for Phase 15 — Advanced Analytics:
- Agent productivity: delivered/failed counts per agent, on-time rate
- Failed delivery analytics: reason-code breakdown, failure rate
- Return/cancellation analytics
- Customer retention / repeat-order rate
- Revenue breakdowns by category and payment method
- Profit margin: only counts products with cost_price set, reports
  products_missing_cost_price honestly
- Trend/forecast: naive, clearly labeled
- Admin-only access
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.delivery_attempt import DeliveryAttemptDB


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _make_delivery(db_engine, org_id, status, agent_id=None, sla_status="not_applicable"):
    db = _session_for(db_engine)
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id=f"ORD-{uuid.uuid4().hex[:8]}", org_id=org_id,
            status=status, agent_id=agent_id, sla_status=sla_status,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery.id
    finally:
        db.close()


def _make_attempt(db_engine, org_id, delivery_id, agent_id, outcome, reason_label=None):
    db = _session_for(db_engine)
    try:
        attempt = DeliveryAttemptDB(
            id=str(uuid.uuid4()), delivery_id=delivery_id, org_id=org_id, agent_id=agent_id,
            attempt_number=1, outcome=outcome, reason_label=reason_label, attempted_at=datetime.utcnow(),
        )
        db.add(attempt)
        db.commit()
    finally:
        db.close()


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
            "role": "agent", "display_name": username, "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["user"]["id"]


def _place_order(client, auth_headers, customer_auth_headers, price=100.0, category=None, cost_price=None, payment_method="cod"):
    payload = {"name": "Analytics Item", "price": price, "is_active": True}
    if category:
        payload["category"] = category
    if cost_price is not None:
        payload["cost_price"] = cost_price
    product = client.post("/admin/products/", json=payload, headers=auth_headers).json()
    resp = client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": payment_method},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = resp.json()
    resp = client.post("/customer/checkout/verify", json={"order_id": order["order_id"]}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- Access control ----------

def test_only_admin_can_access_advanced_analytics(client, signed_up_admin, auth_headers):
    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    assert resp.status_code == 200

    invite_code = signed_up_admin["org_invite_code"]
    dispatcher_resp = client.post(
        "/auth/signup",
        json={
            "username": "adv_analytics_dispatcher", "email": "adv_analytics_dispatcher@example.com",
            "password": "correct-horse-battery", "role": "dispatcher", "display_name": "Dispatcher", "invite_code": invite_code,
        },
    )
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_resp.json()['access_token']}"}
    resp = client.get("/admin/analytics/advanced/", headers=dispatcher_headers)
    assert resp.status_code == 403


# ---------- Agent productivity & failed deliveries ----------

def test_agent_productivity_and_failed_delivery_breakdown(client, signed_up_admin, auth_headers, db_engine):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "adv_agent_1")

    d1 = _make_delivery(db_engine, org_id, DeliveryStatus.delivered, agent_id=agent_id, sla_status="met")
    d2 = _make_delivery(db_engine, org_id, DeliveryStatus.delivered, agent_id=agent_id, sla_status="missed")
    d3 = _make_delivery(db_engine, org_id, DeliveryStatus.failed_attempt, agent_id=agent_id)
    _make_attempt(db_engine, org_id, d1, agent_id, "delivered")
    _make_attempt(db_engine, org_id, d2, agent_id, "delivered")
    _make_attempt(db_engine, org_id, d3, agent_id, "failed_attempt", reason_label="Customer unavailable")

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    productivity = next(a for a in body["agent_productivity"] if a["agent_id"] == agent_id)
    assert productivity["delivered_count"] == 2
    assert productivity["failed_count"] == 1
    assert productivity["on_time_rate"] == 50.0

    failed = body["failed_delivery_analytics"]
    assert failed["total_failed"] == 1
    assert failed["by_reason"]["Customer unavailable"] == 1
    assert failed["failure_rate_percent"] > 0


def test_agent_with_no_deliveries_has_none_on_time_rate(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id = _signup_agent(client, invite_code, "adv_agent_idle")
    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    productivity = next(a for a in resp.json()["agent_productivity"] if a["agent_id"] == agent_id)
    assert productivity["delivered_count"] == 0
    assert productivity["on_time_rate"] is None


# ---------- Return/cancellation ----------

def test_return_and_cancellation_analytics(client, auth_headers, customer_auth_headers):
    body = _place_order(client, auth_headers, customer_auth_headers)
    delivery_id = body["delivery_id"]

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    before = resp.json()["return_and_cancellation_analytics"]["total_cancelled"]

    resp = client.post(f"/customer/deliveries/{delivery_id}/cancel", headers=customer_auth_headers)
    assert resp.status_code == 200

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    after = resp.json()["return_and_cancellation_analytics"]
    assert after["total_cancelled"] == before + 1
    assert after["cancellation_rate_percent"] > 0


# ---------- Customer retention ----------

def test_customer_retention_repeat_order_rate(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers)
    _place_order(client, auth_headers, customer_auth_headers)  # same customer, second order

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    retention = resp.json()["customer_retention"]
    assert retention["unique_customers"] >= 1
    assert retention["repeat_customers"] >= 1
    assert retention["repeat_order_rate_percent"] > 0


# ---------- Revenue breakdowns & profit margin ----------

def test_revenue_breakdown_by_category_and_payment_method(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers, category="Snacks", payment_method="cod")
    _place_order(client, auth_headers, customer_auth_headers, category="Snacks", payment_method="online")

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    breakdown = resp.json()["revenue_breakdowns"]
    assert breakdown["by_category"]["Snacks"] > 0
    assert breakdown["by_payment_method"]["cod"] > 0
    assert breakdown["by_payment_method"]["online"] > 0


def test_profit_margin_excludes_products_without_cost_price(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers, price=100.0, cost_price=60.0)
    _place_order(client, auth_headers, customer_auth_headers, price=50.0)  # no cost_price set

    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    margin = resp.json()["profit_margin"]
    # Only the 100/60 product contributes to revenue/cost; the no-cost-price product is excluded, not assumed free.
    assert margin["revenue"] == 100.0
    assert margin["cost"] == 60.0
    assert margin["profit"] == 40.0
    assert margin["products_missing_cost_price"] == 1


def test_profit_margin_with_no_orders_reports_null_margin(client, auth_headers):
    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    margin = resp.json()["profit_margin"]
    assert margin["margin_percent"] is None


# ---------- Trend & forecast ----------

def test_trend_and_forecast_is_labeled_naive(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers, price=140.0)
    resp = client.get("/admin/analytics/advanced/", headers=auth_headers)
    trend = resp.json()["trend_and_forecast"]
    assert trend["current_period_revenue"] >= 140.0
    assert "naive" in trend["forecast_method"].lower()
    assert trend["naive_7_day_forecast"] >= 0


def test_advanced_analytics_isolated_between_organizations(client, signed_up_admin, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers, price=999.0, category="ShouldNotLeak")

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "adv_analytics_other_org_admin", "email": "adv_analytics_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org Analytics",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get("/admin/analytics/advanced/", headers=other_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "ShouldNotLeak" not in body["revenue_breakdowns"]["by_category"]
    assert body["profit_margin"]["revenue"] == 0.0
