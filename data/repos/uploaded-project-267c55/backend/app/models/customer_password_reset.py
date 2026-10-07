"""
Password reset tokens for CUSTOMER accounts — the self-service
"forgot password" flow for the customer-facing app.

Kept as its own table, separate from PasswordResetTokenDB (staff), for
the same reason customer auth already lives in its own routes/models
files: CustomerDB and UserDB are two entirely separate identity
systems (see routes/customer_auth.py's docstring), and a shared token
table would need a discriminator column to avoid a customer's token id
ever accidentally validating against a staff user id or vice versa.
Keeping them apart makes that mix-up structurally impossible instead
of merely policy-enforced.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base

RESET_TOKEN_EXPIRY_MINUTES = 30


class CustomerPasswordResetTokenDB(Base):
    __tablename__ = "customer_password_reset_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES),
    )
    used = Column(Boolean, nullable=False, default=False)


class CustomerForgotPasswordRequest(BaseModel):
    email: str
    captcha_token: Optional[str] = None


class CustomerResetPasswordRequest(BaseModel):
    token: str
    new_password: str
