"""
ActionLogDB — a general-purpose admin audit trail: who did what to
which record, and when, across the admin-facing parts of the app that
AREN'T delivery status changes (those already have their own dedicated
log — see models/delivery_history.py and routes/admin.py's existing
/admin/audit-log endpoint).

This covers the other admin write actions: user management (deactivate/
reactivate/password reset), product create/update/delete, coupon
create/update/delete, and store settings changes (visibility, pricing,
slot settings, profile). Anywhere an admin (or dispatcher, for product/
coupon management) changes something org-wide and another admin might
later need to answer "who did this, and when" — this is that record.

Design choices mirror delivery_history.py's, deliberately, for
consistency:
- `actor_display_name` is denormalized (stored directly on the row, not
  just as a user ID to join at read time) so entries stay readable even
  if a user's display name or account changes later.
- `changes` stores a small JSON object of {field: {"from": ..., "to":
  ...}} for update actions — enough to answer "what changed" without
  needing a full before/after snapshot. Null for create/delete actions
  where the whole record is the "change".
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class ActionLogDB(Base):
    __tablename__ = "action_log"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    actor_user_id = Column(String, nullable=False)
    actor_display_name = Column(String, nullable=False)
    action = Column(String, nullable=False)  # e.g. "product.create", "user.deactivate"
    entity_type = Column(String, nullable=False)  # e.g. "product", "user", "coupon", "store_settings"
    entity_id = Column(String, nullable=True)
    entity_label = Column(String, nullable=True)  # human-readable, e.g. product name or user display name
    summary = Column(String, nullable=False)  # short one-line description of what happened
    changes = Column(Text, nullable=True)  # JSON string: {"field": {"from": x, "to": y}, ...}
    created_at = Column(DateTime, nullable=False)


class ActionLogOut(BaseModel):
    id: str
    actor_display_name: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    entity_label: Optional[str] = None
    summary: str
    changes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
