"""
DeliveryRecord model.

This file defines TWO things, which is a common FastAPI pattern:
1. `DeliveryRecordDB`  -> the actual database table (SQLAlchemy)
2. Pydantic schemas    -> what data looks like coming in/out of the API

Keeping these separate means the API can validate/shape data independently
of how it's stored in the database.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean, Enum as SqlEnum
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class DeliveryStatus(str, enum.Enum):
    pending = "pending"  # placed via checkout, not yet assigned to an agent
    picked_up = "picked_up"
    out_for_delivery = "out_for_delivery"
    delivered = "delivered"
    failed_attempt = "failed_attempt"
    cancelled = "cancelled"


class DeliveryPriority(str, enum.Enum):
    """
    Dispatcher queue priority. Deliberately a plain String column below
    (not a SqlEnum like `status`) — SQLAlchemy's Enum type renders a
    CHECK constraint baked with whatever values existed when a table
    was first created, and this project's lightweight migration system
    (db/migrate.py) only ever ADDs columns, it never touches an
    existing CHECK constraint. A plain String avoids that trap entirely
    (same reasoning `delivery_type` above already follows) while still
    getting real validation via this enum at the Pydantic layer.
    """
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


# Higher number = more urgent = sorts first in the dispatcher queue.
PRIORITY_RANK = {
    DeliveryPriority.urgent.value: 3,
    DeliveryPriority.high.value: 2,
    DeliveryPriority.normal.value: 1,
    DeliveryPriority.low.value: 0,
}


# ---------- Database Table ----------

class DeliveryRecordDB(Base):
    __tablename__ = "deliveries"

    id = Column(String, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=True)
    order_id = Column(String, index=True, nullable=False)
    status = Column(SqlEnum(DeliveryStatus), nullable=False)
    notes = Column(String, nullable=True)
    location_note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Added for route batching: a free-text zone/area name (e.g. "Sector 5",
    # "Koramangala") lets deliveries be grouped without needing a paid
    # geocoding API. Latitude/longitude are optional — if a dispatcher
    # knows them, the agent's route can additionally be ordered via a
    # nearest-neighbor heuristic; deliveries without coordinates still work
    # fine, just grouped by zone rather than precisely ordered.
    zone = Column(String, nullable=True)
    latitude = Column(String, nullable=True)
    longitude = Column(String, nullable=True)

    # Added for delivery time estimates: an optional deadline the
    # dispatcher sets when assigning. Nullable — not every delivery needs
    # a hard deadline.
    expected_by = Column(DateTime, nullable=True)

    # Delivery time-slot the CUSTOMER picked at checkout (see
    # routes/slots.py, routes/checkout.py) — distinct from expected_by
    # above, which is a dispatcher-set deadline on an already-placed
    # delivery. Both nullable: a dispatcher-created manual delivery has
    # neither, and a customer checkout without picking a slot (ASAP
    # delivery) has neither either.
    slot_start = Column(DateTime, nullable=True)
    slot_end = Column(DateTime, nullable=True)

    # Phase 10: set once an upcoming-delivery reminder has been sent
    # for this slot — see services/reminder_scheduler.py. Left null
    # forever for a delivery with no slot at all (nothing to remind
    # about).
    reminder_sent_at = Column(DateTime, nullable=True)

    # Multi-tenant scoping: every delivery belongs to exactly one
    # organization (inherited from the dispatcher who created it). All
    # queries elsewhere filter by this so two organizations never see
    # each other's deliveries.
    org_id = Column(String, index=True, nullable=False)

    # Proof of delivery: a base64 data URL (signature drawn on a canvas,
    # or a photo taken/uploaded), captured when the agent marks a
    # delivery "Delivered". Stored directly in the database as text —
    # there's no budget for cloud file storage (S3, etc.) in this
    # project, so this is a disclosed, demo-appropriate simplification.
    # A production system would upload to real object storage and store
    # a URL here instead of the raw image data itself.
    proof_of_delivery = Column(String, nullable=True)

    # Customer contact info, used to send status-change notifications
    # (see services/notifications.py). Both optional — a delivery can
    # have neither, either, or both; notifications simply aren't sent
    # for whichever channel has no contact info.
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # If a real customer account (CustomerDB) exists matching
    # customer_email, this gets set — that's what makes the delivery show
    # up in that customer's dashboard, not just via a one-off tracking
    # link. Nullable: plenty of deliveries won't have a matching customer
    # account, and that's fine — they're still trackable via the public
    # link, just not tied to a logged-in dashboard.
    customer_id = Column(String, nullable=True, index=True)

    # "delivery" (default — a normal forward delivery to the customer)
    # or "return_pickup" (an agent collecting an item BACK from the
    # customer, created when a return/exchange request is approved —
    # see models/return_request.py). A return_pickup flows through the
    # exact same pending -> picked_up -> delivered status lifecycle as
    # a normal delivery; "delivered" for one of these means "brought
    # back to the store", which is what triggers the return/exchange to
    # complete (see routes/deliveries.py's update_delivery).
    delivery_type = Column(String, nullable=False, default="delivery")

    # Dispatcher-queue priority — see DeliveryPriority above for why
    # this is a plain string rather than a SqlEnum. Settable at
    # creation and editable afterward via PATCH /deliveries/{id}/priority.
    priority = Column(String, nullable=False, default=DeliveryPriority.normal.value)

    # How many real delivery ATTEMPTS (delivered/failed_attempt/
    # partial_delivery outcomes) this delivery has had — see
    # services/delivery_attempts.py and models/delivery_attempt.py.
    # Kept denormalized here (rather than always COUNT()-ing the
    # delivery_attempts table) so it's a free read alongside the
    # delivery record itself, e.g. for a dispatcher table column.
    attempt_count = Column(Integer, nullable=False, default=0)

    # Reschedule workflow: set by POST /deliveries/{id}/reschedule
    # after a failed attempt. `rescheduled_to` is the new promised
    # date/window; `reschedule_reason` is why (e.g. "customer asked
    # for tomorrow"); `reschedule_count` tracks how many times this
    # has happened, since a delivery rescheduled 4 times is a real
    # operational signal worth surfacing to a dispatcher.
    rescheduled_to = Column(DateTime, nullable=True)
    reschedule_reason = Column(String, nullable=True)
    reschedule_count = Column(Integer, nullable=False, default=0)

    # Partial-delivery marking: set when an agent marks a delivery
    # "Delivered" but not everything ordered was actually handed over
    # (e.g. one item out of stock on the vehicle, or the customer only
    # accepted part of the order). Status stays `delivered` — a
    # partial delivery IS a completed attempt, not a failure — this
    # flag + notes just record that it wasn't 100% complete, for
    # whoever needs to follow up (refund the missing item, redeliver
    # it, etc.).
    is_partial = Column(Boolean, nullable=False, default=False)
    partial_notes = Column(String, nullable=True)

    # SLA tracking (Phase 2) — see models/sla.py and services/sla.py.
    # sla_policy_id: which SLAPolicyDB matched at assignment time (kept
    # even if that policy is later edited/deactivated, so a delivery's
    # deadline doesn't retroactively move under it).
    # sla_target_at: the computed deadline itself. Null means either no
    # matching policy exists for this org, or the delivery hasn't been
    # assigned yet (deadlines are computed from assignment time).
    # sla_status: "not_applicable" (no policy/deadline) | "on_track" |
    # "at_risk" (near-breach warning fired) | "breached" (deadline
    # passed, still not delivered) | "met" (delivered by the deadline) |
    # "missed" (delivered after the deadline). A plain String, not a
    # SqlEnum — same CHECK-constraint-migration trap `priority` above
    # already avoids.
    sla_policy_id = Column(String, nullable=True)
    sla_target_at = Column(DateTime, nullable=True)
    sla_status = Column(String, nullable=False, default="not_applicable")
    sla_breach_notified = Column(Boolean, nullable=False, default=False)


# ---------- Pydantic Schemas (API request/response shapes) ----------

class DeliveryRecordCreate(BaseModel):
    """Shape expected when creating a new delivery record."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    order_id: str
    status: DeliveryStatus
    notes: Optional[str] = None
    location_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    zone: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    expected_by: Optional[datetime] = None
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    priority: Optional[DeliveryPriority] = DeliveryPriority.normal


