"""
Tests for customer subscriptions (routes/subscriptions.py) — recurring
orders that are generated on a schedule but always require the
customer to explicitly pay each cycle (never auto-charged; see
models/subscription.py's module docstring).

These exercise the full lifecycle end to end: create -> run-now ->
initiate-payment -> pay (via the shared /customer/checkout/verify
endpoint, in local/test-mode since no Razorpay keys are configured in
tests) -> a real delivery exists. Also covers pause/resume/cancel,
ownership isolation between customers, validation, and the
insufficient-stock skip-this-item behavior.
"""

from app.models.order import OrderDB, OrderStatus


def _create_product(client, auth_headers, price=50.0, stock=None):
    payload = {"name": "Subscribed Item", "description": "x", "price": price, "is_active": True}
    if stock is not None:
        payload["stock_quantity"] = stock
    resp = client.post("/admin/products/", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _subscription_payload(org_id, product_id, interval_days=7, payment_method="cod", quantity=1):
    return {
        "org_id": org_id,
        "items": [{"product_id": product_id, "quantity": quantity}],
        "interval_days": interval_days,
        "address_line": "12 Test Street",
        "city": "Testville",
        "phone": "9999999999",
        "payment_method": payment_method,
    }


def test_create_subscription_and_list_it(client, auth_headers, signed_up_admin, customer_auth_headers):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id),
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["interval_days"] == 7
    assert len(body["items"]) == 1
    assert body["items"][0]["product_id"] == product_id

    resp = client.get("/customer/subscriptions/", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert any(s["id"] == body["id"] for s in resp.json())


def test_create_subscription_rejects_invalid_interval(client, auth_headers, signed_up_admin, customer_auth_headers):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id, interval_days=0),
        headers=customer_auth_headers,
    )
    assert resp.status_code == 400


def test_create_subscription_rejects_product_from_other_org(client, auth_headers, signed_up_admin, customer_auth_headers):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload("some-other-org-entirely", product_id),
        headers=customer_auth_headers,
    )
    assert resp.status_code == 400


def test_subscription_run_now_initiate_payment_and_verify_creates_delivery(
    client, auth_headers, signed_up_admin, customer_auth_headers
):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers, price=25.0)

    create_resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id, payment_method="online"),
        headers=customer_auth_headers,
    )
    subscription_id = create_resp.json()["id"]

    run_resp = client.post(f"/customer/subscriptions/{subscription_id}/run-now", headers=customer_auth_headers)
    assert run_resp.status_code == 200, run_resp.text
    pending_order_id = run_resp.json()["pending_order_id"]
    assert pending_order_id

    init_resp = client.post(
        f"/customer/subscriptions/orders/{pending_order_id}/initiate-payment",
        headers=customer_auth_headers,
    )
    assert init_resp.status_code == 200, init_resp.text
    init_body = init_resp.json()
    assert init_body["is_test_mode"] is True  # no Razorpay keys configured in tests
    assert init_body["payment_method"] == "online"

    verify_resp = client.post(
        "/customer/checkout/verify",
        json={"order_id": pending_order_id},
        headers=customer_auth_headers,
    )
    assert verify_resp.status_code == 200, verify_resp.text
    order_out = verify_resp.json()
    assert order_out["status"] == "paid"
    assert order_out["delivery_id"]

    # A real delivery now exists, unassigned, in the dispatcher's queue.
    resp = client.get("/deliveries/unassigned", headers=auth_headers)
    assert any(d["id"] == order_out["delivery_id"] for d in resp.json())


def test_subscription_run_now_cod_does_not_need_payment_gateway(
    client, auth_headers, signed_up_admin, customer_auth_headers
):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    create_resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id, payment_method="cod"),
        headers=customer_auth_headers,
    )
    subscription_id = create_resp.json()["id"]

    run_resp = client.post(f"/customer/subscriptions/{subscription_id}/run-now", headers=customer_auth_headers)
    pending_order_id = run_resp.json()["pending_order_id"]

    init_resp = client.post(
        f"/customer/subscriptions/orders/{pending_order_id}/initiate-payment",
        headers=customer_auth_headers,
    )
    assert init_resp.status_code == 200
    assert init_resp.json()["payment_method"] == "cod"
    assert init_resp.json()["razorpay_order_id"] is None


def test_subscription_run_now_skips_out_of_stock_item(
    client, auth_headers, signed_up_admin, customer_auth_headers
):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers, stock=0)

    create_resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id),
        headers=customer_auth_headers,
    )
    subscription_id = create_resp.json()["id"]

    run_resp = client.post(f"/customer/subscriptions/{subscription_id}/run-now", headers=customer_auth_headers)
    # The only item is out of stock -> nothing to generate an order for.
    assert run_resp.status_code == 400


def test_subscription_pause_resume_and_cancel(client, auth_headers, signed_up_admin, customer_auth_headers):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    create_resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id),
        headers=customer_auth_headers,
    )
    subscription_id = create_resp.json()["id"]

    resp = client.post(f"/customer/subscriptions/{subscription_id}/pause", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    # A paused subscription can't be run.
    resp = client.post(f"/customer/subscriptions/{subscription_id}/run-now", headers=customer_auth_headers)
    assert resp.status_code == 400

    resp = client.post(f"/customer/subscriptions/{subscription_id}/resume", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    resp = client.post(f"/customer/subscriptions/{subscription_id}/cancel", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # A cancelled subscription can't be updated or resumed.
    resp = client.patch(f"/customer/subscriptions/{subscription_id}", json={"interval_days": 14}, headers=customer_auth_headers)
    assert resp.status_code == 400
    resp = client.post(f"/customer/subscriptions/{subscription_id}/resume", headers=customer_auth_headers)
    assert resp.status_code == 400


def test_subscription_ownership_is_isolated_between_customers(
    client, auth_headers, signed_up_admin, customer_auth_headers
):
    org_id = signed_up_admin["user"]["org_id"]
    product_id = _create_product(client, auth_headers)

    create_resp = client.post(
        "/customer/subscriptions/",
        json=_subscription_payload(org_id, product_id),
        headers=customer_auth_headers,
    )
    subscription_id = create_resp.json()["id"]

    # A second, unrelated customer must not be able to see or act on it.
    other_signup = client.post(
        "/customer/signup",
        json={"email": "other_subscriber@example.com", "password": "correct-horse-battery", "name": "Other Customer"},
    )
    other_token = other_signup.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    resp = client.get("/customer/subscriptions/", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post(f"/customer/subscriptions/{subscription_id}/pause", headers=other_headers)
    assert resp.status_code == 404
