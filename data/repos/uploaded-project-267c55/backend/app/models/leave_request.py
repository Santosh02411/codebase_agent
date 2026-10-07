"""
LeaveRequestDB — a staff member requesting time off, with a
dispatcher/admin approval workflow. Deliberately simple: a leave
request doesn't automatically cancel or block shift creation for its
dates (a dispatcher reviewing the request is expected to notice the
overlap themselves via GET /workforce/shifts filtered by user/date) —
adding hard scheduling-conflict enforcement is more machinery than
this project's scope calls for, and would need to define what
"conflict" means for a partial-day leave request, which adds
complexity without a corresponding real requirement here.
"""

import enum
import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, Date, DateTime, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class LeaveType(str, enum.Enum):
    sick = "sick"
    vacation = "vacation"
    personal = "personal"
    unpaid = "unpaid"


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"  # withdrawn by the requester before review


class LeaveRequestDB(Base):
    __tablename__ = "leave_requests"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    leave_type = Column(SqlEnum(LeaveType), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(SqlEnum(LeaveStatus), nullable=False, default=LeaveStatus.pending)
    reviewed_by_user_id = Column(String, nullable=True)
    review_note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


# ---------- Pydantic Schemas ----------

class LeaveRequestCreate(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: Optional[str] = None


class LeaveReviewRequest(BaseModel):
    review_note: Optional[str] = None


class LeaveRequestOut(BaseModel):
    id: str
    user_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: Optional[str] = None
    status: LeaveStatus
    reviewed_by_user_id: Optional[str] = None
    review_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
