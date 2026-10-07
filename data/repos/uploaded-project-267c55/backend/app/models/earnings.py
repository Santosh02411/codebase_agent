"""
EarningsStatementDB — a computed pay statement for one staff member
over one date range, generated on demand by an admin (see
services/earnings.py) rather than continuously accrued. Combines two
pay components, each optional depending on what rates are set on the
user (UserDB.hourly_rate / UserDB.per_delivery_rate, see
models/user.py):

- Hours worked, summed from AttendanceDB records (clocked-out only —
  an open/in-progress session isn't counted yet) that fall inside the
  period, times hourly_rate.
- Deliveries completed, counted from DeliveryAttemptDB rows (see
  models/delivery_attempt.py) with outcome delivered OR
  partial_delivery that fall inside the period, times
  per_delivery_rate. A failed_attempt earns nothing — only a real
  completed (or partial) delivery does.

Generating a statement is idempotent per (user, period): regenerating
for the same range recomputes and overwrites the existing draft rather
than creating a duplicate, but a statement already marked "paid" is
left alone (see routes/workforce.py) — a paid statement is a closed
book, not something a later recompute should silently rewrite.
"""

import enum
import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, Date, DateTime, Float, Integer, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class EarningsStatus(str, enum.Enum):
    draft = "draft"
    finalized = "finalized"
    paid = "paid"


class EarningsStatementDB(Base):
    __tablename__ = "earnings_statements"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    hours_worked = Column(Float, nullable=False, default=0.0)
    hourly_rate = Column(Float, nullable=True)
    base_pay = Column(Float, nullable=False, default=0.0)

    deliveries_completed = Column(Integer, nullable=False, default=0)
    per_delivery_rate = Column(Float, nullable=True)
    delivery_pay = Column(Float, nullable=False, default=0.0)

    total_pay = Column(Float, nullable=False, default=0.0)
    status = Column(SqlEnum(EarningsStatus), nullable=False, default=EarningsStatus.draft)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


# ---------- Pydantic Schemas ----------

class EarningsGenerateRequest(BaseModel):
    user_id: Optional[str] = None  # omit to generate for every staff member in the org
    period_start: date
    period_end: date


class EarningsStatementOut(BaseModel):
    id: str
    user_id: str
    period_start: date
    period_end: date
    hours_worked: float
    hourly_rate: Optional[float] = None
    base_pay: float
    deliveries_completed: int
    per_delivery_rate: Optional[float] = None
    delivery_pay: float
    total_pay: float
    status: EarningsStatus
    generated_at: datetime
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True
