"""
Tests for refresh-token rotation — routes/auth.py's /refresh and
/logout, and their customer equivalents. Covers: signup/login issue a
refresh token, /refresh rotates it (old one becomes unusable), reuse of
an already-rotated token is treated as theft and revokes the whole
chain, an expired token is rejected, and /logout revokes server-side
(not just a client-side no-op).
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.refresh_token import RefreshTokenDB
from app.models.customer_refresh_token import CustomerRefreshTokenDB


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def test_signup_and_login_issue_a_refresh_token(client, admin_signup_payload):
    resp = client.post("/auth/signup", json=admin_signup_payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["refresh_token"]

    resp = client.post(
        "/auth/login",
        json={"username": admin_signup_payload["username"], "password": admin_signup_payload["password"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["refresh_token"]


def test_refresh_rotates_the_token(client, signed_up_admin):
    signup_resp = client.post(
        "/auth/login",
        json={
            "username": signed_up_admin["payload"]["username"],
            "password": signed_up_admin["payload"]["password"],
        },
    )
    refresh_token = signup_resp.json()["refresh_token"]

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != refresh_token

    # The new access token actually works against a protected endpoint.
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert resp.status_code == 200


def test_reusing_a_rotated_refresh_token_is_rejected_and_revokes_the_chain(client, db_engine, signed_up_admin):
    login_resp = client.post(
        "/auth/login",
        json={
            "username": signed_up_admin["payload"]["username"],
            "password": signed_up_admin["payload"]["password"],
        },
    )
    original_token = login_resp.json()["refresh_token"]

    first_refresh = client.post("/auth/refresh", json={"refresh_token": original_token})
    assert first_refresh.status_code == 200
    rotated_token = first_refresh.json()["refresh_token"]

    # Reusing the ORIGINAL (already-rotated) token is a theft signal.
    reuse_resp = client.post("/auth/refresh", json={"refresh_token": original_token})
    assert reuse_resp.status_code == 401

    # The entire chain — including the token issued by the legitimate
    # first refresh — is now revoked too, since at this point neither
    # copy can be trusted.
    second_refresh = client.post("/auth/refresh", json={"refresh_token": rotated_token})
    assert second_refresh.status_code == 401


def test_expired_refresh_token_is_rejected(client, db_engine, signed_up_admin):
    login_resp = client.post(
        "/auth/login",
        json={
            "username": signed_up_admin["payload"]["username"],
            "password": signed_up_admin["payload"]["password"],
        },
    )
    refresh_token = login_resp.json()["refresh_token"]

    from app.services.auth import hash_refresh_token
    token_hash = hash_refresh_token(refresh_token)

    db = _session_for(db_engine)
    try:
        row = db.query(RefreshTokenDB).filter(RefreshTokenDB.token_hash == token_hash).first()
        row.expires_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


def test_logout_revokes_the_refresh_token_server_side(client, signed_up_admin):
    login_resp = client.post(
        "/auth/login",
        json={
            "username": signed_up_admin["payload"]["username"],
            "password": signed_up_admin["payload"]["password"],
        },
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert resp.status_code == 200

    # The revoked token can no longer be used to refresh.
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


def test_customer_refresh_rotates_and_reuse_is_rejected(client, signed_up_customer):
    login_resp = client.post(
        "/customer/login",
        json={"email": signed_up_customer["payload"]["email"], "password": signed_up_customer["payload"]["password"]},
    )
    original_token = login_resp.json()["refresh_token"]

    resp = client.post("/customer/refresh-token", json={"refresh_token": original_token})
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["refresh_token"]
    assert new_token != original_token

    reuse_resp = client.post("/customer/refresh-token", json={"refresh_token": original_token})
    assert reuse_resp.status_code == 401


def test_customer_logout_revokes_server_side(client, signed_up_customer):
    login_resp = client.post(
        "/customer/login",
        json={"email": signed_up_customer["payload"]["email"], "password": signed_up_customer["payload"]["password"]},
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = client.post("/customer/logout", json={"refresh_token": refresh_token})
    assert resp.status_code == 200

    resp = client.post("/customer/refresh-token", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


def test_refresh_rejects_garbage_token(client):
    resp = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token-at-all"})
    assert resp.status_code == 401
