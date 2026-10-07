"""
Public API & Webhooks (Phase 14) — external integration layer.

Two independent concerns sharing this module:

  ApiKeyDB           — lets a THIRD PARTY authenticate against this
                        project's external `/api/v1/...` surface
                        without a staff username/password. Scoped
                        (deliveries:read, orders:read, ...) rather than
                        all-or-nothing, and the raw key is shown to the
                        org admin exactly ONCE at creation/rotation
                        time — only its SHA-256 hash and a short
                        `key_prefix` (for admin-UI identification) are
                        ever stored, the same "never store the
                        recoverable secret" principle as password
                        hashing elsewhere in this project, just with a
                        fast deterministic hash instead of bcrypt since
                        API keys are already high-entropy random
                        tokens with nothing to brute-force via a rainbow
                        table.

  WebhookDB /
  WebhookDeliveryDB   — lets an org's OWN server be notified when
                        things happen here (a delivery went out, an
                        order was paid). Each subscription's `secret`
                        IS shown back to the org's own admin on every
                        read (unlike an API key) — it's not a bearer
                        credential granting access to this API, it's a
                        shared secret the org's own receiving endpoint
                        needs on hand to verify the HMAC signature on
                        incoming webhook POSTs.
"""

import hashlib
import secrets
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, Integer
from pydantic import BaseModel
from typing import Optional, List

from app.db.session import Base

API_SCOPES = {"deliveries:read", "deliveries:write", "orders:read", "webhooks:manage"}

WEBHOOK_EVENTS = {
    "delivery.created", "delivery.assigned", "delivery.picked_up",
    "delivery.out_for_delivery", "delivery.delivered", "delivery.failed",
    "order.created", "order.paid", "order.cancelled",
    "refund.created", "return.created",
}


class ApiKeyDB(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)

    name = Column(String, nullable=False)
    key_prefix = Column(String, nullable=False)  # first 8 chars of the raw key, shown in the admin UI to identify which key is which
    hashed_key = Column(String, index=True, nullable=False)  # sha256(raw key) — the raw key itself is never stored

    scopes = Column(String, nullable=False, default="")  # comma-separated subset of API_SCOPES

    is_active = Column(Boolean, nullable=False, default=True)
    created_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class WebhookDB(Base):
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)

    url = Column(String, nullable=False)
    secret = Column(String, nullable=False)  # used to HMAC-sign every delivery's payload
    subscribed_events = Column(String, nullable=False, default="")  # comma-separated subset of WEBHOOK_EVENTS

    is_active = Column(Boolean, nullable=False, default=True)
    created_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WebhookDeliveryDB(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    webhook_id = Column(String, index=True, nullable=False)

    event_type = Column(String, nullable=False)
    payload_json = Column(String, nullable=False)  # the exact JSON body sent (or that will be sent)

    # "pending" (awaiting first attempt or a scheduled retry) | "success" | "failed" (attempts exhausted)
    status = Column(String, nullable=False, default="pending")
    response_status_code = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempted_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)  # None once status is success/failed

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def generate_api_key() -> tuple:
    """Returns (raw_key, key_prefix, hashed_key). Called once at creation/rotation time — the raw_key is returned to the caller and never persisted."""
    raw_key = f"dsk_{secrets.token_urlsafe(32)}"  # "dsk_" = Delivery Sync Key, a recognizable prefix like real API key formats (sk_, pk_, etc.)
    return raw_key, raw_key[:8], hash_api_key(raw_key)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


# ---------- Pydantic Schemas ----------

class ApiKeyCreate(BaseModel):
    name: str
    scopes: List[str]


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApiKeyCreatedOut(ApiKeyOut):
    raw_key: str  # ONLY ever present in the response to the create/rotate call itself


class WebhookCreate(BaseModel):
    url: str
    subscribed_events: List[str]


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    subscribed_events: Optional[List[str]] = None
    is_active: Optional[bool] = None


class WebhookOut(BaseModel):
    id: str
    url: str
    secret: str
    subscribed_events: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookDeliveryOut(BaseModel):
    id: str
    webhook_id: str
    event_type: str
    status: str
    response_status_code: Optional[int] = None
    attempt_count: int
    last_attempted_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
