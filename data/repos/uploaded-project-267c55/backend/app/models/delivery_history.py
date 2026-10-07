"""
DeliveryHistoryDB — an audit log recording every status change made to a
delivery: who changed it, from what status to what, and when.

Design note: `changed_by_display_name` is deliberately stored directly on
each history row (denormalized) rather than only storing a user ID and
joining at read time. This keeps history entries permanently readable even
if a user's display name changes later, or in edge cases — history is a
record of what happened at the time, not a live-updating reference.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class DeliveryHistoryDB(Base):
    __tablename__ = "delivery_history"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, index=True, nullable=False)
    changed_by_user_id = Column(String, nullable=False)
    changed_by_display_name = Column(String, nullable=False)
    old_status = Column(String, nullable=True)  # null for the very first "created" entry
    new_status = Column(String, nullable=False)
    changed_at = Column(DateTime, nullable=False)
    note = Column(String, nullable=True)  # e.g. "Created and assigned", or the delivery note at that time


class DeliveryHistoryOut(BaseModel):
    id: str
    delivery_id: str
    changed_by_display_name: str
    old_status: Optional[str] = None
    new_status: str
    changed_at: datetime
    note: Optional[str] = None

    class Config:
        from_attributes = True
