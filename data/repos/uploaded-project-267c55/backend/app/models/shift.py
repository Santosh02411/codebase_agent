"""
ShiftDB — a scheduled work period for a staff member (agent, dispatcher,
or admin), created by a dispatcher/admin as part of the org's roster.

A shift is a PLAN ("Priya is scheduled 9am-5pm on the 12th"), distinct
from AttendanceDB (models/attendance.py) which is the ACTUAL record of
when someone really clocked in/out — the two are linked via
AttendanceDB.shift_id (nullable, since someone can clock in without a
scheduled shift) so a dispatcher can compare planned vs. actual.

`status` tracks the shift's own lifecycle independent of attendance:
"scheduled" until its date passes, then a background/manual sweep (see
routes/workforce.py's mark-shift-outcomes helper, called when
attendance is fetched for a date) reconciles it to "completed" (an
attendance record with a clock_out exists) or "missed" (none does).
"cancelled" is set explicitly by a dispatcher/admin before the fact.
"""

import enum
import uuid
from datetime import datetime, date, time

from sqlalchemy import Column, String, Date, Time, DateTime, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class ShiftStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    missed = "missed"
    cancelled = "cancelled"


class ShiftDB(Base):
    __tablename__ = "shifts"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    shift_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    notes = Column(String, nullable=True)
    status = Column(SqlEnum(ShiftStatus), nullable=False, default=ShiftStatus.scheduled)
    created_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class ShiftCreate(BaseModel):
    user_id: str
    shift_date: date
    start_time: time
    end_time: time
    notes: Optional[str] = None


class ShiftUpdate(BaseModel):
    shift_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    notes: Optional[str] = None
    status: Optional[ShiftStatus] = None


class ShiftOut(BaseModel):
    id: str
    user_id: str
    shift_date: date
    start_time: time
    end_time: time
    notes: Optional[str] = None
    status: ShiftStatus
    created_at: datetime

    class Config:
        from_attributes = True
