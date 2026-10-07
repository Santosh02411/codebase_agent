"""
Tests for email verification — routes/auth.py's /verify-email and
/resend-verification (staff), and their customer equivalents in
routes/customer_auth.py. Covers: a fresh signup is unverified, a valid
token verifies it, invalid/expired/reused tokens are rejected, resend
works (and short-circuits if already verified), and — the core design
choice — verification does NOT block login.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.email_verification import EmailVerificationTokenDB
from app.models.customer_email_verification import CustomerEmailVerificationTokenDB


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def test_staff_signup_is_unverified_and_login_still_works(client, admin_signup_payload):
    resp = client.post("/auth/signup", json=admin_signup_payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email_verified"] is False

    # Verification does not block login.
    resp = client.post(
        "/auth/login",
        json={"username": admin_signup_payload["username"], "password": admin_signup_payload["password"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email_verified"] is False


def test_staff_verify_email_full_cycle(client, db_engine, signed_up_admin, auth_headers):
    user_id = signed_up_admin["user"]["id"]

    db = _session_for(db_engine)
    try:
        token_row = (
            db.query(EmailVerificationTokenDB)
            .filter(EmailVerificationTokenDB.user_id == user_id)
            .order_by(EmailVerificationTokenDB.created_at.desc())
            .first()
        )
        assert token_row is not None
        token = token_row.token
    finally:
        db.close()

    resp = client.post("/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.json()["email_verified"] is True

    # Reusing the same token fails.
    resp = client.post("/auth/verify-email", json={"token": token})
    assert resp.status_code == 400


def test_staff_verify_email_rejects_invalid_and_expired_tokens(client, db_engine, signed_up_admin):
    resp = client.post("/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400

    db = _session_for(db_engine)
    try:
        expired = EmailVerificationTokenDB(
            user_id=signed_up_admin["user"]["id"],
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(expired)
        db.commit()
        db.refresh(expired)
        expired_token = expired.token
    finally:
        db.close()

    resp = client.post("/auth/verify-email", json={"token": expired_token})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_staff_resend_verification(client, auth_headers, db_engine, signed_up_admin):
    resp = client.post("/auth/resend-verification", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert "sent" in resp.json()["message"].lower()

    # Two tokens now exist for this user (signup's + the resend's).
    db = _session_for(db_engine)
    try:
        count = db.query(EmailVerificationTokenDB).filter(
            EmailVerificationTokenDB.user_id == signed_up_admin["user"]["id"]
        ).count()
        assert count == 2
    finally:
        db.close()


def test_staff_resend_verification_short_circuits_if_already_verified(client, db_engine, signed_up_admin, auth_headers):
    db = _session_for(db_engine)
    try:
        token_row = db.query(EmailVerificationTokenDB).filter(
            EmailVerificationTokenDB.user_id == signed_up_admin["user"]["id"]
        ).first()
        token = token_row.token
    finally:
        db.close()

    client.post("/auth/verify-email", json={"token": token})

    resp = client.post("/auth/resend-verification", headers=auth_headers)
    assert resp.status_code == 200
    assert "already verified" in resp.json()["message"].lower()


def test_resend_verification_requires_auth(client):
    resp = client.post("/auth/resend-verification")
    assert resp.status_code == 401


def test_customer_signup_is_unverified_and_login_still_works(client, customer_signup_payload):
    resp = client.post("/customer/signup", json=customer_signup_payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["customer"]["email_verified"] is False

    resp = client.post(
        "/customer/login",
        json={"email": customer_signup_payload["email"], "password": customer_signup_payload["password"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["customer"]["email_verified"] is False


def test_customer_verify_email_full_cycle(client, db_engine, signed_up_customer, customer_auth_headers):
    customer_id = signed_up_customer["customer"]["id"]

    db = _session_for(db_engine)
    try:
        token_row = (
            db.query(CustomerEmailVerificationTokenDB)
            .filter(CustomerEmailVerificationTokenDB.customer_id == customer_id)
            .first()
        )
        token = token_row.token
    finally:
        db.close()

    resp = client.post("/customer/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    resp = client.get("/customer/me", headers=customer_auth_headers)
    assert resp.json()["email_verified"] is True


def test_customer_resend_verification(client, customer_auth_headers):
    resp = client.post("/customer/resend-verification", headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    assert "sent" in resp.json()["message"].lower()
