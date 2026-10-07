"""
Email verification tokens for STAFF accounts (UserDB) — a link-based,
single-use token emailed at signup (and on request via
POST /auth/resend-verification) to confirm the address actually
belongs to whoever signed up. Structurally identical to
PasswordResetTokenDB (models/password_reset.py) on purpose — same
"separate table so a fresh request invalidates checking an old link"
shape — but kept as its own table since it verifies a different claim
(this inbox exists and is reachable) with a different, longer expiry.

Verifying an email does NOT gate login — see routes/auth.py's
/verify-email docstring for the reasoning. This exists so the account
carries a real, checkable record of whether its contact address was
ever confirmed, and so the frontend can nudge an unverified user
without blocking them outright.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base

VERIFICATION_TOKEN_EXPIRY_HOURS = 48


class EmailVerificationTokenDB(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS),
    )
    used = Column(Boolean, nullable=False, default=False)


class VerifyEmailRequest(BaseModel):
    token: str
