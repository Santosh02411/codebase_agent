"""
Password reset tokens — a short-lived, single-use token generated when
someone requests a password reset, verified when they submit a new
password. Kept in its own table (rather than, say, a field on UserDB)
since a user could request a reset multiple times, and only the token
actually used should ever work.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base

RESET_TOKEN_EXPIRY_MINUTES = 30


class PasswordResetTokenDB(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES),
    )
    used = Column(Boolean, nullable=False, default=False)


class ForgotPasswordRequest(BaseModel):
    email: str
    captcha_token: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
