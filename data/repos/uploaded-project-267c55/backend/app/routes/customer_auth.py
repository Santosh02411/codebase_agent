"""
Customer authentication — separate signup/login from the staff
(agent/dispatcher/admin) system in routes/auth.py. Reuses the same
password hashing and JWT helpers from services/auth.py, but issues
tokens with a distinct payload shape ({"customer_id": ...} instead of
{"sub": ..., "role": ...}) so a customer token and a staff token can
never be confused with each other, even accidentally.
"""

import os
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import CustomerDB, CustomerSignup, CustomerLogin, CustomerTokenResponse, CustomerOut, CustomerProfileUpdate, CustomerPasswordChange, CustomerSetPassword
from app.models.customer_password_reset import CustomerPasswordResetTokenDB, CustomerForgotPasswordRequest, CustomerResetPasswordRequest
from app.models.customer_email_verification import CustomerEmailVerificationTokenDB, CustomerVerifyEmailRequest
from app.models.customer_refresh_token import CustomerRefreshTokenDB, CustomerRefreshTokenRequest, CustomerRefreshTokenResponse
from app.models.delivery import DeliveryRecordDB
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
    create_customer_oauth_state_token,
    create_customer_oauth_login_code,
)
from app.services.email import send_customer_password_reset_email, send_customer_verification_email
from app.services.captcha import verify_captcha, IS_CONFIGURED as CAPTCHA_CONFIGURED
from app.services.rate_limiter import limiter
from app.services import oauth as oauth_svc
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter(prefix="/customer", tags=["customer-auth"])

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _issue_customer_refresh_token(db: Session, customer_id: str) -> str:
    raw_token = generate_refresh_token()
    db.add(CustomerRefreshTokenDB(customer_id=customer_id, token_hash=hash_refresh_token(raw_token)))
    db.commit()
    return raw_token


def _issue_and_send_customer_verification_email(db: Session, customer: CustomerDB) -> None:
    verification = CustomerEmailVerificationTokenDB(customer_id=customer.id)
    db.add(verification)
    db.commit()
    db.refresh(verification)
    verify_link = f"{FRONTEND_URL}/?verify_customer_email_token={verification.token}"
    send_customer_verification_email(customer.email, verify_link)


