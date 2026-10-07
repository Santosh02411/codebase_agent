"""
Authentication utilities: password hashing and JWT token creation/verification.

SECRET_KEY is read from the JWT_SECRET_KEY environment variable. If it's
not set, a dev-only fallback is used AND a warning is printed on startup —
this is fine for local development, but the fallback is a fixed, publicly-
visible string, so anyone could forge valid tokens against a deployment
that still uses it. Before deploying this publicly, set JWT_SECRET_KEY to
a long, random, secret value (e.g. `python -c "import secrets;
print(secrets.token_hex(32))"`). Documented as a known v1 gap in
docs/SECURITY_AND_ACCESS.md.

When ENVIRONMENT=production, this stops being a warning and becomes a
hard startup failure instead — see the ENVIRONMENT block below. A
warning that scrolls by in a terminal is easy to miss; a real
deployment refusing to start with the insecure default key is not.
"""

import os
import secrets
import hashlib
import warnings
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

_DEV_FALLBACK_SECRET = "dev-only-secret-change-before-deploying"
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _DEV_FALLBACK_SECRET)

if SECRET_KEY == _DEV_FALLBACK_SECRET:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "Refusing to start with ENVIRONMENT=production and no JWT_SECRET_KEY set. "
            "The fallback signing key is a fixed, publicly-known string — running "
            "production with it means anyone can forge valid login tokens for any "
            "account. Set JWT_SECRET_KEY to a long, random value, e.g.: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    warnings.warn(
        "JWT_SECRET_KEY is not set — using an insecure, publicly-known "
        "default signing key. This is fine for local development only. "
        "Set the JWT_SECRET_KEY environment variable before deploying "
        "this anywhere real.",
        stacklevel=2,
    )

ALGORITHM = "HS256"
# Deliberately short now that refresh tokens (models/refresh_token.py)
# exist to keep a session alive past this — see that file's docstring
# for the full "why rotate instead of one long-lived token" reasoning.
# A stolen access token is only ever useful for this short a window;
# real, ongoing sessions are carried by the refresh token instead,
# which — unlike a JWT — CAN be revoked before it expires.
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


TWO_FACTOR_CHALLENGE_EXPIRE_MINUTES = 5


def create_two_factor_challenge_token(user_id: str) -> str:
    """
    A short-lived token issued after a correct username/password but
    before a correct 2FA code — proves "this caller knows the password"
    without yet granting real API access. Deliberately a much shorter
    expiry (5 minutes) than a normal access token, and a distinct claim
    shape ({"pending_2fa_user_id": ...} instead of {"sub": ..., "role":
    ...}) so it can never be mistaken for, or reused as, a real session
    token even if it leaked or a caller tried to pass it into an
    ordinary authenticated route.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=TWO_FACTOR_CHALLENGE_EXPIRE_MINUTES)
    to_encode = {"pending_2fa_user_id": user_id, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Returns the decoded token payload, or None if invalid/expired."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ---------- OAuth / SSO (Google) ----------
# Both of these are short-lived signed JWTs with a distinct claim shape
# from a real access token, following the exact same "self-contained,
# no server-side session storage needed" pattern as
# create_two_factor_challenge_token above.

OAUTH_STATE_EXPIRE_MINUTES = 10


def create_oauth_state_token(provider: str, org_name: str | None, invite_code: str | None, role: str | None) -> str:
    """
    Carries the signup context (which org to join/create, which role)
    across the redirect to Google and back — Google echoes the `state`
    query param back to our callback verbatim, and since it's signed,
    the callback can trust it wasn't tampered with in transit without
    needing a server-side session/state table.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    to_encode = {
        "oauth_provider": provider,
        "oauth_org_name": org_name,
        "oauth_invite_code": invite_code,
        "oauth_role": role,
        "exp": expire,
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


OAUTH_LOGIN_CODE_EXPIRE_MINUTES = 2


def create_oauth_login_code(user_id: str) -> str:
    """
    Issued after a successful Google OAuth callback and handed to the
    frontend as a one-time `?oauth_code=` query param, which it then
    exchanges (POST /auth/oauth/exchange) for real access/refresh
    tokens. Deliberately NOT the real tokens themselves — putting a
    long-lived refresh token directly in a redirect URL would leave it
    exposed in browser history and any HTTP referrer logging; this
    short-lived (2 min), single-purpose code carries none of that risk
    since on its own it grants nothing beyond "prove you're the
    browser Google just redirected".
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_LOGIN_CODE_EXPIRE_MINUTES)
    to_encode = {"oauth_login_user_id": user_id, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_customer_oauth_state_token() -> str:
    """
    Customer-side equivalent of create_oauth_state_token above, but
    much simpler: a customer account needs no org context at all to
    sign up (see CustomerDB's own comment on this), so there is
    nothing to carry through the redirect except proof the callback
    wasn't reached some other way — the signed token itself IS that
    proof, same CSRF-mitigation role `state` plays in the staff flow.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    return jwt.encode({"customer_oauth_provider": "google", "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def create_customer_oauth_login_code(customer_id: str) -> str:
    """Customer-side equivalent of create_oauth_login_code above."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_LOGIN_CODE_EXPIRE_MINUTES)
    to_encode = {"customer_oauth_login_customer_id": customer_id, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ---------- Refresh tokens ----------
# Shared by both staff (models/refresh_token.py) and customer
# (models/customer_refresh_token.py) sessions — the generation/hashing
# logic is identical either way; only which DB table a route stores the
# hash in differs.

def generate_refresh_token() -> str:
    """
    A long, random, high-entropy opaque string — NOT a JWT. Deliberately
    not a signed token: a refresh token's job is to be looked up against
    a database row that can be revoked, not to be self-contained and
    independently verifiable the way an access token is. token_urlsafe(48)
    gives 384 bits of randomness, comfortably unguessable.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    """
    SHA-256, not bcrypt — see models/refresh_token.py's docstring for
    why a fast hash is the correct (not weaker) choice for a token that
    is already high-entropy random data rather than a human-chosen
    password.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()
