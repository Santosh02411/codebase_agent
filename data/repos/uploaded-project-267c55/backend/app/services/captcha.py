"""
Bot protection for public write endpoints (signup, forgot-password) via
Google reCAPTCHA v2 (the checkbox widget — "I'm not a robot"), chosen
over v3 because v2 needs no site-specific score-tuning to be useful and
its verification call is a single, simple POST.

To make this genuinely real:
    1. Register a site at google.com/recaptcha/admin (free, ~2 minutes,
       no billing account needed) — choose reCAPTCHA v2 "Checkbox".
    2. Set RECAPTCHA_SECRET_KEY below / in your .env (backend).
    3. Set VITE_RECAPTCHA_SITE_KEY in the frontend's env (see
       frontend/.env.example) so the widget actually renders.
Once both are set, every signup and forgot-password submission
genuinely round-trips through Google's siteverify API before the
request is allowed to proceed — no shortcuts.

WITHOUT RECAPTCHA_SECRET_KEY configured, every one of those endpoints
still fully works — this is NEVER a hard requirement to run the app
locally or to exercise every other feature — but the CAPTCHA check
itself is skipped entirely (verify_captcha() always returns True). This
is the same "bring your own credentials, or it no-ops" shape as this
project's other optional integrations (Razorpay payments, VAPID push,
Google geocoding) — see services/payment.py for the pattern this
deliberately mirrors. A one-time startup warning makes the current mode
visible either way, so it's never a silent, easy-to-miss gap.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY")
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

IS_CONFIGURED = bool(RECAPTCHA_SECRET_KEY)

if not IS_CONFIGURED:
    logger.warning(
        "RECAPTCHA_SECRET_KEY is not set — CAPTCHA verification is running "
        "in no-op mode (every check passes automatically). Fine for local "
        "development; set RECAPTCHA_SECRET_KEY before relying on this for "
        "real bot protection. See services/captcha.py for details."
    )


def verify_captcha(token: str | None) -> bool:
    """
    True if the CAPTCHA check passes — which, in no-op mode (no secret
    key configured), is unconditionally True regardless of what `token`
    is, including None. Callers only need to branch on IS_CONFIGURED
    when deciding whether a MISSING token should itself be rejected
    (see routes/auth.py / routes/customer_auth.py: "captcha_token is
    required" is only enforced when a real check is actually possible).

    When actually configured, this calls Google's siteverify endpoint
    exactly as their docs specify: POST the secret + the widget's
    response token, trust only a JSON body with "success": true. Any
    network failure, timeout, or non-200 response is treated as a
    FAILED check, not silently passed — a CAPTCHA provider being
    unreachable is not a reason to let a request through unchecked.
    """
    if not IS_CONFIGURED:
        return True

    if not token:
        return False

    try:
        response = requests.post(
            RECAPTCHA_VERIFY_URL,
            data={"secret": RECAPTCHA_SECRET_KEY, "response": token},
            timeout=5,
        )
        response.raise_for_status()
        return bool(response.json().get("success"))
    except requests.RequestException:
        logger.warning("CAPTCHA verification request to Google failed — treating as failed check.")
        return False
