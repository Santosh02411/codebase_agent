"""
Return-to-Origin (RTO) management (Phase 7) — for a FORWARD delivery
that couldn't be completed and needs to come back to the org, as
distinct from a return_request (models/return_request.py), which is
for an order the customer already RECEIVED and wants to send back.
Integrated with, not duplicating, the existing failed-delivery system:
an RtoRequestDB row is created automatically the moment a delivery
becomes RTO-eligible (see services/rto.py's check_rto_eligibility(),
called from services/delivery_attempts.py right after every
failed_attempt is logged — the ONE place every failed-attempt path in
this project already funnels through).

Status lifecycle: eligible -> approved -> in_transit -> received_at_origin
                              \\-> cancelled (dispatcher decides to reattempt instead)

Deliberately does NOT create a second DeliveryRecordDB the way a
return_pickup does — the agent who failed to deliver typically still
has the package in hand, so there's no separate "pickup" leg to model;
"in_transit" here just means "the agent is bringing it back", tracked
on this row directly rather than via a parallel delivery record.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class RtoStatus(str, enum.Enum):
    eligible = "eligible"
    approved = "approved"
    in_transit = "in_transit"
    received_at_origin = "received_at_origin"
    cancelled = "cancelled"


class RtoRequestDB(Base):
    __tablename__ = "rto_requests"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    delivery_id = Column(String, index=True, nullable=False, unique=True)  # one active RTO per delivery
    order_id = Column(String, nullable=True)
    customer_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)

    reason_code_id = Column(String, nullable=True)
    reason_label = Column(String, nullable=True)  # denormalized, same reasoning as delivery_attempt's reason_label

    status = Column(SqlEnum(RtoStatus), nullable=False, default=RtoStatus.eligible)

    refund_issued = Column(Boolean, nullable=False, default=False)
    resolution_note = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    in_transit_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


# ---------- Pydantic Schemas ----------

class RtoApproveIn(BaseModel):
    note: Optional[str] = None


class RtoCancelIn(BaseModel):
    note: Optional[str] = None


class RtoRequestOut(BaseModel):
    id: str
    delivery_id: str
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    agent_id: Optional[str] = None
    reason_code_id: Optional[str] = None
    reason_label: Optional[str] = None
    status: RtoStatus
    refund_issued: bool
    resolution_note: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    in_transit_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True
