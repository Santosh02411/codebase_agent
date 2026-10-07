"""
Customer support (Phase 12) — tickets, threaded messages (customer +
staff), and staff-only internal notes, additive alongside the existing
delivery-specific chat (models/delivery_message.py, Phase 6). The two
are deliberately kept separate: delivery chat is a live, in-the-moment
channel between one customer and one agent about one delivery in
progress ("I'm arriving", "please share location"); a support ticket
is a longer-lived, dispatcher/admin-triaged issue that may reference an
order or delivery but isn't tied to one — a payment question or a
general complaint has no delivery to attach chat to.

Two tables:
  SupportTicketDB         — one row per ticket: category, priority,
                             status, optional order/delivery reference,
                             assignment, resolution.
  SupportTicketMessageDB  — the ticket's thread. `is_internal_note`
                             marks a staff-only note never returned to
                             the customer-facing endpoints.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class SupportTicketDB(Base):
    __tablename__ = "support_tickets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    customer_id = Column(String, index=True, nullable=False)

    order_id = Column(String, nullable=True)  # optional — a general account question has neither
    delivery_id = Column(String, nullable=True)  # set when this is a delivery dispute/complaint

    # "delivery_issue" | "order_issue" | "payment_issue" | "product_issue" | "account_issue" | "other"
    category = Column(String, nullable=False, default="other")
    # "low" | "normal" | "high" | "urgent"
    priority = Column(String, nullable=False, default="normal")
    # "open" | "in_progress" | "resolved" | "closed"
    status = Column(String, nullable=False, default="open")

    # A dispute is a specific kind of complaint — a customer contesting an
    # outcome (e.g. "I was charged but never received this"), tracked with
    # its own flag so it can be filtered/reported on separately from an
    # ordinary support question, without a whole second table.
    is_dispute = Column(Boolean, nullable=False, default=False)

    subject = Column(String, nullable=False)
    description = Column(String, nullable=False)

    assigned_to_user_id = Column(String, nullable=True)
    resolution_notes = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class SupportTicketMessageDB(Base):
    __tablename__ = "support_ticket_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    ticket_id = Column(String, index=True, nullable=False)

    sender_type = Column(String, nullable=False)  # "customer" | "staff"
    sender_id = Column(String, nullable=False)  # a CustomerDB.id or UserDB.id, per sender_type
    sender_display_name = Column(String, nullable=False)

    message = Column(String, nullable=False)
    attachment_url = Column(String, nullable=True)
    is_internal_note = Column(Boolean, nullable=False, default=False)  # staff-only; never shown to the customer

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class SupportTicketCreate(BaseModel):
    subject: str
    description: str
    category: str = "other"
    order_id: Optional[str] = None
    delivery_id: Optional[str] = None
    is_dispute: bool = False


class SupportTicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to_user_id: Optional[str] = None


class SupportTicketResolve(BaseModel):
    resolution_notes: str


class SupportTicketOut(BaseModel):
    id: str
    org_id: str
    customer_id: str
    order_id: Optional[str] = None
    delivery_id: Optional[str] = None
    category: str
    priority: str
    status: str
    is_dispute: bool
    subject: str
    description: str
    assigned_to_user_id: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketMessageCreate(BaseModel):
    message: str
    attachment_url: Optional[str] = None
    is_internal_note: bool = False  # ignored (forced False) on the customer-facing endpoint


class TicketMessageOut(BaseModel):
    id: str
    ticket_id: str
    sender_type: str
    sender_id: str
    sender_display_name: str
    message: str
    attachment_url: Optional[str] = None
    is_internal_note: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TicketAttachmentUploadOut(BaseModel):
    attachment_url: str
