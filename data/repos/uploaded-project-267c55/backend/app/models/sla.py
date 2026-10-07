"""
SLAPolicyDB — an org's delivery-time targets (Phase 2).

A policy can be scoped to a specific zone, delivery_type, and/or
priority, or left as the org-wide default (all three null). When a
delivery is assigned, services/sla.py picks the SINGLE best-matching
active policy for that org, using specificity as the tiebreaker
(zone+type+priority match beats zone+priority beats zone-only beats
the org-wide default) — see `select_policy_for_delivery` there.

target_minutes is measured from the delivery's `created_at` (when it
entered the system) — the simplest, least-ambiguous anchor point, and
consistent regardless of whether a delivery started as a customer
checkout or a dispatcher-created record.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class SLAPolicyDB(Base):
    __tablename__ = "sla_policies"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)

    # All three nullable — null means "matches any value for this
    # dimension". A policy with all three null is the org-wide default.
    zone = Column(String, nullable=True)
    delivery_type = Column(String, nullable=True)
    priority = Column(String, nullable=True)

    target_minutes = Column(Integer, nullable=False)

    # Percentage of target_minutes elapsed at which a delivery flips
    # from "on_track" to "at_risk" (near-breach warning) — e.g. 80 means
    # the warning fires once 80% of the allotted time has passed.
    warning_threshold_percent = Column(Integer, nullable=False, default=80)

    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class SLAPolicyCreate(BaseModel):
    name: str
    zone: Optional[str] = None
    delivery_type: Optional[str] = None
    priority: Optional[str] = None
    target_minutes: int = Field(gt=0)
    warning_threshold_percent: int = Field(default=80, ge=1, le=99)


class SLAPolicyUpdate(BaseModel):
    name: Optional[str] = None
    zone: Optional[str] = None
    delivery_type: Optional[str] = None
    priority: Optional[str] = None
    target_minutes: Optional[int] = Field(default=None, gt=0)
    warning_threshold_percent: Optional[int] = Field(default=None, ge=1, le=99)
    active: Optional[bool] = None


class SLAPolicyOut(BaseModel):
    id: str
    org_id: str
    name: str
    zone: Optional[str] = None
    delivery_type: Optional[str] = None
    priority: Optional[str] = None
    target_minutes: int
    warning_threshold_percent: int
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
