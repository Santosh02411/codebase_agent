"""
Proof of Delivery (POD) — Phase 1 of the missing-features build-out.

Two tables:

1. `ProofOfDeliveryDB` — the actual proof captured for a delivery
   attempt: who received it, how it was verified, signature/photo,
   GPS at the moment of capture, and free-text notes. A delivery can
   have more than one POD row over its life (a failed attempt doesn't
   get one; but a delivery that was reattempted and delivered on the
   second try only ever needs one — this exists as its own table
   rather than columns on DeliveryRecordDB mainly so "POD history" is
   a free byproduct of the schema, not something bolted on later).

2. `DeliveryOtpDB` — short-lived hashed OTP codes used for the
   optional "recipient verification" requirement, mirroring
   `models/email_otp.py`'s shape/reasoning exactly (own table, hashed
   code, expiry, single-use).

Whether any of this is REQUIRED before a delivery can be marked
`delivered` is controlled per-organization by the pod_* columns added
to OrganizationDB (see models/organization.py) — see services/pod.py
for the enforcement logic itself, and routes/deliveries.py's
update_delivery() for where it's actually checked.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base

DELIVERY_OTP_EXPIRY_MINUTES = 15


# ---------- Database Tables ----------

class ProofOfDeliveryDB(Base):
    __tablename__ = "proof_of_delivery"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, index=True, nullable=False)

    # Denormalized, same reasoning as everywhere else in this project:
    # every query filtering PODs is scoped by org_id directly, rather
    # than joining back to deliveries just to check tenant ownership.
    org_id = Column(String, index=True, nullable=False)

    agent_id = Column(String, nullable=True)

    recipient_name = Column(String, nullable=True)
    recipient_phone = Column(String, nullable=True)

    # True only if an OTP was actually generated AND correctly entered
    # for this capture (see services/pod.py:verify_delivery_otp). False
    # (not null) when OTP verification isn't in use for this delivery,
    # so "was this recipient OTP-verified" is always a plain boolean
    # read, never a three-state null check.
    otp_verified = Column(Boolean, nullable=False, default=False)

    # Base64 data URLs, same storage approach as the pre-existing
    # DeliveryRecordDB.proof_of_delivery field (see that column's
    # docstring for the disclosed no-object-storage-budget rationale).
    signature_data_url = Column(String, nullable=True)
    photo_data_url = Column(String, nullable=True)

    latitude = Column(String, nullable=True)
    longitude = Column(String, nullable=True)

    notes = Column(String, nullable=True)

    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Set true when this POD was captured while the agent's device was
    # offline (IndexedDB queue) and only reached the server later via a
    # background retry — see frontend services/podOfflineQueue.js. Purely
    # informational (shown as a small badge in the POD viewer); doesn't
    # change validation.
    captured_offline = Column(Boolean, nullable=False, default=False)


class DeliveryOtpDB(Base):
    __tablename__ = "delivery_otp_codes"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    channel = Column(String, nullable=False, default="none")  # "email" | "sms" | "none" (no contact info on file)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=DELIVERY_OTP_EXPIRY_MINUTES),
    )
    used = Column(Boolean, nullable=False, default=False)


# ---------- Pydantic Schemas ----------

class DeliveryOtpGenerateOut(BaseModel):
    """
    Deliberately never returns the code itself — only where it went
    (masked) and whether it went anywhere at all. Mirrors the
    email-2FA flow's mask_email() reasoning in models/email_otp.py.
    """
    sent: bool
    channel: str  # "email" | "sms" | "none"
    destination_hint: Optional[str] = None  # e.g. "m***y@example.com" or "+91 9****21098"
    expires_in_minutes: int = DELIVERY_OTP_EXPIRY_MINUTES


class ProofOfDeliverySubmit(BaseModel):
    recipient_name: Optional[str] = None
    recipient_phone: Optional[str] = None
    otp_code: Optional[str] = None
    signature_data_url: Optional[str] = None
    photo_data_url: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    notes: Optional[str] = None
    captured_at: Optional[datetime] = None
    captured_offline: bool = False


class ProofOfDeliveryOut(BaseModel):
    id: str
    delivery_id: str
    agent_id: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_phone: Optional[str] = None
    otp_verified: bool = False
    signature_data_url: Optional[str] = None
    photo_data_url: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    notes: Optional[str] = None
    captured_at: datetime
    captured_offline: bool = False

    class Config:
        from_attributes = True


class PodSettingsOut(BaseModel):
    pod_require_recipient_name: bool = False
    pod_require_signature_or_photo: bool = False
    pod_require_otp: bool = False
    pod_require_gps: bool = False

    class Config:
        from_attributes = True


class PodSettingsUpdate(BaseModel):
    pod_require_recipient_name: bool
    pod_require_signature_or_photo: bool
    pod_require_otp: bool
    pod_require_gps: bool