class ClaimOrderRequest(BaseModel):
    """
    Shape for a customer manually linking an order to their account when
    it wasn't auto-linked at creation time (e.g. the dispatcher typed a
    different email than the one the customer signed up with). Verified
    with the order's phone number rather than trusting order_id alone —
    order_id is a dispatcher-chosen business reference, not guaranteed
    globally unique or secret, so it can't be the only proof of ownership.
    """
    order_id: str
    phone: str


class DeliveryRecordUpdate(BaseModel):
    """Shape expected when updating an existing delivery record's status."""
    status: DeliveryStatus
    notes: Optional[str] = None
    location_note: Optional[str] = None
    updated_at: datetime
    proof_of_delivery: Optional[str] = None

    # Required (enforced server-side, see update_delivery()) when
    # status == failed_attempt — must reference an active
    # FailedDeliveryReasonDB row belonging to the caller's org.
    reason_code_id: Optional[str] = None

    # Only meaningful when status == delivered — see
    # DeliveryRecordDB.is_partial above for what this means.
    is_partial: bool = False
    partial_notes: Optional[str] = None


class DeliveryRecordOut(BaseModel):
    """Shape returned by the API to clients."""
    id: str
    agent_id: Optional[str] = None
    order_id: str
    status: DeliveryStatus
    notes: Optional[str] = None
    location_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    zone: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    expected_by: Optional[datetime] = None
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    org_id: str
    proof_of_delivery: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_id: Optional[str] = None
    delivery_type: str = "delivery"
    priority: str = DeliveryPriority.normal.value
    attempt_count: int = 0
    rescheduled_to: Optional[datetime] = None
    reschedule_reason: Optional[str] = None
    reschedule_count: int = 0
    is_partial: bool = False
    partial_notes: Optional[str] = None
    sla_target_at: Optional[datetime] = None
    sla_status: str = "not_applicable"

    class Config:
        from_attributes = True  # allows conversion from SQLAlchemy objects
