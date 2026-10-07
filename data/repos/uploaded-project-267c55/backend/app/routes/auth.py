"""
Auth routes: signup and login. Also exposes `get_current_user`, a FastAPI
dependency that other routes use to identify who's making a request,
check their role, and check their organization — this is what makes both
role-based access AND multi-tenant isolation possible.
"""

import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import (
    UserDB,
    UserSignup,
    UserLogin,
    UserOut,
    UserProfileUpdate,
    UserPasswordChange,
    UserSetPassword,
    TokenResponse,
    LoginResult,
    TwoFactorSetupOut,
    TwoFactorCodeRequest,
    TwoFactorLoginVerify,
    TwoFactorDisableRequest,
    TwoFactorStatusOut,
    TwoFactorEmailCodeRequest,
)
from app.models.organization import OrganizationDB
from app.models.password_reset import PasswordResetTokenDB, ForgotPasswordRequest, ResetPasswordRequest
from app.models.email_otp import EmailOtpDB, EMAIL_OTP_EXPIRY_MINUTES, generate_numeric_code, mask_email
from app.models.email_verification import EmailVerificationTokenDB, VerifyEmailRequest, VERIFICATION_TOKEN_EXPIRY_HOURS
from app.models.refresh_token import RefreshTokenDB, RefreshTokenRequest, RefreshTokenResponse
from app.models.security import (
    LoginHistoryDB, SecurityEventDB, SessionOut, LoginHistoryOut, SecurityEventOut,
    RecoveryCodesGenerateRequest, RecoveryCodesOut,
)
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_two_factor_challenge_token,
    generate_refresh_token,
    hash_refresh_token,
    create_oauth_state_token,
    create_oauth_login_code,
)
from app.services.totp import generate_secret, get_provisioning_uri, verify_code
from app.services.rate_limiter import limiter
from app.services.email import send_password_reset_email, send_two_factor_code_email, send_verification_email
from app.services.email import send_org_welcome_email, send_staff_welcome_email
from app.services.captcha import verify_captcha, IS_CONFIGURED as CAPTCHA_CONFIGURED
from app.services import security as security_svc
from app.services.email import send_security_alert_email
from app.services import oauth as oauth_svc
from app.services import demo_seed as demo_seed_svc
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List
import os

router = APIRouter(prefix="/auth", tags=["auth"])

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _issue_refresh_token(db: Session, user_id: str, device_info: str = None, ip_address: str = None) -> str:
    """
    Creates a new refresh token row (hash stored, not the raw value) and
    returns the RAW token — the only place the raw value ever exists is
    this return value and whatever the caller does with it immediately
    (put it in a response body). It is never logged or stored anywhere
    in plaintext.
    """
    raw_token = generate_refresh_token()
    db.add(RefreshTokenDB(user_id=user_id, token_hash=hash_refresh_token(raw_token), device_info=device_info, ip_address=ip_address))
    db.commit()
    return raw_token


def _issue_and_send_verification_email(db: Session, user: UserDB) -> None:
    verification = EmailVerificationTokenDB(user_id=user.id)
    db.add(verification)
    db.commit()
    db.refresh(verification)
    verify_link = f"{FRONTEND_URL}/?verify_email_token={verification.token}"
    send_verification_email(user.email, verify_link)


def _send_welcome_email(user: UserDB, org: OrganizationDB, is_new_org: bool, invite_code: str | None) -> None:
    """
    Shared by POST /auth/signup and the Google OAuth signup path below
    — both create a user + org the same two ways (new org vs. joining
    one via invite code), so both send the matching welcome email.
    Wrapped in try/except (unlike _issue_and_send_verification_email
    above, which deliberately lets a failure propagate and fail
    signup): a welcome email is a nice-to-have, not core correctness,
    so the same "best-effort, log and move on" reasoning
    notify_customer_of_status_change() uses for status emails applies
    here too — nobody should be unable to create an account just
    because an SMTP server had a bad moment.
    """
    try:
        if is_new_org:
            send_org_welcome_email(user.email, user.display_name, org.name, invite_code)
        else:
            send_staff_welcome_email(user.email, user.display_name, org.name, user.role.value)
    except Exception as error:  # noqa: BLE001
        print(f"Welcome email failed for {user.email}: {error}")


