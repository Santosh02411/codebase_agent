"""
DeliveryAttemptDB — a log of every actual delivery ATTEMPT: an agent
reaching (or trying to reach) a customer, and the outcome that
resulted — delivered, failed_attempt, or partial_delivery.

Distinct from DeliveryHistoryDB (which logs every status change of any
kind, including dispatcher actions like assignment or a bulk
reassignment). An "attempt" specifically means the agent physically
tried to complete the delivery and something happened — so a
dispatcher assigning or reassigning a delivery, or setting its
priority, does NOT create an attempt row, only a history row.

`reason_label` is denormalized from FailedDeliveryReasonDB at the time
of the attempt (same reasoning as DeliveryHistoryDB's
changed_by_display_name) so an attempt stays readable even if a reason
code is later renamed or deactivated.

`attempt_number` is a per-delivery running count (1st attempt, 2nd
attempt, ...), tracked via DeliveryRecordDB.attempt_count — this is
what makes "how many times has this delivery actually been attempted"
a simple, always-correct read instead of a COUNT() query scattered
across call sites.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class DeliveryAttemptDB(Base):
    __tablename__ = "delivery_attempts"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    delivery_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, nullable=True)
    attempt_number = Column(Integer, nullable=False)
    outcome = Column(String, nullable=False)  # "delivered" | "failed_attempt" | "partial_delivery"
    reason_code_id = Column(String, nullable=True)
    reason_label = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    attempted_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class DeliveryAttemptOut(BaseModel):
    id: str
    delivery_id: str
    agent_id: Optional[str] = None
    attempt_number: int
    outcome: str
    reason_code_id: Optional[str] = None
    reason_label: Optional[str] = None
    notes: Optional[str] = None
    attempted_at: datetime

    class Config:
        from_attributes = True
