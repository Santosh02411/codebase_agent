"""
Tests for staff self-service account settings — GET/PATCH /auth/me and
POST /auth/me/change-password. Mirrors the customer equivalents
(routes/customer_auth.py's /customer/me endpoints), covering the same
edge cases: current-password verification, minimum length, email
collision, and that logging in still works with a new password
afterward.
"""


def test_get_my_profile(client, auth_headers, signed_up_admin):
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == signed_up_admin["user"]["id"]
    assert body["username"] == signed_up_admin["user"]["username"]


def test_update_my_display_name_and_email(client, auth_headers):
    resp = client.patch(
        "/auth/me",
        json={"display_name": "Updated Name", "email": "updated_email@example.com"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Updated Name"
    assert body["email"] == "updated_email@example.com"

    # Persisted — a fresh GET reflects it too.
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.json()["display_name"] == "Updated Name"


def test_update_my_profile_partial_update_leaves_other_field_untouched(client, auth_headers, signed_up_admin):
    original_email = signed_up_admin["user"]["email"]

    resp = client.patch("/auth/me", json={"display_name": "Only Name Changed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Only Name Changed"
    assert resp.json()["email"] == original_email


def test_update_my_profile_rejects_empty_display_name(client, auth_headers):
    resp = client.patch("/auth/me", json={"display_name": "   "}, headers=auth_headers)
    assert resp.status_code == 400


def test_update_my_profile_rejects_email_already_used_by_another_account(
    client, auth_headers, signed_up_admin
):
    invite_code = signed_up_admin["org_invite_code"]
    other_signup = client.post(
        "/auth/signup",
        json={
            "username": "other_staffer",
            "email": "other_staffer@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": "Other Staffer",
            "invite_code": invite_code,
        },
    )
    assert other_signup.status_code == 200, other_signup.text

    resp = client.patch("/auth/me", json={"email": "other_staffer@example.com"}, headers=auth_headers)
    assert resp.status_code == 400


def test_change_my_password_full_cycle(client, auth_headers, signed_up_admin, admin_signup_payload):
    resp = client.post(
        "/auth/me/change-password",
        json={"current_password": admin_signup_payload["password"], "new_password": "a-brand-new-password"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # Old password no longer works.
    resp = client.post(
        "/auth/login",
        json={"username": admin_signup_payload["username"], "password": admin_signup_payload["password"]},
    )
    assert resp.status_code == 401

    # New password does.
    resp = client.post(
        "/auth/login",
        json={"username": admin_signup_payload["username"], "password": "a-brand-new-password"},
    )
    assert resp.status_code == 200, resp.text


def test_change_my_password_rejects_wrong_current_password(client, auth_headers):
    resp = client.post(
        "/auth/me/change-password",
        json={"current_password": "definitely-wrong", "new_password": "a-brand-new-password"},
        headers=auth_headers,
    )
    assert resp.status_code == 401


def test_change_my_password_rejects_too_short(client, auth_headers, admin_signup_payload):
    resp = client.post(
        "/auth/me/change-password",
        json={"current_password": admin_signup_payload["password"], "new_password": "abc"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_account_settings_require_auth(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401

    resp = client.patch("/auth/me", json={"display_name": "x"})
    assert resp.status_code == 401

    resp = client.post("/auth/me/change-password", json={"current_password": "x", "new_password": "y" * 8})
    assert resp.status_code == 401
