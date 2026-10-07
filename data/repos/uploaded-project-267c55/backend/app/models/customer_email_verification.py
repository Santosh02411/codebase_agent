"""
Email verification tokens for CUSTOMER accounts — mirrors
models/email_verification.py's staff version exactly. Kept as its own
table for the same reason customer_password_reset.py is separate from
password_reset.py: CustomerDB and UserDB are two entirely different
identity systems in this project, so a shared token table would need a
discriminator column to prevent a customer's token ever validating
against a staff account or vice versa. Keeping them apart makes that
mix-up structurally impossible instead of merely policy-enforced.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base

VERIFICATION_TOKEN_EXPIRY_HOURS = 48


class CustomerEmailVerificationTokenDB(Base):
    __tablename__ = "customer_email_verification_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS),
    )
    used = Column(Boolean, nullable=False, default=False)


class CustomerVerifyEmailRequest(BaseModel):
    token: str
