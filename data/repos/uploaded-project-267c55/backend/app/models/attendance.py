"""
AttendanceDB — the actual record of a staff member clocking in and
(later) clocking out, as opposed to ShiftDB (models/shift.py) which is
just the plan. `shift_id` links back to a scheduled shift when one
exists, but is nullable: someone can clock in with no shift scheduled
(an unscheduled/ad-hoc work session) — that's allowed, just flagged as
`is_unscheduled` for a dispatcher reviewing the log.

Only one OPEN attendance record (clock_out_at IS NULL) is allowed per
user at a time — enforced in routes/workforce.py's clock-in endpoint,
not here, since SQLite has no easy partial-unique-index shortcut in
this project's lightweight migration setup, and hand-checking on write
is simple enough at this scale.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class AttendanceDB(Base):
    __tablename__ = "attendance_records"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    shift_id = Column(String, nullable=True)
    clock_in_at = Column(DateTime, nullable=False)
    clock_out_at = Column(DateTime, nullable=True)
    clock_in_note = Column(String, nullable=True)
    clock_out_note = Column(String, nullable=True)
    is_unscheduled = Column(Boolean, nullable=False, default=False)


# ---------- Pydantic Schemas ----------

class ClockInRequest(BaseModel):
    shift_id: Optional[str] = None
    note: Optional[str] = None


class ClockOutRequest(BaseModel):
    note: Optional[str] = None


class AttendanceOut(BaseModel):
    id: str
    user_id: str
    shift_id: Optional[str] = None
    clock_in_at: datetime
    clock_out_at: Optional[datetime] = None
    clock_in_note: Optional[str] = None
    clock_out_note: Optional[str] = None
    is_unscheduled: bool

    class Config:
        from_attributes = True
