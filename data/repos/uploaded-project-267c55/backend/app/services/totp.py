"""
TOTP (Time-based One-Time Password) helpers for staff two-factor
authentication — RFC 6238, the same standard behind Google Authenticator,
Authy, 1Password, etc. Free and self-contained (no SMS/email provider
needed, unlike this project's other 2FA-adjacent flows like password
reset), which is why it was picked over an SMS-code approach for a
zero-budget project.

Uses the `pyotp` library. A 30-second time step and 6-digit codes are
pyotp's defaults and match every standard authenticator app, so nothing
is configured beyond that.
"""

import pyotp

ISSUER_NAME = "Delivery Sync"


def generate_secret() -> str:
    """A new random base32 secret, unique per user, stored on UserDB.totp_secret."""
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, account_name: str) -> str:
    """
    The otpauth:// URI an authenticator app scans (as a QR code) to add
    this account. Includes the issuer name so the entry in the user's
    authenticator app is clearly labeled "Delivery Sync", not just a
    bare username among dozens of other accounts.
    """
    return pyotp.totp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=ISSUER_NAME)


def verify_code(secret: str, code: str) -> bool:
    """
    Checks a 6-digit code against the secret. valid_window=1 accepts the
    previous and next 30-second time step too, a standard, small amount
    of clock-drift tolerance — without it, users get spuriously rejected
    codes if their phone's clock is even a few seconds off from the
    server's.
    """
    if not code or not code.isdigit():
        return False
    return pyotp.totp.TOTP(secret).verify(code, valid_window=1)
