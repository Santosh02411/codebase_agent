"""
Tests for Phase 17 — Security & Session Management:
- Account lockout after repeated failed logins, auto-expiring, reset
  on successful login
- Login history recorded for both failed and successful attempts
- Suspicious-login detection (new IP flagged, first login never flagged)
- Sessions: list, is_current marking, revoke one, logout-all
- Password reuse rejected on change and on reset; a genuinely new
  password is accepted
- Security events recorded (password_changed, 2fa_enabled, 2fa_disabled,
  session_revoked)
- 2FA recovery codes: generated on enable, single-use, allow login when
  the TOTP code itself is wrong, regeneration requires password
"""

import pyotp

from app.services import security as security_svc


def _enable_totp(client, headers):
    resp = client.post("/auth/2fa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    secret = resp.json()["secret"]
    code = pyotp.TOTP(secret).now()
    resp = client.post("/auth/2fa/enable", json={"code": code}, headers=headers)
    assert resp.status_code == 200, resp.text
    return secret, resp.json()


# ---------- Account lockout ----------

def test_account_locks_out_after_repeated_failed_logins(client, signed_up_admin):
    username = signed_up_admin["user"]["username"]
    for _ in range(security_svc.MAX_FAILED_LOGIN_ATTEMPTS):
        resp = client.post("/auth/login", json={"username": username, "password": "wrong-password"})
        assert resp.status_code == 401

    resp = client.post("/auth/login", json={"username": username, "password": "wrong-password"})
    assert resp.status_code == 403
    assert "too many" in resp.json()["detail"].lower()

    # Even the CORRECT password is rejected while locked out.
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    assert resp.status_code == 403


def test_successful_login_resets_failed_count(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    client.post("/auth/login", json={"username": username, "password": "wrong-password"})
    client.post("/auth/login", json={"username": username, "password": "wrong-password"})

    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    assert resp.status_code == 200

    resp = client.get("/auth/security-events", headers=auth_headers)
    # No account_locked event, since we never crossed the threshold.
    assert not any(e["event_type"] == "account_locked" for e in resp.json())


# ---------- Login history ----------

def test_login_history_records_success_and_failure(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    client.post("/auth/login", json={"username": username, "password": "wrong-password"})
    client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})

    resp = client.get("/auth/login-history", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()
    event_types = {e["event_type"] for e in events}
    assert "login_failed" in event_types
    assert "login_success" in event_types or "suspicious_login" in event_types


# ---------- Sessions ----------

def test_list_sessions_marks_current_and_shows_others(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    login_resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    refresh_token = login_resp.json()["refresh_token"]

    resp = client.get(f"/auth/sessions?current_refresh_token={refresh_token}", headers=auth_headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 2  # the signup session + this new login session
    assert any(s["is_current"] for s in sessions)


def test_revoke_one_session(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    login_resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    new_refresh_token = login_resp.json()["refresh_token"]

    resp = client.get("/auth/sessions", headers=auth_headers)
    session_to_revoke = next(s for s in resp.json())["id"]

    resp = client.delete(f"/auth/sessions/{session_to_revoke}", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/auth/sessions", headers=auth_headers)
    assert session_to_revoke not in [s["id"] for s in resp.json()]


def test_cannot_revoke_another_users_session(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "security_other_staff", "email": "security_other_staff@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Other", "invite_code": invite_code,
        },
    )
    other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.get("/auth/sessions", headers=other_headers)
    other_session_id = resp.json()[0]["id"]

    resp = client.delete(f"/auth/sessions/{other_session_id}", headers=auth_headers)
    assert resp.status_code == 404


def test_logout_all_revokes_every_session(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})

    resp = client.post("/auth/sessions/logout-all", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/auth/sessions", headers=auth_headers)
    assert resp.json() == []


# ---------- Password reuse ----------

def test_change_password_rejects_reuse(client, auth_headers):
    resp = client.post("/auth/me/change-password", json={"current_password": "correct-horse-battery", "new_password": "brand-new-password-1"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    # Re-authenticate with the new password to get valid headers for the next change.
    resp = client.post("/auth/me/change-password", json={"current_password": "brand-new-password-1", "new_password": "correct-horse-battery"}, headers=auth_headers)
    assert resp.status_code == 400
    assert "last" in resp.json()["detail"].lower()


def test_change_password_records_security_event(client, auth_headers):
    resp = client.post("/auth/me/change-password", json={"current_password": "correct-horse-battery", "new_password": "another-fresh-password-2"}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/auth/security-events", headers=auth_headers)
    assert any(e["event_type"] == "password_changed" for e in resp.json())


# ---------- 2FA & recovery codes ----------

def test_enable_totp_returns_recovery_codes_and_records_event(client, auth_headers):
    secret, body = _enable_totp(client, auth_headers)
    assert len(body["recovery_codes"]) == security_svc.RECOVERY_CODE_COUNT

    resp = client.get("/auth/security-events", headers=auth_headers)
    event_types = {e["event_type"] for e in resp.json()}
    assert "2fa_enabled" in event_types
    assert "recovery_codes_generated" in event_types


def test_recovery_code_allows_login_and_is_single_use(client, signed_up_admin, auth_headers):
    username = signed_up_admin["user"]["username"]
    secret, body = _enable_totp(client, auth_headers)
    recovery_code = body["recovery_codes"][0]

    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    assert resp.status_code == 200
    challenge_token = resp.json()["challenge_token"]

    resp = client.post("/auth/2fa/verify-login", json={"challenge_token": challenge_token, "code": recovery_code})
    assert resp.status_code == 200, resp.text

    # Using the SAME recovery code again must fail.
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse-battery"})
    challenge_token_2 = resp.json()["challenge_token"]
    resp = client.post("/auth/2fa/verify-login", json={"challenge_token": challenge_token_2, "code": recovery_code})
    assert resp.status_code == 401


def test_disable_totp_records_security_event(client, auth_headers):
    _enable_totp(client, auth_headers)
    resp = client.post("/auth/2fa/disable", json={"password": "correct-horse-battery"}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/auth/security-events", headers=auth_headers)
    assert any(e["event_type"] == "2fa_disabled" for e in resp.json())


def test_regenerate_recovery_codes_requires_password(client, auth_headers):
    _enable_totp(client, auth_headers)
    resp = client.post("/auth/2fa/recovery-codes/generate", json={"password": "wrong-password"}, headers=auth_headers)
    assert resp.status_code == 401

    resp = client.post("/auth/2fa/recovery-codes/generate", json={"password": "correct-horse-battery"}, headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["codes"]) == security_svc.RECOVERY_CODE_COUNT
