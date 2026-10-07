"""
Tests for Google OAuth/SSO (routes/auth.py's /oauth/google/* and
/oauth/exchange, services/oauth.py). Since this project's test suite
never talks to a real Google account, every test here monkeypatches
GOOGLE_OAUTH_CONFIGURED true and oauth_svc.exchange_code_for_profile
to return a fake profile — exactly the seam services/oauth.py exists
to provide (see its module docstring).
"""

from app.routes import auth as auth_routes
from app.services import oauth as oauth_svc
from app.models.user import UserDB


def _configure_fake_google(monkeypatch, profile):
    monkeypatch.setattr(oauth_svc, "GOOGLE_OAUTH_CONFIGURED", True)
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setattr(auth_routes.oauth_svc, "exchange_code_for_profile", lambda code: profile)


def _extract_query_param(url: str, key: str) -> str | None:
    from urllib.parse import urlsplit, parse_qs, unquote
    qs = parse_qs(urlsplit(url).query)
    values = qs.get(key)
    return unquote(values[0]) if values else None


# ---------- Configuration gating ----------

def test_oauth_login_400s_when_not_configured(client):
    resp = client.get("/auth/oauth/google/login")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["detail"].lower()


def test_oauth_callback_redirects_with_error_when_not_configured(client):
    resp = client.get("/auth/oauth/google/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


# ---------- Starting the flow ----------

def test_oauth_login_returns_authorization_url_when_configured(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile=None)
    resp = client.get("/auth/oauth/google/login?org_name=My+New+Org")
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state=" in url


def test_oauth_login_rejects_invalid_role(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile=None)
    resp = client.get("/auth/oauth/google/login?invite_code=SOMECODE&role=superuser")
    assert resp.status_code == 400


# ---------- New user signup via Google (creating a new org) ----------

def test_oauth_callback_creates_new_org_and_admin_user(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-001",
        "email": "newgoogleuser@example.com",
        "name": "New Google User",
    })

    state_resp = client.get("/auth/oauth/google/login?org_name=Acme+Logistics")
    assert state_resp.status_code == 200
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    assert state

    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert "oauth_code" in location
    login_code = _extract_query_param(location, "oauth_code")
    assert login_code

    exchange_resp = client.post("/auth/oauth/exchange", json={"code": login_code})
    assert exchange_resp.status_code == 200, exchange_resp.text
    body = exchange_resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "newgoogleuser@example.com"
    assert body["user"]["role"] == "admin"  # org creator always becomes admin, same as signup
    assert body["user"]["oauth_provider"] == "google"
    assert body["user"]["email_verified"] is True


# ---------- New user signup via Google (joining an existing org) ----------

def test_oauth_callback_joins_existing_org_via_invite_code_never_as_admin(client, monkeypatch, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]

    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-002",
        "email": "joiner@example.com",
        "name": "Joiner",
    })

    state_resp = client.get(f"/auth/oauth/google/login?invite_code={invite_code}&role=admin")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")

    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    login_code = _extract_query_param(resp.headers["location"], "oauth_code")

    exchange_resp = client.post("/auth/oauth/exchange", json={"code": login_code})
    assert exchange_resp.status_code == 200, exchange_resp.text
    body = exchange_resp.json()
    # Requested role="admin" via invite code must be downgraded, same
    # anti-privilege-escalation rule as ordinary signup.
    assert body["user"]["role"] == "agent"
    assert body["user"]["org_id"] == signed_up_admin["user"]["org_id"]


def test_oauth_callback_rejects_bad_invite_code(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-003",
        "email": "someone@example.com",
        "name": "Someone",
    })
    state_resp = client.get("/auth/oauth/google/login?invite_code=NOTREAL999")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")

    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


def test_oauth_callback_with_no_org_context_errors(client, monkeypatch):
    # start_google_oauth_login defaults role but requires org_name or
    # invite_code for a genuinely new account — omit both.
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-004",
        "email": "noorg@example.com",
        "name": "No Org",
    })
    state_resp = client.get("/auth/oauth/google/login")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")

    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


# ---------- Existing user: repeat login via Google ----------

def test_oauth_callback_logs_in_already_linked_user(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-005",
        "email": "repeatuser@example.com",
        "name": "Repeat User",
    })
    state_resp = client.get("/auth/oauth/google/login?org_name=Repeat+Co")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    login_code = _extract_query_param(resp.headers["location"], "oauth_code")
    first_exchange = client.post("/auth/oauth/exchange", json={"code": login_code}).json()
    first_user_id = first_exchange["user"]["id"]

    # Log in again via Google — same Google subject id, no org context
    # needed this time since the account already exists and is linked.
    state_resp_2 = client.get("/auth/oauth/google/login")
    state_2 = _extract_query_param(state_resp_2.json()["authorization_url"], "state")
    resp_2 = client.get(f"/auth/oauth/google/callback?code=fake-code-2&state={state_2}", follow_redirects=False)
    login_code_2 = _extract_query_param(resp_2.headers["location"], "oauth_code")
    second_exchange = client.post("/auth/oauth/exchange", json={"code": login_code_2})
    assert second_exchange.status_code == 200, second_exchange.text
    assert second_exchange.json()["user"]["id"] == first_user_id


# ---------- Linking Google to an existing password account by email ----------

