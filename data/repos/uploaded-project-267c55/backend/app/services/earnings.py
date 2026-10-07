"""
Computes (or recomputes) one EarningsStatementDB for a single user over
a single date range — see models/earnings.py for the two pay
components this combines and the idempotency/paid-statement rules.
"""

import uuid
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.attendance import AttendanceDB
from app.models.delivery_attempt import DeliveryAttemptDB
from app.models.earnings import EarningsStatementDB, EarningsStatus
from app.models.user import UserDB

COMPLETED_OUTCOMES = ("delivered", "partial_delivery")


def generate_statement_for_user(
    db: Session,
    user: UserDB,
    period_start: date,
    period_end: date,
) -> EarningsStatementDB:
    """
    Recomputes and upserts the draft/finalized statement for this user
    + period. If a statement for the exact same (user_id, period_start,
    period_end) already exists and is "paid", it's returned UNCHANGED —
    a paid statement is a closed book (see models/earnings.py). Any
    other existing statement for that period is overwritten in place
    rather than duplicated.
    """
    existing = db.query(EarningsStatementDB).filter(
        EarningsStatementDB.org_id == user.org_id,
        EarningsStatementDB.user_id == user.id,
        EarningsStatementDB.period_start == period_start,
        EarningsStatementDB.period_end == period_end,
    ).first()
    if existing and existing.status == EarningsStatus.paid:
        return existing

    # Attendance: sum hours from clocked-out sessions whose clock_in
    # falls inside the period. An open (still clocked-in) session isn't
    # counted — its hours aren't final yet.
    period_start_dt = datetime.combine(period_start, datetime.min.time())
    period_end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time())

    attendance_records = db.query(AttendanceDB).filter(
        AttendanceDB.org_id == user.org_id,
        AttendanceDB.user_id == user.id,
        AttendanceDB.clock_in_at >= period_start_dt,
        AttendanceDB.clock_in_at < period_end_dt,
        AttendanceDB.clock_out_at.isnot(None),
    ).all()
    total_seconds = sum(
        (a.clock_out_at - a.clock_in_at).total_seconds() for a in attendance_records
    )
    hours_worked = round(total_seconds / 3600.0, 2)

    # Deliveries: count real completed/partial attempts in the period.
    attempts = db.query(DeliveryAttemptDB).filter(
        DeliveryAttemptDB.org_id == user.org_id,
        DeliveryAttemptDB.agent_id == user.id,
        DeliveryAttemptDB.outcome.in_(COMPLETED_OUTCOMES),
        DeliveryAttemptDB.attempted_at >= period_start_dt,
        DeliveryAttemptDB.attempted_at < period_end_dt,
    ).count()

    hourly_rate = user.hourly_rate
    per_delivery_rate = user.per_delivery_rate
    base_pay = round(hours_worked * hourly_rate, 2) if hourly_rate else 0.0
    delivery_pay = round(attempts * per_delivery_rate, 2) if per_delivery_rate else 0.0
    total_pay = round(base_pay + delivery_pay, 2)

    if existing:
        statement = existing
    else:
        statement = EarningsStatementDB(
            id=str(uuid.uuid4()),
            org_id=user.org_id,
            user_id=user.id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(statement)

    statement.hours_worked = hours_worked
    statement.hourly_rate = hourly_rate
    statement.base_pay = base_pay
    statement.deliveries_completed = attempts
    statement.per_delivery_rate = per_delivery_rate
    statement.delivery_pay = delivery_pay
    statement.total_pay = total_pay
    statement.status = EarningsStatus.draft
    statement.generated_at = datetime.utcnow()

    db.commit()
    db.refresh(statement)
    return statement
