"""
Return/exchange requests — for a DELIVERED order the customer wants to
send back (wrong item, damaged, changed their mind) or swap for a
replacement. Deliberately a completely separate concept from
cancellation (services/refund.py, routes/customer_dashboard.py's cancel
endpoint): cancellation is for an order that hasn't been delivered yet;
a return/exchange is for one that already has been. Conflating the two
would mean a "cancel" on an already-in-the-customer's-hands order,
which doesn't make sense — the item has to physically come back first.

The pickup itself reuses the EXISTING delivery/agent/dispatcher
infrastructure rather than building parallel plumbing: approving a
return request creates a real DeliveryRecordDB (see models/delivery.py)
with delivery_type="return_pickup" — it shows up in the dispatcher's
unassigned queue exactly like a normal delivery, gets assigned to an
agent, and goes through the same picked_up -> delivered status flow
(here, "delivered" means "brought back to the store", not "delivered to
the customer"). When that pickup delivery reaches "delivered", this
request auto-completes: a return triggers a real refund (reusing
services/refund.py's refund_order_for_delivery against the ORIGINAL
delivery/order — untouched status-wise, only its refund_status changes),
an exchange creates a brand new forward delivery for the replacement.
See routes/deliveries.py's update_delivery for where that hook lives.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class ReturnRequestType(str, enum.Enum):
    return_ = "return"
    exchange = "exchange"


class ReturnRequestStatus(str, enum.Enum):
    requested = "requested"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"


class ReturnRequestDB(Base):
    __tablename__ = "return_requests"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String, index=True, nullable=False)
    delivery_id = Column(String, index=True, nullable=False)  # the ORIGINAL forward delivery being returned/exchanged
    customer_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)

    request_type = Column(SqlEnum(ReturnRequestType), nullable=False)
    reason = Column(String, nullable=False)
    status = Column(SqlEnum(ReturnRequestStatus), nullable=False, default=ReturnRequestStatus.requested)

    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(String, nullable=True)  # dispatcher/admin's note on approval or rejection

    # Set once approved: the new return_pickup DeliveryRecordDB created
    # for an agent to go collect the item.
    pickup_delivery_id = Column(String, nullable=True)

    # Set once completed, ONLY for request_type=exchange: the new
    # forward DeliveryRecordDB created for the replacement item.
    exchange_delivery_id = Column(String, nullable=True)


# ---------- Pydantic Schemas ----------

class ReturnRequestCreate(BaseModel):
    delivery_id: str
    request_type: ReturnRequestType
    reason: str


class ReturnRequestResolve(BaseModel):
    resolution_note: Optional[str] = None


class ReturnRequestOut(BaseModel):
    id: str
    order_id: str
    delivery_id: str
    request_type: ReturnRequestType
    reason: str
    status: ReturnRequestStatus
    requested_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    pickup_delivery_id: Optional[str] = None
    exchange_delivery_id: Optional[str] = None

    class Config:
        from_attributes = True
