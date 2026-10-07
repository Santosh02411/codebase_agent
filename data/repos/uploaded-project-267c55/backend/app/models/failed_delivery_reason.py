"""
Failed-delivery reason codes — an org-managed list of standardized
reasons an agent picks from when marking a delivery attempt failed
(e.g. "Customer unavailable", "Wrong address", "Refused by customer").

Admin-managed (CRUD under /admin/failed-delivery-reasons, see
routes/failed_delivery_reasons.py), org-scoped like everything
multi-tenant in this project. This is ENFORCED, not just offered: see
routes/deliveries.py's update_delivery() — a failed_attempt status
update is rejected without a valid, active reason_code_id, so the
delivery-attempts log (models/delivery_attempt.py) always records a
real, standardized reason rather than free-text guesswork someone has
to interpret later. (The offline sync path, routes/sync.py, does NOT
hard-enforce this the same way — see that file's comment for why.)

`active` lets an org retire a reason code without breaking historical
attempts that already reference it (soft-delete, the same pattern used
elsewhere in this project) — deactivating just hides it from the
picker and blocks new attempts from using it; rows that already
reference it keep working.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class FailedDeliveryReasonDB(Base):
    __tablename__ = "failed_delivery_reasons"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    code = Column(String, nullable=False)  # short machine-ish token, e.g. "CUSTOMER_UNAVAILABLE"
    label = Column(String, nullable=False)  # human-readable, e.g. "Customer unavailable"
    description = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # RTO (Phase 7): reasons an agent can never resolve by reattempting
    # (e.g. "Wrong address", "Refused by customer") get flagged here so
    # a SINGLE failed attempt with this reason makes the delivery
    # RTO-eligible immediately, instead of waiting for the org's
    # attempt-count threshold (OrganizationDB.rto_max_attempts) to be
    # reached — see services/rto.py's check_rto_eligibility().
    eligible_for_rto = Column(Boolean, nullable=False, default=False)


# ---------- Pydantic Schemas ----------

class FailedDeliveryReasonCreate(BaseModel):
    code: str
    label: str
    description: Optional[str] = None
    eligible_for_rto: bool = False


class FailedDeliveryReasonUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    eligible_for_rto: Optional[bool] = None


class FailedDeliveryReasonOut(BaseModel):
    id: str
    code: str
    label: str
    description: Optional[str] = None
    active: bool
    eligible_for_rto: bool = False

    class Config:
        from_attributes = True