def test_oauth_callback_links_google_to_existing_password_account_by_email(client, db_engine, monkeypatch, signed_up_admin):
    admin_email = signed_up_admin["user"]["email"]
    admin_id = signed_up_admin["user"]["id"]

    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-linked",
        "email": admin_email,
        "name": "Admin Via Google",
    })
    state_resp = client.get("/auth/oauth/google/login")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    login_code = _extract_query_param(resp.headers["location"], "oauth_code")

    exchange_resp = client.post("/auth/oauth/exchange", json={"code": login_code})
    assert exchange_resp.status_code == 200, exchange_resp.text
    body = exchange_resp.json()
    # Same account (same id), now linked rather than duplicated.
    assert body["user"]["id"] == admin_id
    assert body["user"]["oauth_provider"] == "google"


# ---------- Exchange endpoint security ----------

def test_exchange_rejects_garbage_code(client):
    resp = client.post("/auth/oauth/exchange", json={"code": "not-a-real-token"})
    assert resp.status_code == 401


def test_exchange_rejects_a_real_access_token_used_as_login_code(client, auth_headers):
    # An ordinary access token has a different claim shape
    # ({"sub": ...} not {"oauth_login_user_id": ...}) and must not be
    # accepted here even though it's validly signed.
    token = auth_headers["Authorization"].split(" ", 1)[1]
    resp = client.post("/auth/oauth/exchange", json={"code": token})
    assert resp.status_code == 401


def test_oauth_callback_reports_google_error_from_query_param(client):
    resp = client.get("/auth/oauth/google/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


# ---------- Self-service "add a password" for an OAuth-only account ----------

def _create_oauth_only_user_and_get_headers(client, monkeypatch, email="oauthonly@example.com"):
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-setpw",
        "email": email,
        "name": "OAuth Only",
    })
    state_resp = client.get("/auth/oauth/google/login?org_name=SetPw+Org")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    resp = client.get(f"/auth/oauth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    login_code = _extract_query_param(resp.headers["location"], "oauth_code")
    exchange_resp = client.post("/auth/oauth/exchange", json={"code": login_code})
    body = exchange_resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def test_new_oauth_user_has_usable_password_false(client, monkeypatch):
    headers, user = _create_oauth_only_user_and_get_headers(client, monkeypatch)
    assert user["has_usable_password"] is False

    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["has_usable_password"] is False


def test_ordinary_signup_has_usable_password_true(client, signed_up_admin):
    assert signed_up_admin["user"]["has_usable_password"] is True


def test_set_password_succeeds_for_oauth_only_account(client, monkeypatch):
    headers, _ = _create_oauth_only_user_and_get_headers(client, monkeypatch, email="setpw1@example.com")

    resp = client.post("/auth/me/set-password", json={"new_password": "a-real-password-now"}, headers=headers)
    assert resp.status_code == 200, resp.text

    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.json()["has_usable_password"] is True


def test_set_password_then_actually_works_for_login(client, monkeypatch):
    headers, user = _create_oauth_only_user_and_get_headers(client, monkeypatch, email="setpw2@example.com")

    resp = client.post("/auth/me/set-password", json={"new_password": "a-real-password-now"}, headers=headers)
    assert resp.status_code == 200, resp.text

    login_resp = client.post("/auth/login", json={"username": user["username"], "password": "a-real-password-now"})
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["user"]["id"] == user["id"]


def test_set_password_rejects_short_password(client, monkeypatch):
    headers, _ = _create_oauth_only_user_and_get_headers(client, monkeypatch, email="setpw3@example.com")
    resp = client.post("/auth/me/set-password", json={"new_password": "abc"}, headers=headers)
    assert resp.status_code == 400


def test_set_password_rejects_when_account_already_has_password(client, auth_headers):
    # signed_up_admin (behind auth_headers) is an ordinary password
    # account — set-password must refuse and point at change-password.
    resp = client.post("/auth/me/set-password", json={"new_password": "another-real-password"}, headers=auth_headers)
    assert resp.status_code == 400
    assert "change password" in resp.json()["detail"].lower()


def test_set_password_requires_auth(client):
    resp = client.post("/auth/me/set-password", json={"new_password": "whatever-password"})
    assert resp.status_code in (401, 403)


def test_oauth_callback_rejects_tampered_state(client, monkeypatch):
    _configure_fake_google(monkeypatch, profile={
        "subject_id": "google-sub-006",
        "email": "tampered@example.com",
        "name": "Tampered",
    })
    resp = client.get("/auth/oauth/google/callback?code=fake-code&state=not-a-valid-jwt", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


def test_oauth_callback_surfaces_google_exchange_failure(client, monkeypatch):
    monkeypatch.setattr(oauth_svc, "GOOGLE_OAUTH_CONFIGURED", True)
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr(oauth_svc, "GOOGLE_CLIENT_SECRET", "fake-client-secret")

    def _raise(code):
        raise oauth_svc.GoogleOAuthError("Google rejected the authorization code (it may be expired or already used).")

    monkeypatch.setattr(auth_routes.oauth_svc, "exchange_code_for_profile", _raise)

    state_resp = client.get("/auth/oauth/google/login?org_name=Whatever")
    state = _extract_query_param(state_resp.json()["authorization_url"], "state")
    resp = client.get(f"/auth/oauth/google/callback?code=bad-code&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]
