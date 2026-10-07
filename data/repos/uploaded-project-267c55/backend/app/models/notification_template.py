"""
Notification templates (Phase 10) — lets an org customize the wording
of customer-facing notifications per event type, and toggle which
channels (email/SMS/WhatsApp/in-app) fire for each. Additive: the
EXISTING hardcoded notify_customer_of_status_change() is left
completely untouched (it's exercised by a large slice of the existing
test suite; rewriting it would be high-risk for little benefit). This
system powers the genuinely NEW notification events this phase adds:
refund_processed, return_approved, agent_nearby, delivery_reminder,
subscription_reminder — see services/notification_templates.py.

One NotificationTemplateDB row per (org, event_type) that an admin has
customized; an event type with no row uses the built-in
DEFAULT_TEMPLATES text — an org that never visits the template editor
sees sensible default behavior, not silence.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base

EVENT_TYPES = [
    "refund_processed",
    "return_approved",
    "agent_nearby",
    "delivery_reminder",
    "subscription_reminder",
]

# {event_type: (default_subject, default_body)} — body supports
# {order_id} as the only placeholder (kept deliberately simple; no
# templating engine dependency for one substitution).
DEFAULT_TEMPLATES = {
    "refund_processed": ("Your refund has been processed", "Your refund for order {order_id} has been processed."),
    "return_approved": ("Your return has been approved", "Your return for order {order_id} has been approved. We'll pick up the item soon."),
    "agent_nearby": ("Your delivery is almost here", "Your delivery agent is nearby for order {order_id}."),
    "delivery_reminder": ("Upcoming delivery reminder", "Reminder: order {order_id} is scheduled for delivery soon."),
    "subscription_reminder": ("Your subscription renews soon", "Your subscription order will be placed again soon. Visit your account to make changes before then."),
}


class NotificationTemplateDB(Base):
    __tablename__ = "notification_templates"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    event_type = Column(String, nullable=False)

    subject = Column(String, nullable=False)
    body = Column(String, nullable=False)

    email_enabled = Column(Boolean, nullable=False, default=True)
    sms_enabled = Column(Boolean, nullable=False, default=False)
    whatsapp_enabled = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class NotificationTemplateUpsert(BaseModel):
    subject: str
    body: str
    email_enabled: bool = True
    sms_enabled: bool = False
    whatsapp_enabled: bool = False


class NotificationTemplateOut(BaseModel):
    event_type: str
    subject: str
    body: str
    email_enabled: bool
    sms_enabled: bool
    whatsapp_enabled: bool
    is_default: bool = False

    class Config:
        from_attributes = True