def generate_invite_code() -> str:
    """8-character, easy-to-read invite code (uppercase letters + digits)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _issue_and_send_email_otp(db: Session, user: UserDB, purpose: str) -> str:
    """
    Generates a fresh 6-digit code, stores its hash (see
    models/email_otp.py for why hashed, not plaintext), emails the plain
    code to the user, and returns the masked email address for display.
    Shared by both the "confirm your inbox to enable email 2FA" flow and
    the "here's your login code" flow — same mechanics, different
    `purpose` label so the two can't be swapped for each other.
    """
    code = generate_numeric_code()
    otp = EmailOtpDB(user_id=user.id, code_hash=hash_password(code), purpose=purpose)
    db.add(otp)
    db.commit()

    send_two_factor_code_email(user.email, code, purpose)
    return mask_email(user.email)


def _verify_and_consume_email_otp(db: Session, user_id: str, purpose: str, code: str) -> bool:
    """
    Checks `code` against the most recent not-yet-used, not-yet-expired
    OTP of this purpose for this user, and marks it used on success —
    each code works exactly once, and only the most recently issued one
    is ever accepted (so requesting a resend invalidates checking an
    older email still sitting in the inbox, avoiding any ambiguity about
    which one is "the real code").
    """
    otp = (
        db.query(EmailOtpDB)
        .filter(EmailOtpDB.user_id == user_id, EmailOtpDB.purpose == purpose, EmailOtpDB.used == False)  # noqa: E712
        .order_by(EmailOtpDB.created_at.desc())
        .first()
    )
    if not otp or otp.expires_at < datetime.utcnow():
        return False
    if not verify_password(code, otp.code_hash):
        return False

    otp.used = True
    db.commit()
    return True


@router.post("/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
def signup(request: Request, payload: UserSignup, db: Session = Depends(get_db)):
    if CAPTCHA_CONFIGURED and not verify_captcha(payload.captcha_token):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    existing = db.query(UserDB).filter(UserDB.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="That username's already taken. Try another.")

    existing_email = db.query(UserDB).filter(UserDB.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="That email is already registered. Try logging in instead.")

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    if not payload.org_name and not payload.invite_code:
        raise HTTPException(
            status_code=400,
            detail="Provide either an organization name (to create one) or an invite code (to join one).",
        )
    if payload.org_name and payload.invite_code:
        raise HTTPException(
            status_code=400,
            detail="Provide only ONE of organization name or invite code, not both.",
        )

    new_org_invite_code = None

    if payload.org_name:
        # Creating a brand new organization — this user becomes its admin
        # automatically, regardless of which role they selected, since
        # someone has to be able to manage the org from the very start.
        org = OrganizationDB(name=payload.org_name.strip(), invite_code=generate_invite_code())
        db.add(org)
        db.commit()
        db.refresh(org)
        org_id = org.id
        effective_role = "admin"
        new_org_invite_code = org.invite_code
    else:
        # Joining an existing organization via invite code
        org = db.query(OrganizationDB).filter(OrganizationDB.invite_code == payload.invite_code).first()
        if not org:
            raise HTTPException(status_code=400, detail="That invite code doesn't match any organization.")
        if org.is_suspended:
            raise HTTPException(status_code=403, detail="This organization is currently suspended and isn't accepting new members.")

        # SECURITY: anyone joining via invite code must never be able to
        # self-select the "admin" role. An invite code is meant for
        # regular team members (agents/dispatchers) to join an existing
        # organization — without this check, anyone holding a valid
        # invite code could simply choose "admin" on this form and gain
        # full administrative control over someone else's organization
        # (deactivating users, resetting passwords, viewing everything).
        # Admin status is only ever granted automatically to whoever
        # creates the organization in the first place (the branch above).
        if payload.role.value == "admin":
            raise HTTPException(
                status_code=400,
                detail="You can't self-assign the admin role when joining an existing organization.",
            )

        org_id = org.id
        effective_role = payload.role.value

    user = UserDB(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=effective_role,
        display_name=payload.display_name,
        org_id=org_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _issue_and_send_verification_email(db, user)
    _send_welcome_email(user, org, is_new_org=bool(payload.org_name), invite_code=new_org_invite_code)

    token = create_access_token({"sub": user.id, "role": user.role.value, "org_id": user.org_id})
    refresh_token = _issue_refresh_token(db, user.id)
    return {"access_token": token, "refresh_token": refresh_token, "user": user, "org_invite_code": new_org_invite_code}


@router.post("/login", response_model=LoginResult)
@limiter.limit("10/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    ip_address = security_svc.client_ip(request)
    device_info = security_svc.parse_user_agent(request.headers.get("user-agent"))

    user = db.query(UserDB).filter(UserDB.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    if security_svc.is_locked_out(user):
        raise HTTPException(status_code=403, detail=f"Too many failed login attempts. Try again in a few minutes.")

    if not verify_password(payload.password, user.hashed_password):
        security_svc.register_failed_login(db, user)
        security_svc.record_login_history(db, user.id, user.org_id, "login_failed", ip_address, device_info)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated. Contact your admin.")

    # Password was correct — reset the failed-attempt counter regardless
    # of whether 2FA is still pending, since the PASSWORD factor (the
    # thing lockout actually protects) has now been proven.
    security_svc.register_successful_login(db, user)

    if user.totp_enabled:
        # Password alone isn't enough for this account — hand back a
        # short-lived challenge token instead of a real session, and let
        # the frontend prompt for the code next. For the "email" method
        # there's no code sitting in an app yet, so send one right now;
        # for "totp" the code already exists in the user's authenticator
        # app, nothing to send.
        challenge_token = create_two_factor_challenge_token(user.id)
        masked_email = None
        if user.two_factor_method == "email":
            masked_email = _issue_and_send_email_otp(db, user, purpose="login")
        return {
            "requires_2fa": True,
            "challenge_token": challenge_token,
            "two_factor_method": user.two_factor_method,
            "masked_email": masked_email,
        }

    suspicious = security_svc.is_suspicious_login(db, user.id, ip_address)
    security_svc.record_login_history(db, user.id, user.org_id, "suspicious_login" if suspicious else "login_success", ip_address, device_info)
    if suspicious:
        send_security_alert_email(user.email, "New login from an unrecognized location", ip_address=ip_address, device_info=device_info)

    token = create_access_token({"sub": user.id, "role": user.role.value, "org_id": user.org_id})
    refresh_token = _issue_refresh_token(db, user.id, device_info=device_info, ip_address=ip_address)
    return {"access_token": token, "refresh_token": refresh_token, "user": user, "org_invite_code": None}


class OAuthAuthorizationUrlOut(BaseModel):
    authorization_url: str


class OAuthExchangeRequest(BaseModel):
    code: str


@router.get("/oauth/google/login", response_model=OAuthAuthorizationUrlOut)
@limiter.limit("10/minute")
def start_google_oauth_login(
    request: Request,
    org_name: str | None = None,
    invite_code: str | None = None,
    role: str = "agent",
):
    """
    Step 1 of Google SSO: returns the URL the frontend should send the
    browser to (`window.location.href = authorization_url`). `org_name`
    and `invite_code` are the same "create a new org" vs "join an
    existing one via invite code" choice as POST /auth/signup —
    optional here because they're only actually needed if this Google
    account turns out to be brand new to this app (see the callback
    below); logging into an ALREADY-linked account needs no org
    context at all, same as an ordinary password login needing no org
    context either.
    """
    if not oauth_svc.GOOGLE_OAUTH_CONFIGURED:
        raise HTTPException(
            status_code=400,
            detail="Google sign-in isn't configured for this deployment. Set GOOGLE_CLIENT_ID and "
                   "GOOGLE_CLIENT_SECRET to enable it.",
        )
    if role not in ("agent", "dispatcher", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role.")
    state = create_oauth_state_token("google", org_name, invite_code, role)
    return {"authorization_url": oauth_svc.build_authorization_url(state)}


@router.get("/oauth/google/callback")
def google_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """
    Step 2: Google redirects the user's browser HERE directly (not a
    fetch call from the frontend), so failures here can't hand back a
    JSON error the way the rest of this API does — every path below
    ends in a redirect back to the frontend, either with a one-time
    `?oauth_code=` (success — see POST /oauth/exchange) or an
    `?oauth_error=` message the login page can display.
    """
    def _redirect_with_error(message: str) -> RedirectResponse:
        from urllib.parse import quote
        return RedirectResponse(f"{FRONTEND_URL}/?oauth_error={quote(message)}")

    if error:
        return _redirect_with_error("Google sign-in was cancelled or denied.")
    if not oauth_svc.GOOGLE_OAUTH_CONFIGURED:
        return _redirect_with_error("Google sign-in isn't configured for this deployment.")
    if not code or not state:
        return _redirect_with_error("Missing information from Google's redirect. Please try again.")

    decoded_state = decode_access_token(state)
    if not decoded_state or "oauth_provider" not in decoded_state:
        return _redirect_with_error("This sign-in attempt has expired. Please try again.")

    try:
        profile = oauth_svc.exchange_code_for_profile(code)
    except oauth_svc.GoogleOAuthError as err:
        return _redirect_with_error(str(err))

    user = db.query(UserDB).filter(
        UserDB.oauth_provider == "google",
        UserDB.oauth_subject_id == profile["subject_id"],
    ).first()

    if not user:
        # Not linked yet — if an account with this (Google-verified)
        # email already exists from an ordinary password signup, link
        # this Google identity to it rather than erroring or creating
        # a confusing second account for the same person. Trusting
        # Google's own email_verified flag here is the same trust bar
        # this project already applies to its own email-verification
        # links elsewhere.
        user = db.query(UserDB).filter(UserDB.email == profile["email"]).first()
        if user:
            user.oauth_provider = "google"
            user.oauth_subject_id = profile["subject_id"]
            user.email_verified = True
            db.commit()
            db.refresh(user)

    new_org_invite_code = None

    if not user:
        # Genuinely new to this app — provision an account the same
        # way POST /auth/signup does, using the org context carried
        # through in `state`.
        org_name = decoded_state.get("oauth_org_name")
        invite_code = decoded_state.get("oauth_invite_code")
        role = decoded_state.get("oauth_role") or "agent"

        if not org_name and not invite_code:
            return _redirect_with_error("No organization was selected before starting Google sign-in. Please try again.")
        if org_name and invite_code:
            return _redirect_with_error("Provide only one of organization name or invite code, not both.")

        if org_name:
            org = OrganizationDB(name=org_name.strip(), invite_code=generate_invite_code())
            db.add(org)
            db.commit()
            db.refresh(org)
            org_id = org.id
            effective_role = "admin"
            new_org_invite_code = org.invite_code
        else:
            org = db.query(OrganizationDB).filter(OrganizationDB.invite_code == invite_code).first()
            if not org:
                return _redirect_with_error("That invite code doesn't match any organization.")
            if org.is_suspended:
                return _redirect_with_error("This organization is currently suspended and isn't accepting new members.")
            # Same anti-privilege-escalation rule as POST /auth/signup:
            # an invite code alone must never grant self-selected admin.
            effective_role = "agent" if role == "admin" else role
            org_id = org.id

        base_username = profile["email"].split("@")[0]
        username = base_username
        suffix = 1
        while db.query(UserDB).filter(UserDB.username == username).first():
            suffix += 1
            username = f"{base_username}{suffix}"

        user = UserDB(
            username=username,
            email=profile["email"],
            # OAuth-only accounts have no password of their own — this
            # column is NOT NULL (see models/user.py), so a securely
            # random value is stored that is never shared with the
            # user and never usable to log in via POST /auth/login.
            # has_usable_password=False is what actually marks the
            # account as OAuth-only (see POST /auth/me/set-password
            # for the self-service fallback if Google sign-in is later
            # disabled for this deployment).
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            has_usable_password=False,
            role=effective_role,
            display_name=profile["name"],
            org_id=org_id,
            is_active=True,
            email_verified=True,
            oauth_provider="google",
            oauth_subject_id=profile["subject_id"],
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        _send_welcome_email(user, org, is_new_org=bool(org_name), invite_code=new_org_invite_code)

    if not user.is_active:
        return _redirect_with_error("This account has been deactivated. Contact your admin.")

    login_code = create_oauth_login_code(user.id)
    from urllib.parse import quote
    return RedirectResponse(f"{FRONTEND_URL}/?oauth_code={quote(login_code)}")


@router.post("/oauth/exchange", response_model=TokenResponse)
@limiter.limit("10/minute")
def exchange_oauth_login_code(request: Request, payload: OAuthExchangeRequest, db: Session = Depends(get_db)):
    """
    Step 3: the frontend lands on `/?oauth_code=...` after the Google
    redirect, immediately calls this with that code, and gets back a
    real session — the same access_token/refresh_token/user shape as
    POST /auth/login, so the rest of the app treats an SSO session
    identically to a password one. See create_oauth_login_code's
    docstring for why this handoff step exists instead of putting real
    tokens directly in the redirect URL.
    """
    decoded = decode_access_token(payload.code)
    if not decoded or "oauth_login_user_id" not in decoded:
        raise HTTPException(status_code=401, detail="This sign-in link has expired. Please sign in again.")

    user = db.query(UserDB).filter(UserDB.id == decoded["oauth_login_user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="This sign-in link has expired. Please sign in again.")

    ip_address = security_svc.client_ip(request)
    device_info = security_svc.parse_user_agent(request.headers.get("user-agent"))
    suspicious = security_svc.is_suspicious_login(db, user.id, ip_address)
    security_svc.record_login_history(db, user.id, user.org_id, "suspicious_login" if suspicious else "login_success", ip_address, device_info)
    if suspicious:
        send_security_alert_email(user.email, "New login from an unrecognized location", ip_address=ip_address, device_info=device_info)

    token = create_access_token({"sub": user.id, "role": user.role.value, "org_id": user.org_id})
    refresh_token = _issue_refresh_token(db, user.id, device_info=device_info, ip_address=ip_address)
    return {"access_token": token, "refresh_token": refresh_token, "user": user, "org_invite_code": None}


@router.post("/demo-login", response_model=TokenResponse)
@limiter.limit("10/hour")
def demo_login(request: Request, db: Session = Depends(get_db)):
    """
    "Try the Demo" — logs straight into a real, fully-populated
    dispatcher account with zero signup, zero password, zero typing.
    See services/demo_seed.py's own module docstring for the full
    design rationale (why this is one shared sandbox org rather than a
    private one per visitor, what it does and doesn't seed, and how
    it's kept from staying broken after visitors poke at it).

    Rate-limited tighter than a normal login (10/hour per IP, vs the
    usual 10/minute elsewhere in this file) — this endpoint needs no
    credentials at all, so it's the one auth endpoint here an
    automated script could hit relentlessly for no cost; a generous
    but bounded hourly cap stops that without getting in the way of a
    real visitor trying the demo a few times.

    Seeds the demo org on first-ever call if it doesn't exist yet
    (e.g. a fresh local `docker compose up` with an empty database) so
    this works out of the box with no separate manual seeding step —
    on every call after that, it just logs into the existing seeded
    org rather than re-seeding on every click (see
    services/demo_reset_scheduler.py for what keeps it fresh instead).
    """
    admin = demo_seed_svc.get_demo_admin(db)
    if not admin:
        org = demo_seed_svc.seed_demo_org(db)
        admin = demo_seed_svc.get_demo_admin(db)

    if not admin or not admin.is_active:
        raise HTTPException(status_code=503, detail="The demo isn't available right now. Please try again shortly.")

    token = create_access_token({"sub": admin.id, "role": admin.role.value, "org_id": admin.org_id})
    refresh_token = _issue_refresh_token(db, admin.id, device_info="demo", ip_address=security_svc.client_ip(request))
    return {"access_token": token, "refresh_token": refresh_token, "user": admin, "org_invite_code": None}


@router.post("/2fa/resend-code")
@limiter.limit("5/minute")
def resend_two_factor_login_code(request: Request, payload: TwoFactorLoginVerify, db: Session = Depends(get_db)):
    """
    Sends a fresh login code to an "email" 2FA account's inbox — for
    when the first one expired, got lost, or landed in spam.
    `payload.code` is ignored here (the model is reused for its
    `challenge_token` field); only the token matters.
    """
    decoded = decode_access_token(payload.challenge_token)
    if not decoded or "pending_2fa_user_id" not in decoded:
        raise HTTPException(status_code=401, detail="This login attempt has expired. Log in again.")

    user = db.query(UserDB).filter(UserDB.id == decoded["pending_2fa_user_id"]).first()
    if not user or not user.is_active or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="This login attempt has expired. Log in again.")
    if user.two_factor_method != "email":
        raise HTTPException(status_code=400, detail="This account doesn't use email codes.")

    masked_email = _issue_and_send_email_otp(db, user, purpose="login")
    return {"sent": True, "masked_email": masked_email}


@router.post("/2fa/verify-login", response_model=TokenResponse)
@limiter.limit("10/minute")
def verify_two_factor_login(request: Request, payload: TwoFactorLoginVerify, db: Session = Depends(get_db)):
    """
    Second step of login for an account with 2FA turned on: exchanges a
    valid challenge_token (from POST /auth/login) plus a correct code
    for a real access token. Branches on the account's
    `two_factor_method` to check against the right kind of code.
    """
    decoded = decode_access_token(payload.challenge_token)
    if not decoded or "pending_2fa_user_id" not in decoded:
        raise HTTPException(status_code=401, detail="This login attempt has expired. Log in again.")

    user = db.query(UserDB).filter(UserDB.id == decoded["pending_2fa_user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="This login attempt has expired. Log in again.")

    if not user.totp_enabled:
        # 2FA was turned off between step 1 and step 2 (rare, but
        # possible) — nothing left to verify against.
        raise HTTPException(status_code=400, detail="Two-factor authentication is no longer enabled on this account.")

    if user.two_factor_method == "email":
        code_valid = _verify_and_consume_email_otp(db, user.id, purpose="login", code=payload.code.strip())
    else:
        code_valid = bool(user.totp_secret) and verify_code(user.totp_secret, payload.code)

    if not code_valid:
        # Fall back to a recovery code — lets someone back in when they've
        # lost their authenticator app or can't reach the 2FA email inbox.
        code_valid = security_svc.verify_and_consume_recovery_code(db, user.id, payload.code)
        if code_valid:
            security_svc.record_security_event(db, user.id, user.org_id, "recovery_code_used")

    if not code_valid:
        raise HTTPException(status_code=401, detail="Incorrect code. Check your authenticator app, or use a recovery code.")

    ip_address = security_svc.client_ip(request)
    device_info = security_svc.parse_user_agent(request.headers.get("user-agent"))
    suspicious = security_svc.is_suspicious_login(db, user.id, ip_address)
    security_svc.record_login_history(db, user.id, user.org_id, "suspicious_login" if suspicious else "login_success", ip_address, device_info)
    if suspicious:
        send_security_alert_email(user.email, "New login from an unrecognized location", ip_address=ip_address, device_info=device_info)

    token = create_access_token({"sub": user.id, "role": user.role.value, "org_id": user.org_id})
    refresh_token = _issue_refresh_token(db, user.id, device_info=device_info, ip_address=ip_address)
    return {"access_token": token, "refresh_token": refresh_token, "user": user, "org_invite_code": None}


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Requests a password reset email. ALWAYS returns the same generic
    success message, whether or not that email actually belongs to an
    account — revealing "yes, that email exists" vs "no, it doesn't"
    would let anyone probe which emails are registered users, which is a
    real (if minor) information leak. The rate limit here (3/minute) also
    specifically guards against someone hammering this endpoint to spam
    reset emails at a real user's inbox.
    """
    GENERIC_RESPONSE = {
        "message": "If that email is registered, a password reset link has been sent."
    }

    if CAPTCHA_CONFIGURED and not verify_captcha(payload.captcha_token):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    user = db.query(UserDB).filter(UserDB.email == payload.email).first()
    if not user or not user.is_active:
        return GENERIC_RESPONSE

    reset_token = PasswordResetTokenDB(user_id=user.id)
    db.add(reset_token)
    db.commit()
    db.refresh(reset_token)

    reset_link = f"{FRONTEND_URL}/?reset_token={reset_token.token}"
    send_password_reset_email(user.email, reset_link)

    return GENERIC_RESPONSE


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Completes a password reset, given a valid, unused, unexpired token."""
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    reset_token = db.query(PasswordResetTokenDB).filter(
        PasswordResetTokenDB.token == payload.token
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="This reset link is invalid.")
    if reset_token.used:
        raise HTTPException(status_code=400, detail="This reset link has already been used.")
    if reset_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link has expired. Request a new one.")

    user = db.query(UserDB).filter(UserDB.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid.")
    if security_svc.is_password_reused(db, user.id, payload.new_password):
        raise HTTPException(status_code=400, detail=f"That's one of your last {security_svc.PASSWORD_HISTORY_LIMIT} passwords. Choose a different one.")

    security_svc.record_password_history(db, user.id, user.hashed_password)
    user.hashed_password = hash_password(payload.new_password)
    reset_token.used = True
    db.commit()
    security_svc.record_security_event(db, user.id, user.org_id, "password_reset")
    send_security_alert_email(user.email, "Your password was reset")

    return {"message": "Password reset successfully. You can now log in with your new password."}


# ---------- Email verification ----------
# Confirms the email address on a staff account is real/reachable.
# Deliberately does NOT block login or any other action — this project
# treats it as informational rather than a hard gate, for two reasons:
# (1) an admin creating an org and inviting teammates needs to be able
# to use the account immediately, not wait on an email round-trip
# before they can even see their own dashboard; (2) SMTP is optional in
# this project (see backend/.env.example) — locking accounts out until
# a verification email arrives would make the app partially unusable
# for anyone running it without SMTP configured. What this DOES give:
# a real, checkable `email_verified` flag or the frontend to show a
# "please verify" nudge, and a genuine confirmation step for anyone who
# wants one — the same trade-off many real products make (Slack,
# GitHub, etc. all let you use the product before verifying).

@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    verification = db.query(EmailVerificationTokenDB).filter(
        EmailVerificationTokenDB.token == payload.token
    ).first()

    if not verification:
        raise HTTPException(status_code=400, detail="This verification link is invalid.")
    if verification.used:
        raise HTTPException(status_code=400, detail="This verification link has already been used.")
    if verification.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This verification link has expired. Request a new one.")

    user = db.query(UserDB).filter(UserDB.id == verification.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="This verification link is invalid.")

    user.email_verified = True
    verification.used = True
    db.commit()

    return {"message": "Email verified."}


def get_current_user(
    authorization: str = Header(None), db: Session = Depends(get_db)
) -> UserDB:
    """
    FastAPI dependency: extracts and validates the JWT from the
    'Authorization: Bearer <token>' header, and returns the corresponding
    user. Any route that depends on this requires a logged-in user with
    an active account.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    user = db.query(UserDB).filter(UserDB.id == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated. Contact your admin.")

    return user


@router.post("/resend-verification")
@limiter.limit("3/minute")
def resend_verification(request: Request, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.email_verified:
        return {"message": "This account's email is already verified."}
    _issue_and_send_verification_email(db, current_user)
    return {"message": "Verification email sent."}


# ---------- Refresh tokens ----------
# See models/refresh_token.py's module docstring for the full design
# rationale (hashing, rotation, theft detection). This is what a client
# calls with the refresh_token it got at login/signup, shortly before
# its short-lived access token (30 minutes — services/auth.py) expires,
# to get a new pair of both without making the person log in again.

@router.post("/refresh", response_model=RefreshTokenResponse)
@limiter.limit("30/minute")
def refresh_access_token(request: Request, payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshTokenDB).filter(RefreshTokenDB.token_hash == token_hash).first()

    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token. Log in again.")

    if stored.used or stored.revoked_at is not None:
        # Reuse of an already-rotated (or already-revoked) refresh
        # token — see models/refresh_token.py's docstring: this is a
        # theft signal, not an ordinary expiry. Revoke every other
        # still-live token for this user too, since at this point
        # neither the legitimate holder's copy nor whoever just
        # presented this one can be trusted to be the only party who
        # has it.
        db.query(RefreshTokenDB).filter(
            RefreshTokenDB.user_id == stored.user_id,
            RefreshTokenDB.revoked_at.is_(None),
        ).update({"revoked_at": datetime.utcnow()})
        db.commit()
        raise HTTPException(status_code=401, detail="This session was revoked. Log in again.")

    if stored.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Your session has expired. Log in again.")

    user = db.query(UserDB).filter(UserDB.id == stored.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token. Log in again.")

    new_raw_token = generate_refresh_token()
    new_row = RefreshTokenDB(
        user_id=user.id, token_hash=hash_refresh_token(new_raw_token),
        device_info=stored.device_info, ip_address=stored.ip_address,
    )
    db.add(new_row)
    db.flush()  # assigns new_row.id without a second round trip

    stored.used = True
    stored.replaced_by_id = new_row.id
    db.commit()

    new_access_token = create_access_token({"sub": user.id, "role": user.role.value, "org_id": user.org_id})
    return {"access_token": new_access_token, "refresh_token": new_raw_token}


@router.post("/logout")
def logout(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Server-side session revocation — this is the actual "log out"
    beyond just the frontend clearing its local storage. Without this,
    a refresh token issued at login would stay silently valid for its
    full expiry (30 days) even after the person clicked "log out,"
    since a JWT-only scheme has no way to invalidate anything before
    its own expiry. Deliberately not authenticated with an access
    token: logging out should work even if the access token already
    expired, and the refresh token itself is enough proof of the
    session being ended.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshTokenDB).filter(RefreshTokenDB.token_hash == token_hash).first()
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.utcnow()
        db.commit()
        user = db.query(UserDB).filter(UserDB.id == stored.user_id).first()
        if user:
            security_svc.record_security_event(db, user.id, user.org_id, "session_revoked", detail="Logged out")
    return {"message": "Logged out."}


# ---------- Self-service account settings (staff, logged in) ----------
# Mirrors routes/customer_auth.py's GET/PATCH /me + POST /me/change-password
# exactly, for the same self-service reasons — a staff member editing
# their own display name or changing their own password shouldn't need
# an admin to do it for them (admin.py's reset-password endpoint is for
# an admin acting on SOMEONE ELSE's account; this is a user acting on
# their own, and requires proving they know the current password rather
# than an admin's authority to skip that check).

@router.get("/me", response_model=UserOut)
def get_my_profile(current_user: UserDB = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
def update_my_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=400, detail="Display name can't be empty.")
        current_user.display_name = display_name

    if payload.email is not None:
        email = payload.email.strip()
        if not email:
            raise HTTPException(status_code=400, detail="Email can't be empty.")
        if email != current_user.email:
            existing = db.query(UserDB).filter(UserDB.email == email).first()
            if existing:
                raise HTTPException(status_code=400, detail="Another account already uses that email.")
            current_user.email = email

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/change-password")
def change_my_password(
    payload: UserPasswordChange,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")
    if security_svc.is_password_reused(db, current_user.id, payload.new_password):
        raise HTTPException(status_code=400, detail=f"That's one of your last {security_svc.PASSWORD_HISTORY_LIMIT} passwords. Choose a different one.")

    security_svc.record_password_history(db, current_user.id, current_user.hashed_password)
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "password_changed")
    send_security_alert_email(current_user.email, "Your password was changed")
    return {"message": "Password changed."}


@router.post("/me/set-password")
def set_my_password(
    payload: UserSetPassword,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Lets an OAuth-only account (has_usable_password False — see
    UserDB's docstring) add a real password for the first time, so
    they have a fallback way to log in if Google sign-in is later
    disabled or unreachable. Deliberately rejects this for an account
    that already has a usable password — that's what
    /me/change-password is for, and it correctly requires proving the
    CURRENT password first, a check this route has nothing to compare
    against for a brand-new password.
    """
    if current_user.has_usable_password:
        raise HTTPException(
            status_code=400,
            detail="This account already has a password. Use \"Change password\" instead.",
        )
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.has_usable_password = True
    db.commit()
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "password_changed")
    send_security_alert_email(
        current_user.email,
        "A password was added to your account — you can now log in with it as well as Google Sign-In.",
    )
    return {"message": "Password set. You can now log in with it, in addition to Google Sign-In."}


# ---------- Two-factor auth: setup / enable / disable (staff, logged in) ----------
# These three routes require an already-valid access token, which is why
# they're defined after get_current_user above rather than next to
# /login and /2fa/verify-login (both of which run BEFORE a session
# exists). Turning 2FA on is a two-step process on purpose — /2fa/setup
# hands back a QR code but does NOT enable anything yet, and /2fa/enable
# only flips it on once the user proves their authenticator app actually
# received it by submitting one real code. Skipping straight to "on"
# would risk locking someone out on a secret their app never scanned.

@router.get("/2fa/status", response_model=TwoFactorStatusOut)
def get_two_factor_status(current_user: UserDB = Depends(get_current_user)):
    return {"totp_enabled": current_user.totp_enabled, "two_factor_method": current_user.two_factor_method}


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
def setup_two_factor(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    """Start setup for the AUTHENTICATOR APP method. For the email-code method, see /2fa/setup-email below instead."""
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled. Disable it first to set up a new device.")

    secret = generate_secret()
    current_user.totp_secret = secret
    db.commit()

    uri = get_provisioning_uri(secret, current_user.username)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/2fa/enable")
def enable_two_factor(
    payload: TwoFactorCodeRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Confirms the AUTHENTICATOR APP method with one real code from it, and turns 2FA on."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Start setup first (POST /auth/2fa/setup) before confirming a code.")
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled.")

    if not verify_code(current_user.totp_secret, payload.code):
        raise HTTPException(status_code=400, detail="Incorrect code. Check your authenticator app and try again.")

    current_user.totp_enabled = True
    current_user.two_factor_method = "totp"
    db.commit()
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "2fa_enabled", detail="totp")
    recovery_codes = security_svc.generate_recovery_codes(db, current_user.id)
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "recovery_codes_generated")
    return {"success": True, "message": "Two-factor authentication is now enabled on your account.", "recovery_codes": recovery_codes}


@router.post("/2fa/setup-email")
@limiter.limit("5/minute")
def setup_email_two_factor(request: Request, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    """
    Start setup for the EMAIL CODE method: sends a confirmation code to
    the user's own account email right away — the "device" being set up
    here is the inbox itself, so there's nothing to scan first the way
    there is with an authenticator app. POST /2fa/enable-email with that
    code turns it on.
    """
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled. Disable it first to switch methods.")

    masked_email = _issue_and_send_email_otp(db, current_user, purpose="enable_2fa")
    return {"sent": True, "masked_email": masked_email}


@router.post("/2fa/enable-email")
def enable_email_two_factor(
    payload: TwoFactorEmailCodeRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled.")

    if not _verify_and_consume_email_otp(db, current_user.id, purpose="enable_2fa", code=payload.code.strip()):
        raise HTTPException(status_code=400, detail="Incorrect or expired code. Request a new one and try again.")

    current_user.totp_enabled = True
    current_user.two_factor_method = "email"
    current_user.totp_secret = None  # this account uses email codes, not an authenticator secret
    db.commit()
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "2fa_enabled", detail="email")
    recovery_codes = security_svc.generate_recovery_codes(db, current_user.id)
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "recovery_codes_generated")
    return {"success": True, "message": "Two-factor authentication is now enabled on your account.", "recovery_codes": recovery_codes}


@router.post("/2fa/disable")
def disable_two_factor(
    payload: TwoFactorDisableRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Requires the account password again — not just an active session —
    so someone who grabs an unlocked, logged-in device can't silently
    strip 2FA off the account themselves. Works the same regardless of
    which method (authenticator app or email) is currently active."""
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.two_factor_method = "totp"
    db.commit()
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "2fa_disabled")
    send_security_alert_email(current_user.email, "Two-factor authentication was disabled on your account")
    return {"success": True, "message": "Two-factor authentication has been disabled."}


# ---------- Sessions, login history, security events, recovery codes (Phase 17) ----------
# All self-service, staff-facing — mirrors the "acting on your own
# account" reasoning already established above for change-password.

@router.get("/sessions", response_model=List[SessionOut])
def list_my_sessions(
    current_refresh_token: str = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Active (not revoked, not expired) sessions for the logged-in user.
    `current_refresh_token` is an OPTIONAL query param the frontend can
    pass (it already has the raw token in memory/storage) so THIS
    session can be marked is_current — there's no way to derive that
    from an access token alone, since an access token carries no
    session/session-id claim linking it back to the refresh token that
    issued it.
    """
    now = datetime.utcnow()
    sessions = db.query(RefreshTokenDB).filter(
        RefreshTokenDB.user_id == current_user.id, RefreshTokenDB.revoked_at.is_(None), RefreshTokenDB.expires_at > now,
    ).order_by(RefreshTokenDB.created_at.desc()).all()

    current_hash = hash_refresh_token(current_refresh_token) if current_refresh_token else None
    result = []
    for s in sessions:
        out = SessionOut.model_validate(s)
        out.is_current = (s.token_hash == current_hash)
        result.append(out)
    return result


@router.delete("/sessions/{session_id}")
def revoke_my_session(session_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    session = db.query(RefreshTokenDB).filter(RefreshTokenDB.id == session_id, RefreshTokenDB.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    security_svc.revoke_session(db, session)
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "session_revoked", detail="Revoked from Active Sessions")
    return {"message": "Session revoked."}


@router.post("/sessions/logout-all")
def logout_all_sessions(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    """Revokes EVERY active session for this account, including the one making this request — the frontend should treat this the same as an immediate forced logout."""
    count = security_svc.revoke_all_sessions(db, current_user.id)
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "all_sessions_revoked", detail=f"{count} session(s)")
    send_security_alert_email(current_user.email, "You were logged out of all devices")
    return {"message": f"{count} session(s) logged out."}


@router.get("/login-history", response_model=List[LoginHistoryOut])
def get_my_login_history(limit: int = 50, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    limit = min(max(limit, 1), 200)
    return db.query(LoginHistoryDB).filter(LoginHistoryDB.user_id == current_user.id).order_by(LoginHistoryDB.created_at.desc()).limit(limit).all()


@router.get("/security-events", response_model=List[SecurityEventOut])
def get_my_security_events(limit: int = 50, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    limit = min(max(limit, 1), 200)
    return db.query(SecurityEventDB).filter(SecurityEventDB.user_id == current_user.id).order_by(SecurityEventDB.created_at.desc()).limit(limit).all()


@router.post("/2fa/recovery-codes/generate", response_model=RecoveryCodesOut)
def regenerate_recovery_codes(
    payload: RecoveryCodesGenerateRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Requires the account password, same reasoning as /2fa/disable — regenerating codes invalidates every existing one, so it shouldn't be possible from a merely-unlocked device without proving it's really the account owner."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication isn't enabled on this account.")
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    codes = security_svc.generate_recovery_codes(db, current_user.id)
    security_svc.record_security_event(db, current_user.id, current_user.org_id, "recovery_codes_generated")
    return RecoveryCodesOut(codes=codes)
