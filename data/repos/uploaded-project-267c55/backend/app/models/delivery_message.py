"""
Per-delivery messages — a simple chat/notes thread scoped to one
specific delivery. Distinct from the `notes` field on a delivery (a
single current-state note) and from the status history log (an
automatic audit trail) — this is an actual back-and-forth conversation
thread.

Phase 6 extends the original agent<->dispatcher thread to also include
the CUSTOMER as a participant — sender_role can now be "customer" in
addition to "agent"/"dispatcher"/"admin", with sender_id then being a
CustomerDB.id instead of a UserDB.id (there's no FK constraint either
way, consistent with how sender_id already worked before this phase).

read_by_staff_at / read_by_customer_at track read/unread state as two
separate timestamps rather than a single "read" flag, because staff is
a GROUP (any dispatcher/admin, or the assigned agent) while the
customer is a single person — "read by staff" means "seen by anyone
authorized to see this thread", set the first time any staff member's
GET request following this message runs; "read by customer" is the
same idea for the one customer on the order.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class DeliveryMessageDB(Base):
    __tablename__ = "delivery_messages"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, index=True, nullable=False)
    sender_id = Column(String, nullable=False)
    sender_display_name = Column(String, nullable=False)  # denormalized, same reasoning as delivery_history
    sender_role = Column(String, nullable=False)  # "agent", "dispatcher", "admin", or "customer" at time of sending
    message = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    read_by_staff_at = Column(DateTime, nullable=True)
    read_by_customer_at = Column(DateTime, nullable=True)


class MessageCreate(BaseModel):
    message: str


class MessageOut(BaseModel):
    id: str
    delivery_id: str
    sender_id: str
    sender_display_name: str
    sender_role: str
    message: str
    created_at: datetime
    read_by_staff_at: Optional[datetime] = None
    read_by_customer_at: Optional[datetime] = None

    class Config:
        from_attributes = True

