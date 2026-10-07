"""
Tests for customer-facing Google OAuth/SSO (routes/customer_auth.py's
/oauth/google/* and /oauth/exchange, /me/set-password). Mirrors
tests/test_oauth.py's approach (see that file's module docstring) —
monkeypatches GOOGLE_OAUTH_CONFIGURED and oauth_svc's own
exchange_code_for_profile, since this suite never talks to a real
Google account. Notably simpler than the staff flow: no org context
(org_name/invite_code/role) is ever needed for a customer signup.
"""

from app.routes import customer_auth as customer_auth_routes
from app.services import oauth as oauth_svc


def _configure_fake_google(monkeypatch, profile):
    monkeypatch.setattr(oauth_svc, "GOOGLE_OAUTH_CONFIGURED", True)
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setattr(customer_auth_routes.oauth_svc, "exchange_code_for_profile", lambda code, redirect_uri=None: profile)


def _extract_query_param(url: str, key: str) -> str | None:
    from urllib.parse import urlsplit, parse_qs, unquote
    qs = parse_qs(urlsplit(url).query)
    values = qs.get(key)
    return unquote(values[0]) if values else None


def _run_customer_oauth_login(client, monkeypatch, email, name="Google Customer"):
    _configure_fake_google(monkeypatch, profile={"subject_id": f"google-sub-{email}", "email": email, "name": name})
    state_resp = client.get("/customer/oauth/google/login")
    assert state_resp.status_code == 200, state_resp.text
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")

    resp = client.get(f"/customer/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    return location


# ---------- Configuration gating ----------

def test_customer_oauth_login_400s_when_not_configured(client):
    resp = client.get("/customer/oauth/google/login")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["detail"].lower()


def test_customer_oauth_callback_redirects_with_error_when_not_configured(client):
    resp = client.get("/customer/oauth/google/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "customer_oauth_error" in resp.headers["location"]


def test_customer_oauth_login_returns_authorization_url_when_configured(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile=None)
    resp = client.get("/customer/oauth/google/login")
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state=" in url


def test_customer_oauth_uses_a_different_redirect_uri_than_staff(client, monkeypatch):
    # Regression test: both flows previously shared one hardcoded
    # redirect_uri, which meant Google would send a customer sign-in
    # back to the STAFF callback route in a real deployment (this
    # never showed up in the other tests here since they call the
    # callback directly, bypassing Google's own redirect_uri
    # validation entirely).
    _configure_fake_google(monkeypatch, profile=None)
    from urllib.parse import urlsplit, parse_qs

    customer_url = client.get("/customer/oauth/google/login").json()["authorization_url"]
    staff_url = client.get("/auth/oauth/google/login").json()["authorization_url"]

    customer_redirect = parse_qs(urlsplit(customer_url).query)["redirect_uri"][0]
    staff_redirect = parse_qs(urlsplit(staff_url).query)["redirect_uri"][0]

    assert customer_redirect != staff_redirect
    assert customer_redirect.endswith("/customer/oauth/google/callback")
    assert staff_redirect.endswith("/auth/oauth/google/callback")


# ---------- New customer signup via Google — no org context needed ----------

def test_customer_oauth_callback_creates_new_customer(client, monkeypatch):
    location = _run_customer_oauth_login(client, monkeypatch, "newcustomer@example.com", name="New Customer")
    assert "customer_oauth_code" in location
    login_code = _extract_query_param(location, "customer_oauth_code")
    assert login_code

    exchange_resp = client.post("/customer/oauth/exchange", json={"code": login_code})
    assert exchange_resp.status_code == 200, exchange_resp.text
    body = exchange_resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["customer"]["email"] == "newcustomer@example.com"
    assert body["customer"]["name"] == "New Customer"
    assert body["customer"]["oauth_provider"] == "google"
    assert body["customer"]["email_verified"] is True
    assert body["customer"]["has_usable_password"] is False


def test_customer_oauth_callback_repeat_login_same_account(client, monkeypatch):
    location_1 = _run_customer_oauth_login(client, monkeypatch, "repeat@example.com")
    code_1 = _extract_query_param(location_1, "customer_oauth_code")
    first_id = client.post("/customer/oauth/exchange", json={"code": code_1}).json()["customer"]["id"]

    location_2 = _run_customer_oauth_login(client, monkeypatch, "repeat@example.com")
    code_2 = _extract_query_param(location_2, "customer_oauth_code")
    second = client.post("/customer/oauth/exchange", json={"code": code_2})
    assert second.status_code == 200
    assert second.json()["customer"]["id"] == first_id


def test_customer_oauth_callback_links_to_existing_password_account_by_email(client, signed_up_customer, monkeypatch):
    email = signed_up_customer["payload"]["email"]
    customer_id = signed_up_customer["customer"]["id"]

    location = _run_customer_oauth_login(client, monkeypatch, email, name="Via Google Now")
    login_code = _extract_query_param(location, "customer_oauth_code")
    exchange_resp = client.post("/customer/oauth/exchange", json={"code": login_code})
    assert exchange_resp.status_code == 200, exchange_resp.text
    body = exchange_resp.json()
    # Same account (same id), now linked rather than duplicated, and
    # the password-based signup's has_usable_password stays True.
    assert body["customer"]["id"] == customer_id
    assert body["customer"]["oauth_provider"] == "google"
    assert body["customer"]["has_usable_password"] is True


def test_customer_oauth_callback_retroactively_links_past_deliveries(client, db_engine, monkeypatch):
    import uuid
    from datetime import datetime
    from sqlalchemy.orm import sessionmaker
    from app.models.delivery import DeliveryRecordDB, DeliveryStatus

    email = "hadordersbefore@example.com"
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = Session()
    try:
        delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()), order_id=f"ORD-{uuid.uuid4().hex[:8]}", org_id=str(uuid.uuid4()),
            status=DeliveryStatus.pending, customer_email=email, customer_id=None,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        db.add(delivery)
        db.commit()
        delivery_id = delivery.id
    finally:
        db.close()

    location = _run_customer_oauth_login(client, monkeypatch, email)
    login_code = _extract_query_param(location, "customer_oauth_code")
    exchange_resp = client.post("/customer/oauth/exchange", json={"code": login_code})
    customer_id = exchange_resp.json()["customer"]["id"]

    db2 = Session()
    try:
        linked = db2.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
        assert linked.customer_id == customer_id
    finally:
        db2.close()


# ---------- Exchange endpoint security ----------

def test_customer_exchange_rejects_garbage_code(client):
    resp = client.post("/customer/oauth/exchange", json={"code": "not-a-real-token"})
    assert resp.status_code == 401


def test_customer_oauth_callback_reports_google_error_from_query_param(client):
    resp = client.get("/customer/oauth/google/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "customer_oauth_error" in resp.headers["location"]


def test_customer_oauth_callback_rejects_tampered_state(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile={"subject_id": "x", "email": "x@example.com", "name": "X"})
    resp = client.get("/customer/oauth/google/callback?code=fake-code&state=not-a-valid-jwt", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "customer_oauth_error" in resp.headers["location"]


def test_customer_oauth_callback_surfaces_google_exchange_failure(client, monkeypatch):
    monkeypatch.setattr(oauth_svc, "GOOGLE_OAUTH_CONFIGURED", True)
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_SECRET", "fake-client-secret")

    def _raise(code, redirect_uri=None):
        raise oauth_svc.GoogleOAuthError("Google rejected the authorization code (it may be expired or already used).")

    monkeypatch.setattr(customer_auth_routes.oauth_svc, "exchange_code_for_profile", _raise)

    state_resp = client.get("/customer/oauth/google/login")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    resp = client.get(f"/customer/oauth/google/callback?code=bad-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "customer_oauth_error" in resp.headers["location"]


# ---------- Self-service "add a password" for an OAuth-only customer ----------

def test_new_oauth_customer_has_usable_password_false(client, monkeypatch):
    location = _run_customer_oauth_login(client, monkeypatch, "setpwcust1@example.com")
    login_code = _extract_query_param(location, "customer_oauth_code")
    body = client.post("/customer/oauth/exchange", json={"code": login_code}).json()

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me_resp = client.get("/customer/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["has_usable_password"] is False


def test_ordinary_customer_signup_has_usable_password_true(signed_up_customer):
    assert signed_up_customer["customer"]["has_usable_password"] is True


def test_customer_set_password_succeeds_and_then_works_for_login(client, monkeypatch):
    location = _run_customer_oauth_login(client, monkeypatch, "setpwcust2@example.com")
    login_code = _extract_query_param(location, "customer_oauth_code")
    body = client.post("/customer/oauth/exchange", json={"code": login_code}).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    resp = client.post("/customer/me/set-password", json={"new_password": "a-real-password-now"}, headers=headers)
    assert resp.status_code == 200, resp.text

    login_resp = client.post("/customer/login", json={"email": "setpwcust2@example.com", "password": "a-real-password-now"})
    assert login_resp.status_code == 200, login_resp.text


def test_customer_set_password_rejects_short_password(client, monkeypatch):
    location = _run_customer_oauth_login(client, monkeypatch, "setpwcust3@example.com")
    login_code = _extract_query_param(location, "customer_oauth_code")
    body = client.post("/customer/oauth/exchange", json={"code": login_code}).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    resp = client.post("/customer/me/set-password", json={"new_password": "abc"}, headers=headers)
    assert resp.status_code == 400


def test_customer_set_password_rejects_when_already_has_password(client, customer_auth_headers):
    resp = client.post("/customer/me/set-password", json={"new_password": "another-real-password"}, headers=customer_auth_headers)
    assert resp.status_code == 400
    assert "change password" in resp.json()["detail"].lower()


def test_customer_set_password_requires_auth(client):
    resp = client.post("/customer/me/set-password", json={"new_password": "whatever-password"})
    assert resp.status_code in (401, 403)
