"""
Google OAuth 2.0 / SSO for staff accounts.

Mirrors this project's existing "real integration, honest no-op if
unconfigured" pattern (see services/captcha.py, the Razorpay
integration in checkout, services/sms.py's console-log default): if
GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET aren't set, GOOGLE_OAUTH_CONFIGURED
is False and routes/auth.py's OAuth endpoints return a clear 400
("Google sign-in isn't configured for this deployment") instead of a
broken redirect to a nonexistent app — the previous, honest state of
this feature ("skipped, no provider infra available") is preserved as
the DEFAULT behavior; setting real credentials is what turns it on.

Scoped to staff accounts only (not customers), the same way 2FA is
staff-only elsewhere in this project — a natural, bounded extension
customers could get later without needing to touch this module.

No third-party OAuth library (authlib etc.) — Google's OAuth endpoints
are plain HTTP, and this project already depends on `requests`, so a
handful of direct calls avoids one more dependency for what's a very
small amount of actual protocol surface (build an authorize URL,
POST an authorization code for tokens, GET userinfo with the access
token).
"""

import os
from urllib.parse import urlencode

import requests

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
# Where Google redirects back to after the user approves/denies — this
# backend's own callback route, not the frontend. Must exactly match
# one of the "Authorized redirect URIs" configured in the Google Cloud
# Console for this OAuth client. Two DIFFERENT callback routes exist
# (staff vs customer — see routes/auth.py and routes/customer_auth.py
# respectively), so two DIFFERENT redirect URIs must both be
# registered in Google Cloud Console, and build_authorization_url()/
# exchange_code_for_profile() below both take redirect_uri as an
# explicit argument rather than relying on a single module-level
# default — using the wrong one for either flow means Google redirects
# the browser to the OTHER flow's callback, where the state token's
# claim shape won't match and the whole sign-in fails.
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/oauth/google/callback"
)
# No separate env var for this one on purpose — the customer callback
# always lives at the same host as the staff one, just under
# /customer/ instead of /auth/, so it's derived rather than asking the
# deployer to keep two URLs in sync by hand. Register it as a second
# "Authorized redirect URI" in Google Cloud Console alongside the
# staff one.
GOOGLE_CUSTOMER_REDIRECT_URI = GOOGLE_REDIRECT_URI.replace(
    "/auth/oauth/google/callback", "/customer/oauth/google/callback"
)

GOOGLE_OAUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

REQUEST_TIMEOUT_SECONDS = 10


def build_authorization_url(state: str, redirect_uri: str = GOOGLE_REDIRECT_URI) -> str:
    """
    The URL to send the user's browser to so they can approve access
    on Google's own consent screen. `state` is our own short-lived
    signed JWT (see services/auth.py's create_oauth_state_token) —
    Google echoes it back verbatim to the callback, which is both how
    this flow avoids needing server-side session storage for the
    signup context (org name / invite code / role chosen before the
    redirect) AND the standard OAuth2 CSRF-mitigation mechanism (a
    callback whose `state` doesn't verify is rejected outright).

    `redirect_uri` defaults to the staff callback — routes/
    customer_auth.py's caller passes GOOGLE_CUSTOMER_REDIRECT_URI
    explicitly instead. Whichever is passed here MUST be the exact
    same one passed to exchange_code_for_profile() below for the same
    flow, since Google validates that the token-exchange request's
    redirect_uri matches the one originally used to get the code.
    """
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


class GoogleOAuthError(Exception):
    """Raised for any failure talking to Google — network, bad code, etc."""
    pass


def exchange_code_for_profile(code: str, redirect_uri: str = GOOGLE_REDIRECT_URI) -> dict:
    """
    Full server-side half of the flow: trades the one-time
    authorization `code` Google sent to our callback for an access
    token, then uses that access token to fetch the user's Google
    profile. Returns {"subject_id", "email", "email_verified",
    "name"}. Raises GoogleOAuthError on any failure — a bad/expired/
    already-used code, a network error, or Google reporting the
    email itself isn't verified (which this project treats as
    unusable for auto-provisioning an account, same trust bar as
    everywhere else here).

    `redirect_uri` MUST be the exact same value passed to
    build_authorization_url() for this same flow — Google validates
    that the redirect_uri on this token-exchange request matches the
    one originally used to obtain `code`, and rejects the exchange
    (as an invalid_grant error) if it doesn't. routes/customer_auth.py
    passes GOOGLE_CUSTOMER_REDIRECT_URI explicitly for the customer
    flow instead of relying on this default.
    """
    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise GoogleOAuthError(f"Could not reach Google's token endpoint: {error}")

    if token_resp.status_code != 200:
        raise GoogleOAuthError("Google rejected the authorization code (it may be expired or already used).")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise GoogleOAuthError("Google's token response didn't include an access token.")

    try:
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise GoogleOAuthError(f"Could not reach Google's userinfo endpoint: {error}")

    if userinfo_resp.status_code != 200:
        raise GoogleOAuthError("Google rejected the request for profile info.")

    profile = userinfo_resp.json()
    subject_id = profile.get("sub")
    email = profile.get("email")
    if not subject_id or not email:
        raise GoogleOAuthError("Google's profile response was missing an account id or email.")

    if not profile.get("email_verified", False):
        raise GoogleOAuthError(
            "That Google account's email address isn't verified with Google, so it can't be used to sign in here."
        )

    return {
        "subject_id": subject_id,
        "email": email,
        "name": profile.get("name") or email.split("@")[0],
    }
