"""
User model — supports three roles: "agent", "dispatcher", and "admin".

Every user belongs to exactly one organization (org_id) — see
models/organization.py for how that's established at signup.

Design decision on usernames: kept GLOBALLY unique (not just unique
within an org), so login only ever needs a username + password with no
extra org context — a user picks their org at signup time (create one, or
join via invite code), and every login afterward is unambiguous. The
trade-off: two different organizations can't both have a user named
"admin", for example. For this project's scope, that's an acceptable
simplification worth being able to explain, rather than adding org-scoped
login (which would need the login form to ask "which organization?" too).
"""

import enum
import uuid

from sqlalchemy import Column, String, Enum as SqlEnum, Boolean, Float, Integer, DateTime
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class UserRole(str, enum.Enum):
    agent = "agent"
    dispatcher = "dispatcher"
    admin = "admin"


class UserDB(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(SqlEnum(UserRole), nullable=False)
    display_name = Column(String, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Set True once this account's email address has been confirmed via
    # the link sent at signup (see routes/auth.py's /verify-email). Does
    # NOT block login — see that route's docstring for why — this is
    # purely informational so the frontend can show a "please verify"
    # banner and the account's own history shows whether its contact
    # email was ever actually confirmed reachable.
    email_verified = Column(Boolean, nullable=False, default=False)

    # Two-factor auth (TOTP). totp_secret is written as soon as the user
    # starts setup (see routes/auth.py's /2fa/setup) but totp_enabled
    # stays False until they prove they scanned it correctly by
    # submitting one valid code (/2fa/enable) — this prevents a user
    # locking themselves out by enabling 2FA against a secret their
    # authenticator app never actually received. A stale, never-confirmed
    # secret from an abandoned setup attempt is harmless: login only
    # checks totp_secret when totp_enabled is True.
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    # Which second factor is active when totp_enabled is True: "totp" (an
    # authenticator app, using totp_secret above) or "email" (a one-time
    # code sent to `email` at login time — see services/email_otp.py).
    # Meaningless while totp_enabled is False.
    two_factor_method = Column(String, nullable=False, default="totp")

    # Account lockout (Phase 17) — auto-expiring, no manual admin-unlock
    # endpoint needed. failed_login_count resets to 0 on any successful
    # login; locked_until is set once the count crosses
    # services/security.py's threshold and simply expires on its own
    # after a fixed window, rather than requiring an admin action to
    # lift it (a locked-out legitimate user shouldn't need to file a
    # support ticket just to wait out a lockout).
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

    # An agent's real-world coverage area — set via "Detect my area" on
    # their profile (browser GPS -> services/geocoding.py reverse
    # geocode), NOT hand-typed, so it reflects where the agent actually
    # is rather than a guess. Used to prioritize zone-matched agents when
    # a dispatcher assigns or auto-assigns a delivery that has a `zone`
    # set (see routes/deliveries.py's _rank_agents_for_delivery).
    # Meaningless for non-agent roles.
    area_name = Column(String, nullable=True)
    area_latitude = Column(Float, nullable=True)
    area_longitude = Column(Float, nullable=True)

    # Pay rates for workforce earnings statements (see
    # models/earnings.py / services/earnings.py). Both optional and
    # independent — an org might pay purely hourly, purely per-delivery,
    # both, or (until an admin sets either) neither, in which case
    # earnings generation still runs but produces a zero-pay statement
    # rather than erroring, so the hours/delivery-count data is still
    # useful on its own.
    hourly_rate = Column(Float, nullable=True)
    per_delivery_rate = Column(Float, nullable=True)

    # Granular RBAC (Phase 4) — see models/rbac.py's module docstring.
    # Null means "use this user's base `role`'s default permission
    # grants" (see services/permissions.py) — completely unaffected
    # unless an admin explicitly assigns a custom role.
    custom_role_id = Column(String, nullable=True)

    # OAuth/SSO (Google) — set only for an account created via, or
    # later linked to, Google sign-in (see routes/auth.py's
    # /oauth/google/* endpoints and services/oauth.py). oauth_subject_id
    # is Google's own stable per-account "sub" claim — NOT the email
    # address, since an email can be reused/changed on Google's side
    # in ways their subject id never is. Both stay NULL for every
    # ordinary password-only account, which is the common case and
    # requires no change to existing rows. An OAuth-provisioned
    # account still gets a `hashed_password` (never NULL, per the
    # column's own constraint) — see the callback route for why that's
    # a securely-random, never-shared value rather than skipped.
    oauth_provider = Column(String, nullable=True)
    oauth_subject_id = Column(String, nullable=True, index=True)
    # True for every ordinary password-signup account (the default,
    # so existing rows and every future non-OAuth INSERT get True for
    # free — see migrate.py's scalar-default handling). Explicitly set
    # False only at OAuth account-creation time (routes/auth.py's
    # Google callback), since that account's hashed_password is a
    # securely-random value never shared with the user and can't
    # actually be used to log in via POST /auth/login. Flips back to
    # True once the user sets a real password via POST
    # /auth/me/set-password (see that route) — the self-service
    # fallback this project didn't have when OAuth/SSO first shipped:
    # without it, an OAuth-only account had no way to log in at all if
    # Google sign-in were later disabled for the deployment.
    has_usable_password = Column(Boolean, nullable=False, default=True)


# ---------- Pydantic Schemas ----------

class UserSignup(BaseModel):
    username: str
    email: str
    password: str
    role: UserRole
    display_name: str
    # Provide exactly one of these two: org_name to CREATE a new
    # organization (this user becomes its admin automatically), or
    # invite_code to JOIN an existing one with the role chosen above.
    org_name: Optional[str] = None
    invite_code: Optional[str] = None
    # Optional CAPTCHA response token (see services/captcha.py) — only
    # actually checked when RECAPTCHA_SECRET_KEY is configured server-side;
    # omit entirely in local dev, same "bring your own credentials, or it
    # no-ops" pattern as this project's other optional integrations
    # (Razorpay, VAPID push, Google geocoding).
    captcha_token: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: UserRole
    display_name: str
    org_id: str
    is_active: bool
    email_verified: bool = False
    totp_enabled: bool = False
    two_factor_method: str = "totp"
    area_name: Optional[str] = None
    hourly_rate: Optional[float] = None
    per_delivery_rate: Optional[float] = None
    custom_role_id: Optional[str] = None
    oauth_provider: Optional[str] = None
    has_usable_password: bool = True

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """
    Self-service profile edit for a logged-in staff user — mirrors
    CustomerProfileUpdate's shape/behavior in models/customer.py.
    Deliberately excludes `username`: it's this app's login identifier
    (see auth.py's /login, which looks a user up by username), so
    letting it change here would need the same "does this collide with
    another account" + "which sessions/audit-log entries reference the
    old value" handling account deletion/rename flows always need, and
    nothing about self-service editing actually requires it — a staff
    member's display_name is what changes when they want a different
    name shown to teammates/customers, without touching how they log in.
    """
    display_name: Optional[str] = None
    email: Optional[str] = None


class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str


class UserSetPassword(BaseModel):
    """
    For POST /auth/me/set-password — an OAuth-only account (see
    UserDB.has_usable_password) adding a real password for the first
    time. Deliberately a SEPARATE model from UserPasswordChange rather
    than making current_password optional on that one: this route only
    ever applies to an account that has no usable password to prove
    knowledge of in the first place, so there's nothing to reuse the
    "verify current, then set new" shape for — see the route itself
    for what it checks instead (a valid session is the only proof
    available, same trust level Google's own sign-in already granted).
    """
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserOut
    org_invite_code: Optional[str] = None  # only present when a NEW org was just created


class LoginResult(BaseModel):
    """
    Response shape for POST /auth/login. Covers both outcomes with one
    model rather than two, since FastAPI needs a single response_model:
    a normal login (access_token + user populated, requires_2fa False),
    or a 2FA challenge (only requires_2fa + challenge_token populated —
    no access_token yet, since the password alone isn't enough to prove
    identity for an account with 2FA turned on).
    """
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserOut] = None
    org_invite_code: Optional[str] = None
    requires_2fa: bool = False
    challenge_token: Optional[str] = None
    two_factor_method: Optional[str] = None  # "totp" or "email", only set when requires_2fa is True
    masked_email: Optional[str] = None  # e.g. "m***y@example.com" — only set when two_factor_method is "email"


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorCodeRequest(BaseModel):
    code: str


class TwoFactorLoginVerify(BaseModel):
    challenge_token: str
    code: str


class TwoFactorDisableRequest(BaseModel):
    password: str


class TwoFactorStatusOut(BaseModel):
    totp_enabled: bool
    two_factor_method: str = "totp"


class TwoFactorEmailCodeRequest(BaseModel):
    code: str


class AreaDetectRequest(BaseModel):
    latitude: float
    longitude: float


class AreaSetRequest(BaseModel):
    area_name: str


class AreaOut(BaseModel):
    area_name: Optional[str] = None
    area_latitude: Optional[float] = None
    area_longitude: Optional[float] = None


class PayRateUpdate(BaseModel):
    """Admin-only: set (or clear, by passing null) a staff member's pay rates. See UserDB.hourly_rate / per_delivery_rate."""
    hourly_rate: Optional[float] = None
    per_delivery_rate: Optional[float] = None
