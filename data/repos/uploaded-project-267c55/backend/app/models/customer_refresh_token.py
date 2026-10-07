"""
Refresh tokens for CUSTOMER sessions — mirrors models/refresh_token.py's
staff version exactly (same hashing, rotation, and theft-detection
design — see that file's docstring for the full reasoning). Kept as
its own table for the same reason every other customer-vs-staff token
table in this project is split: CustomerDB and UserDB are separate
identity systems, and a shared table would need a discriminator column
to prevent a customer's refresh token from ever being redeemable
against a staff session or vice versa.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base

REFRESH_TOKEN_EXPIRE_DAYS = 30


class CustomerRefreshTokenDB(Base):
    __tablename__ = "customer_refresh_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    used = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_id = Column(String, nullable=True)


class CustomerRefreshTokenRequest(BaseModel):
    refresh_token: str


class CustomerRefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