@router.post("/signup", response_model=CustomerTokenResponse)
@limiter.limit("5/minute")
def customer_signup(request: Request, payload: CustomerSignup, db: Session = Depends(get_db)):
    if CAPTCHA_CONFIGURED and not verify_captcha(payload.captcha_token):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    existing = db.query(CustomerDB).filter(CustomerDB.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with that email already exists. Try logging in.")

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    customer = CustomerDB(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    # Retroactively link any existing deliveries that used this email as
    # customer_email but were created before this account existed — so
    # signing up doesn't leave past orders stranded outside the dashboard.
    db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.customer_email == payload.email,
        DeliveryRecordDB.customer_id.is_(None),
    ).update({"customer_id": customer.id})
    db.commit()

    _issue_and_send_customer_verification_email(db, customer)

    token = create_access_token({"customer_id": customer.id})
    refresh_token = _issue_customer_refresh_token(db, customer.id)
    return {"access_token": token, "refresh_token": refresh_token, "customer": customer}


@router.post("/login", response_model=CustomerTokenResponse)
@limiter.limit("10/minute")
def customer_login(request: Request, payload: CustomerLogin, db: Session = Depends(get_db)):
    customer = db.query(CustomerDB).filter(CustomerDB.email == payload.email).first()
    if not customer or not verify_password(payload.password, customer.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = create_access_token({"customer_id": customer.id})
    refresh_token = _issue_customer_refresh_token(db, customer.id)
    return {"access_token": token, "refresh_token": refresh_token, "customer": customer}


class CustomerOAuthAuthorizationUrlOut(BaseModel):
    authorization_url: str


class CustomerOAuthExchangeRequest(BaseModel):
    code: str


@router.get("/oauth/google/login", response_model=CustomerOAuthAuthorizationUrlOut)
@limiter.limit("10/minute")
def start_customer_google_oauth_login(request: Request):
    """
    Customer-side equivalent of routes/auth.py's staff
    /oauth/google/login — see that route's docstring for the overall
    flow. Notably simpler here: no org_name/invite_code/role query
    params at all, since a customer account carries no org context
    (see CustomerDB's own comment on why).
    """
    if not oauth_svc.GOOGLE_OAUTH_CONFIGURED:
        raise HTTPException(
            status_code=400,
            detail="Google sign-in isn't configured for this deployment. Set GOOGLE_CLIENT_ID and "
                   "GOOGLE_CLIENT_SECRET to enable it.",
        )
    state = create_customer_oauth_state_token()
    return {"authorization_url": oauth_svc.build_authorization_url(state, redirect_uri=oauth_svc.GOOGLE_CUSTOMER_REDIRECT_URI)}


@router.get("/oauth/google/callback")
def customer_google_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """
    Customer-side equivalent of routes/auth.py's staff
    /oauth/google/callback. Same "Google redirects the browser here
    directly, so every path ends in a redirect back to the frontend"
    shape — see that route's docstring for why. Also links to an
    existing password-based customer account by verified email, same
    trust bar as the staff flow, and retroactively links any past
    deliveries placed under this email before an account existed —
    mirroring what /customer/signup already does for a password
    signup, so an OAuth signup doesn't behave differently there.
    """
    def _redirect_with_error(message: str) -> RedirectResponse:
        from urllib.parse import quote
        return RedirectResponse(f"{FRONTEND_URL}/?customer_oauth_error={quote(message)}")

    if error:
        return _redirect_with_error("Google sign-in was cancelled or denied.")
    if not oauth_svc.GOOGLE_OAUTH_CONFIGURED:
        return _redirect_with_error("Google sign-in isn't configured for this deployment.")
    if not code or not state:
        return _redirect_with_error("Missing information from Google's redirect. Please try again.")

    decoded_state = decode_access_token(state)
    if not decoded_state or "customer_oauth_provider" not in decoded_state:
        return _redirect_with_error("This sign-in attempt has expired. Please try again.")

    try:
        profile = oauth_svc.exchange_code_for_profile(code, redirect_uri=oauth_svc.GOOGLE_CUSTOMER_REDIRECT_URI)
    except oauth_svc.GoogleOAuthError as err:
        return _redirect_with_error(str(err))

    customer = db.query(CustomerDB).filter(
        CustomerDB.oauth_provider == "google",
        CustomerDB.oauth_subject_id == profile["subject_id"],
    ).first()

    if not customer:
        customer = db.query(CustomerDB).filter(CustomerDB.email == profile["email"]).first()
        if customer:
            customer.oauth_provider = "google"
            customer.oauth_subject_id = profile["subject_id"]
            customer.email_verified = True
            db.commit()
            db.refresh(customer)

    if not customer:
        customer = CustomerDB(
            email=profile["email"],
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            has_usable_password=False,
            name=profile["name"],
            email_verified=True,
            oauth_provider="google",
            oauth_subject_id=profile["subject_id"],
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

        # Same retroactive-linking behavior as POST /customer/signup —
        # see that route's own comment.
        db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.customer_email == profile["email"],
            DeliveryRecordDB.customer_id.is_(None),
        ).update({"customer_id": customer.id})
        db.commit()

    login_code = create_customer_oauth_login_code(customer.id)
    from urllib.parse import quote
    return RedirectResponse(f"{FRONTEND_URL}/?customer_oauth_code={quote(login_code)}")


@router.post("/oauth/exchange", response_model=CustomerTokenResponse)
@limiter.limit("10/minute")
def exchange_customer_oauth_login_code(request: Request, payload: CustomerOAuthExchangeRequest, db: Session = Depends(get_db)):
    """
    Customer-side equivalent of routes/auth.py's staff
    /oauth/exchange — trades the one-time code from the callback
    redirect for a real access/refresh token pair.
    """
    decoded = decode_access_token(payload.code)
    if not decoded or "customer_oauth_login_customer_id" not in decoded:
        raise HTTPException(status_code=401, detail="This sign-in link has expired. Please sign in again.")

    customer = db.query(CustomerDB).filter(CustomerDB.id == decoded["customer_oauth_login_customer_id"]).first()
    if not customer:
        raise HTTPException(status_code=401, detail="This sign-in link has expired. Please sign in again.")

    token = create_access_token({"customer_id": customer.id})
    refresh_token = _issue_customer_refresh_token(db, customer.id)
    return {"access_token": token, "refresh_token": refresh_token, "customer": customer}


@router.post("/forgot-password")
@limiter.limit("3/minute")
def customer_forgot_password(request: Request, payload: CustomerForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Requests a password reset email for a customer account. Mirrors
    routes/auth.py's staff forgot-password endpoint exactly on purpose,
    including the same information-leak precaution: this ALWAYS returns
    the same generic message whether or not the email belongs to a real
    account, so this endpoint can't be used to probe which emails are
    registered customers. Same 3/minute rate limit for the same reason
    (stop someone from spamming reset emails at a real customer's inbox).
    """
    GENERIC_RESPONSE = {
        "message": "If that email is registered, a password reset link has been sent."
    }

    if CAPTCHA_CONFIGURED and not verify_captcha(payload.captcha_token):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    customer = db.query(CustomerDB).filter(CustomerDB.email == payload.email).first()
    if not customer:
        return GENERIC_RESPONSE

    reset_token = CustomerPasswordResetTokenDB(customer_id=customer.id)
    db.add(reset_token)
    db.commit()
    db.refresh(reset_token)

    reset_link = f"{FRONTEND_URL}/?customer_reset_token={reset_token.token}"
    send_customer_password_reset_email(customer.email, reset_link)

    return GENERIC_RESPONSE


@router.post("/reset-password")
@limiter.limit("5/minute")
def customer_reset_password(request: Request, payload: CustomerResetPasswordRequest, db: Session = Depends(get_db)):
    """Completes a customer password reset, given a valid, unused, unexpired token."""
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    reset_token = db.query(CustomerPasswordResetTokenDB).filter(
        CustomerPasswordResetTokenDB.token == payload.token
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="This reset link is invalid.")
    if reset_token.used:
        raise HTTPException(status_code=400, detail="This reset link has already been used.")
    if reset_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link has expired. Request a new one.")

    customer = db.query(CustomerDB).filter(CustomerDB.id == reset_token.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="This reset link is invalid.")

    customer.hashed_password = hash_password(payload.new_password)
    reset_token.used = True
    db.commit()

    return {"message": "Password reset successfully. You can now log in with your new password."}


def get_current_customer(
    authorization: str = Header(None), db: Session = Depends(get_db)
) -> CustomerDB:
    """FastAPI dependency mirroring get_current_user, but for customer tokens."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "customer_id" not in payload:
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    customer = db.query(CustomerDB).filter(CustomerDB.id == payload["customer_id"]).first()
    if not customer:
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    return customer


@router.post("/verify-email")
def verify_customer_email(payload: CustomerVerifyEmailRequest, db: Session = Depends(get_db)):
    """Mirrors routes/auth.py's /auth/verify-email — same non-blocking design, see that docstring."""
    verification = db.query(CustomerEmailVerificationTokenDB).filter(
        CustomerEmailVerificationTokenDB.token == payload.token
    ).first()

    if not verification:
        raise HTTPException(status_code=400, detail="This verification link is invalid.")
    if verification.used:
        raise HTTPException(status_code=400, detail="This verification link has already been used.")
    if verification.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This verification link has expired. Request a new one.")

    customer = db.query(CustomerDB).filter(CustomerDB.id == verification.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="This verification link is invalid.")

    customer.email_verified = True
    verification.used = True
    db.commit()

    return {"message": "Email verified."}


@router.post("/resend-verification")
@limiter.limit("3/minute")
def resend_customer_verification(request: Request, current_customer: CustomerDB = Depends(get_current_customer), db: Session = Depends(get_db)):
    if current_customer.email_verified:
        return {"message": "This account's email is already verified."}
    _issue_and_send_customer_verification_email(db, current_customer)
    return {"message": "Verification email sent."}


@router.post("/refresh-token", response_model=CustomerRefreshTokenResponse)
@limiter.limit("30/minute")
def refresh_customer_access_token(request: Request, payload: CustomerRefreshTokenRequest, db: Session = Depends(get_db)):
    """Mirrors routes/auth.py's /auth/refresh — same rotation + theft-detection design, see models/refresh_token.py."""
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(CustomerRefreshTokenDB).filter(CustomerRefreshTokenDB.token_hash == token_hash).first()

    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token. Log in again.")

    if stored.used or stored.revoked_at is not None:
        db.query(CustomerRefreshTokenDB).filter(
            CustomerRefreshTokenDB.customer_id == stored.customer_id,
            CustomerRefreshTokenDB.revoked_at.is_(None),
        ).update({"revoked_at": datetime.utcnow()})
        db.commit()
        raise HTTPException(status_code=401, detail="This session was revoked. Log in again.")

    if stored.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Your session has expired. Log in again.")

    customer = db.query(CustomerDB).filter(CustomerDB.id == stored.customer_id).first()
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid refresh token. Log in again.")

    new_raw_token = generate_refresh_token()
    new_row = CustomerRefreshTokenDB(customer_id=customer.id, token_hash=hash_refresh_token(new_raw_token))
    db.add(new_row)
    db.flush()

    stored.used = True
    stored.replaced_by_id = new_row.id
    db.commit()

    new_access_token = create_access_token({"customer_id": customer.id})
    return {"access_token": new_access_token, "refresh_token": new_raw_token}


@router.post("/logout")
def customer_logout(payload: CustomerRefreshTokenRequest, db: Session = Depends(get_db)):
    """Mirrors routes/auth.py's /auth/logout — see that docstring for why this isn't access-token-gated."""
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(CustomerRefreshTokenDB).filter(CustomerRefreshTokenDB.token_hash == token_hash).first()
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.utcnow()
        db.commit()
    return {"message": "Logged out."}


@router.get("/me", response_model=CustomerOut)
def get_my_profile(current_customer: CustomerDB = Depends(get_current_customer)):
    return current_customer


@router.patch("/me", response_model=CustomerOut)
def update_my_profile(
    payload: CustomerProfileUpdate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name can't be empty.")
        current_customer.name = name

    if payload.email is not None:
        email = payload.email.strip()
        if not email:
            raise HTTPException(status_code=400, detail="Email can't be empty.")
        if email != current_customer.email:
            existing = db.query(CustomerDB).filter(CustomerDB.email == email).first()
            if existing:
                raise HTTPException(status_code=400, detail="Another account already uses that email.")
            current_customer.email = email

    db.commit()
    db.refresh(current_customer)
    return current_customer


@router.post("/me/change-password")
def change_my_password(
    payload: CustomerPasswordChange,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    if not verify_password(payload.current_password, current_customer.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")

    current_customer.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed."}


@router.post("/me/set-password")
def set_my_customer_password(
    payload: CustomerSetPassword,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Customer-side equivalent of routes/auth.py's staff
    /me/set-password — see UserSetPassword's docstring for the
    reasoning in full; identical logic, customer side."""
    if current_customer.has_usable_password:
        raise HTTPException(
            status_code=400,
            detail="This account already has a password. Use \"Change password\" instead.",
        )
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    current_customer.hashed_password = hash_password(payload.new_password)
    current_customer.has_usable_password = True
    db.commit()
    return {"message": "Password set. You can now log in with it, in addition to Google Sign-In."}
