"""
Short-lived, single-use 6-digit codes emailed to a user for the
"email code" second-factor method — the alternative to an authenticator
app for staff who'd rather not install one. Mirrors
models/password_reset.py's shape (its own table, expiry, used flag) for
the same reason: a user could trigger several of these in a row (a resend,
or a second login attempt), and only the one actually entered should work.

Codes are stored hashed (via the same passlib hasher already used for
passwords), not in plaintext — a 6-digit code is inherently low-entropy,
so hashing it is a cheap extra guard against anyone with raw DB access
being able to log in as someone else during that code's short window.
"""

import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean

from app.db.session import Base

EMAIL_OTP_EXPIRY_MINUTES = 10


class EmailOtpDB(Base):
    __tablename__ = "email_otp_codes"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    purpose = Column(String, nullable=False)  # "enable_2fa" or "login"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=EMAIL_OTP_EXPIRY_MINUTES),
    )
    used = Column(Boolean, nullable=False, default=False)


def generate_numeric_code() -> str:
    """A random 6-digit code, zero-padded (e.g. '004821') so it's always exactly 6 characters."""
    return f"{random.randint(0, 999999):06d}"


def mask_email(email: str) -> str:
    """'monty@example.com' -> 'm***y@example.com' — enough for a user to recognize their own inbox without fully exposing it in an API response."""
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked_local = local[0] + "*" * max(len(local) - 1, 1)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}" if domain else masked_local
