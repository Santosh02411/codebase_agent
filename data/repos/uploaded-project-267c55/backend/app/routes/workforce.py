"""
Workforce management — Group 3: shifts (the roster plan), attendance
(actual clock-in/out), leave requests (time-off approval workflow), and
earnings (computed pay statements). See models/shift.py,
models/attendance.py, models/leave_request.py, and models/earnings.py
for the design reasoning behind each.

All endpoints are org-scoped. "Self" endpoints (clock in/out, my
shifts, my leave requests, my earnings) are open to any authenticated
staff member for their OWN records; roster/approval/generation
endpoints are dispatcher/admin-only, matching the same split this
project already uses elsewhere (e.g. a delivery's assigned agent can
act on their own delivery; only a dispatcher/admin manages the queue).
"""

import uuid
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.shift import ShiftDB, ShiftStatus, ShiftCreate, ShiftUpdate, ShiftOut
from app.models.attendance import AttendanceDB, ClockInRequest, ClockOutRequest, AttendanceOut
from app.models.leave_request import LeaveRequestDB, LeaveStatus, LeaveRequestCreate, LeaveReviewRequest, LeaveRequestOut
from app.models.earnings import EarningsStatementDB, EarningsStatus, EarningsGenerateRequest, EarningsStatementOut
from app.models.user import UserDB, UserRole, PayRateUpdate, UserOut
from app.routes.auth import get_current_user
from app.services.earnings import generate_statement_for_user

router = APIRouter(prefix="/workforce", tags=["workforce"])


def require_dispatcher_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


