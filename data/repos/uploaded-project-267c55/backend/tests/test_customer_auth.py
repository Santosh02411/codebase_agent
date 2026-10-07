"""Customer-facing signup/login — the separate CustomerDB identity used
by the storefront, distinct from staff accounts in test_auth.py."""


def test_customer_signup_returns_token(client, customer_signup_payload):
    resp = client.post("/customer/signup", json=customer_signup_payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["customer"]["email"] == customer_signup_payload["email"]


def test_customer_signup_duplicate_email_rejected(client, customer_signup_payload):
    client.post("/customer/signup", json=customer_signup_payload)
    resp = client.post("/customer/signup", json=customer_signup_payload)
    assert resp.status_code == 400


def test_customer_login(client, signed_up_customer):
    payload = signed_up_customer["payload"]
    resp = client.post(
        "/customer/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert resp.status_code == 200


def test_customer_login_wrong_password(client, signed_up_customer):
    payload = signed_up_customer["payload"]
    resp = client.post(
        "/customer/login",
        json={"email": payload["email"], "password": "nope-not-it"},
    )
    assert resp.status_code in (400, 401)


def test_customer_me_requires_auth(client):
    resp = client.get("/customer/me")
    assert resp.status_code in (401, 403)


def test_customer_me_with_token(client, customer_auth_headers):
    resp = client.get("/customer/me", headers=customer_auth_headers)
    assert resp.status_code == 200


def test_staff_token_cannot_access_customer_me(client, auth_headers):
    """A staff (org) JWT should not double as a customer session — the
    two identity systems are intentionally separate (see
    delivery-sync-project notes: 'global CustomerDB identity' as its
    own thing from org staff accounts)."""
    resp = client.get("/customer/me", headers=auth_headers)
    assert resp.status_code in (401, 403)