def _get_org_user_or_404(db: Session, user_id: str, org_id: str) -> UserDB:
    user = db.query(UserDB).filter(UserDB.id == user_id, UserDB.org_id == org_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found in this organization.")
    return user


# =========================================================================
# Shifts
# =========================================================================

@router.post("/shifts", response_model=ShiftOut)
def create_shift(
    payload: ShiftCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    _get_org_user_or_404(db, payload.user_id, current_user.org_id)
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="Shift end time must be after start time.")

    shift = ShiftDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        user_id=payload.user_id,
        shift_date=payload.shift_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        notes=payload.notes,
        status=ShiftStatus.scheduled,
        created_by_user_id=current_user.id,
        created_at=datetime.utcnow(),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("/shifts", response_model=List[ShiftOut])
def list_shifts(
    user_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    """The full org roster, dispatcher/admin-only, optionally filtered by staff member and/or date range."""
    query = db.query(ShiftDB).filter(ShiftDB.org_id == current_user.org_id)
    if user_id:
        query = query.filter(ShiftDB.user_id == user_id)
    if date_from:
        query = query.filter(ShiftDB.shift_date >= date_from)
    if date_to:
        query = query.filter(ShiftDB.shift_date <= date_to)
    return query.order_by(ShiftDB.shift_date.asc(), ShiftDB.start_time.asc()).all()


@router.get("/shifts/mine", response_model=List[ShiftOut])
def list_my_shifts(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    query = db.query(ShiftDB).filter(
        ShiftDB.org_id == current_user.org_id,
        ShiftDB.user_id == current_user.id,
    )
    if date_from:
        query = query.filter(ShiftDB.shift_date >= date_from)
    if date_to:
        query = query.filter(ShiftDB.shift_date <= date_to)
    return query.order_by(ShiftDB.shift_date.asc(), ShiftDB.start_time.asc()).all()


@router.patch("/shifts/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: str,
    payload: ShiftUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    shift = db.query(ShiftDB).filter(ShiftDB.id == shift_id, ShiftDB.org_id == current_user.org_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found.")

    if payload.shift_date is not None:
        shift.shift_date = payload.shift_date
    if payload.start_time is not None:
        shift.start_time = payload.start_time
    if payload.end_time is not None:
        shift.end_time = payload.end_time
    if payload.notes is not None:
        shift.notes = payload.notes
    if payload.status is not None:
        shift.status = payload.status

    if shift.end_time <= shift.start_time:
        raise HTTPException(status_code=400, detail="Shift end time must be after start time.")

    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/shifts/{shift_id}")
def delete_shift(
    shift_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    shift = db.query(ShiftDB).filter(ShiftDB.id == shift_id, ShiftDB.org_id == current_user.org_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found.")
    db.delete(shift)
    db.commit()
    return {"message": "Shift deleted."}


# =========================================================================
# Attendance
# =========================================================================

@router.post("/attendance/clock-in", response_model=AttendanceOut)
def clock_in(
    payload: ClockInRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Any staff member clocks themselves in. Rejected if they already
    have an open (not-yet-clocked-out) session — see AttendanceDB's
    docstring for why this is checked here rather than via a DB
    constraint.
    """
    open_session = db.query(AttendanceDB).filter(
        AttendanceDB.org_id == current_user.org_id,
        AttendanceDB.user_id == current_user.id,
        AttendanceDB.clock_out_at.is_(None),
    ).first()
    if open_session:
        raise HTTPException(status_code=400, detail="You're already clocked in — clock out first.")

    is_unscheduled = True
    if payload.shift_id:
        shift = db.query(ShiftDB).filter(
            ShiftDB.id == payload.shift_id,
            ShiftDB.org_id == current_user.org_id,
            ShiftDB.user_id == current_user.id,
        ).first()
        if not shift:
            raise HTTPException(status_code=400, detail="That shift doesn't exist or isn't assigned to you.")
        is_unscheduled = False

    record = AttendanceDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        user_id=current_user.id,
        shift_id=payload.shift_id,
        clock_in_at=datetime.utcnow(),
        clock_in_note=payload.note,
        is_unscheduled=is_unscheduled,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/attendance/clock-out", response_model=AttendanceOut)
def clock_out(
    payload: ClockOutRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    open_session = db.query(AttendanceDB).filter(
        AttendanceDB.org_id == current_user.org_id,
        AttendanceDB.user_id == current_user.id,
        AttendanceDB.clock_out_at.is_(None),
    ).first()
    if not open_session:
        raise HTTPException(status_code=400, detail="You're not currently clocked in.")

    open_session.clock_out_at = datetime.utcnow()
    open_session.clock_out_note = payload.note

    if open_session.shift_id:
        shift = db.query(ShiftDB).filter(ShiftDB.id == open_session.shift_id).first()
        if shift and shift.status == ShiftStatus.scheduled:
            shift.status = ShiftStatus.completed

    db.commit()
    db.refresh(open_session)
    return open_session


@router.get("/attendance/mine", response_model=List[AttendanceOut])
def list_my_attendance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    query = db.query(AttendanceDB).filter(
        AttendanceDB.org_id == current_user.org_id,
        AttendanceDB.user_id == current_user.id,
    )
    if date_from:
        query = query.filter(AttendanceDB.clock_in_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AttendanceDB.clock_in_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return query.order_by(AttendanceDB.clock_in_at.desc()).all()


@router.get("/attendance", response_model=List[AttendanceOut])
def list_attendance(
    user_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    query = db.query(AttendanceDB).filter(AttendanceDB.org_id == current_user.org_id)
    if user_id:
        query = query.filter(AttendanceDB.user_id == user_id)
    if date_from:
        query = query.filter(AttendanceDB.clock_in_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AttendanceDB.clock_in_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return query.order_by(AttendanceDB.clock_in_at.desc()).all()


# =========================================================================
# Leave requests
# =========================================================================

@router.post("/leave-requests", response_model=LeaveRequestOut)
def create_leave_request(
    payload: LeaveRequestCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date can't be before start date.")

    request = LeaveRequestDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        user_id=current_user.id,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
        status=LeaveStatus.pending,
        created_at=datetime.utcnow(),
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@router.get("/leave-requests/mine", response_model=List[LeaveRequestOut])
def list_my_leave_requests(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return db.query(LeaveRequestDB).filter(
        LeaveRequestDB.org_id == current_user.org_id,
        LeaveRequestDB.user_id == current_user.id,
    ).order_by(LeaveRequestDB.created_at.desc()).all()


@router.post("/leave-requests/{request_id}/cancel", response_model=LeaveRequestOut)
def cancel_my_leave_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """The requester withdraws their own still-pending request."""
    request = db.query(LeaveRequestDB).filter(
        LeaveRequestDB.id == request_id,
        LeaveRequestDB.org_id == current_user.org_id,
        LeaveRequestDB.user_id == current_user.id,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    if request.status != LeaveStatus.pending:
        raise HTTPException(status_code=400, detail=f"Can't cancel a request that's already {request.status.value}.")

    request.status = LeaveStatus.cancelled
    db.commit()
    db.refresh(request)
    return request


@router.get("/leave-requests", response_model=List[LeaveRequestOut])
def list_leave_requests(
    status: Optional[LeaveStatus] = None,
    user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    query = db.query(LeaveRequestDB).filter(LeaveRequestDB.org_id == current_user.org_id)
    if status:
        query = query.filter(LeaveRequestDB.status == status)
    if user_id:
        query = query.filter(LeaveRequestDB.user_id == user_id)
    return query.order_by(LeaveRequestDB.created_at.desc()).all()


def _review_leave_request(db: Session, request_id: str, org_id: str, reviewer: UserDB, new_status: LeaveStatus, note: Optional[str]) -> LeaveRequestDB:
    request = db.query(LeaveRequestDB).filter(LeaveRequestDB.id == request_id, LeaveRequestDB.org_id == org_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    if request.status != LeaveStatus.pending:
        raise HTTPException(status_code=400, detail=f"This request was already {request.status.value}.")

    request.status = new_status
    request.reviewed_by_user_id = reviewer.id
    request.review_note = note
    request.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(request)
    return request


@router.post("/leave-requests/{request_id}/approve", response_model=LeaveRequestOut)
def approve_leave_request(
    request_id: str,
    payload: LeaveReviewRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    return _review_leave_request(db, request_id, current_user.org_id, current_user, LeaveStatus.approved, payload.review_note)


@router.post("/leave-requests/{request_id}/reject", response_model=LeaveRequestOut)
def reject_leave_request(
    request_id: str,
    payload: LeaveReviewRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    return _review_leave_request(db, request_id, current_user.org_id, current_user, LeaveStatus.rejected, payload.review_note)


# =========================================================================
# Pay rates
# =========================================================================

@router.patch("/pay-rate/{user_id}", response_model=UserOut)
def set_pay_rate(
    user_id: str,
    payload: PayRateUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    """
    Admin/dispatcher sets a staff member's hourly and/or per-delivery
    rate. Uses `model_fields_set` (not just "is not None") so a field
    genuinely OMITTED from the request body is left unchanged, while a
    field explicitly sent as null clears that rate.
    """
    user = _get_org_user_or_404(db, user_id, current_user.org_id)
    fields_sent = payload.model_fields_set
    if "hourly_rate" in fields_sent:
        user.hourly_rate = payload.hourly_rate
    if "per_delivery_rate" in fields_sent:
        user.per_delivery_rate = payload.per_delivery_rate
    db.commit()
    db.refresh(user)
    return user


# =========================================================================
# Earnings
# =========================================================================

@router.post("/earnings/generate", response_model=List[EarningsStatementOut])
def generate_earnings(
    payload: EarningsGenerateRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="Period end can't be before period start.")

    if payload.user_id:
        users = [_get_org_user_or_404(db, payload.user_id, current_user.org_id)]
    else:
        users = db.query(UserDB).filter(UserDB.org_id == current_user.org_id).all()

    return [
        generate_statement_for_user(db, user, payload.period_start, payload.period_end)
        for user in users
    ]


@router.get("/earnings/mine", response_model=List[EarningsStatementOut])
def list_my_earnings(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return db.query(EarningsStatementDB).filter(
        EarningsStatementDB.org_id == current_user.org_id,
        EarningsStatementDB.user_id == current_user.id,
    ).order_by(EarningsStatementDB.period_start.desc()).all()


@router.get("/earnings", response_model=List[EarningsStatementOut])
def list_earnings(
    user_id: Optional[str] = None,
    status: Optional[EarningsStatus] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    query = db.query(EarningsStatementDB).filter(EarningsStatementDB.org_id == current_user.org_id)
    if user_id:
        query = query.filter(EarningsStatementDB.user_id == user_id)
    if status:
        query = query.filter(EarningsStatementDB.status == status)
    return query.order_by(EarningsStatementDB.period_start.desc()).all()


@router.post("/earnings/{statement_id}/finalize", response_model=EarningsStatementOut)
def finalize_earnings(
    statement_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    statement = db.query(EarningsStatementDB).filter(
        EarningsStatementDB.id == statement_id, EarningsStatementDB.org_id == current_user.org_id
    ).first()
    if not statement:
        raise HTTPException(status_code=404, detail="Earnings statement not found.")
    if statement.status != EarningsStatus.draft:
        raise HTTPException(status_code=400, detail=f"Statement is already {statement.status.value}.")
    statement.status = EarningsStatus.finalized
    db.commit()
    db.refresh(statement)
    return statement


@router.post("/earnings/{statement_id}/mark-paid", response_model=EarningsStatementOut)
def mark_earnings_paid(
    statement_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    """
    Marks a finalized statement paid — a draft can't be marked paid
    directly, since finalizing first is what freezes it against being
    silently recomputed by a later /earnings/generate call for the same
    period (see services/earnings.py).
    """
    statement = db.query(EarningsStatementDB).filter(
        EarningsStatementDB.id == statement_id, EarningsStatementDB.org_id == current_user.org_id
    ).first()
    if not statement:
        raise HTTPException(status_code=404, detail="Earnings statement not found.")
    if statement.status != EarningsStatus.finalized:
        raise HTTPException(status_code=400, detail="Only a finalized statement can be marked paid.")
    statement.status = EarningsStatus.paid
    statement.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(statement)
    return statement
