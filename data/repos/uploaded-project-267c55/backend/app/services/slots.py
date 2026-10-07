"""
Delivery time-slot generation: given an org's slot settings
(models/organization.py) and a target date, computes the list of
bookable time windows for that date - e.g. 9:00-11:00, 11:00-13:00,
... - and how many are already booked out of the org's per-slot cap.

Shared by the customer-facing "pick a delivery window" endpoint
(routes/slots.py) and checkout's own server-side validation
(routes/checkout.py) - the same function generates and validates
slots, so a slot the customer was shown as available can never
mismatch what checkout is willing to accept.
"""

from datetime import datetime, timedelta, date as date_cls
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.organization import OrganizationDB
from app.models.order import OrderDB, OrderStatus

MAX_ADVANCE_DAYS = 6  # customers can schedule up to 6 days out (today + 6 = a week's worth of options)


class SlotWindow:
    def __init__(self, start: datetime, end: datetime, remaining: int, capacity: int):
        self.start = start
        self.end = end
        self.remaining = remaining
        self.capacity = capacity

    @property
    def available(self) -> bool:
        return self.remaining > 0


def _slot_starts_for_date(org: OrganizationDB, target_date: date_cls) -> List[datetime]:
    duration = timedelta(minutes=org.slot_duration_minutes)
    cursor = datetime.combine(target_date, datetime.min.time()).replace(hour=org.slot_window_start_hour)
    window_end = datetime.combine(target_date, datetime.min.time()).replace(hour=org.slot_window_end_hour)
    starts = []
    while cursor + duration <= window_end:
        starts.append(cursor)
        cursor += duration
    return starts


def get_slots_for_date(db: Session, org: OrganizationDB, target_date: date_cls) -> List[SlotWindow]:
    """
    Every bookable slot for one date, with how many orders are already
    booked into each (so a full slot shows as unavailable rather than
    letting a store get overwhelmed with more orders in one window than
    it configured itself to handle).
    """
    now = datetime.utcnow()
    starts = _slot_starts_for_date(org, target_date)

    # Count existing PAID orders per slot_start for this org+date in one
    # query rather than one query per slot.
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    booked_orders = db.query(OrderDB.slot_start).filter(
        OrderDB.org_id == org.id,
        OrderDB.status == OrderStatus.paid,
        OrderDB.slot_start.isnot(None),
        OrderDB.slot_start >= day_start,
        OrderDB.slot_start < day_end,
    ).all()
    counts: dict = {}
    for (slot_start,) in booked_orders:
        counts[slot_start] = counts.get(slot_start, 0) + 1

    windows = []
    for start in starts:
        if start < now:
            continue  # don't offer slots that have already passed today
        booked = counts.get(start, 0)
        windows.append(SlotWindow(
            start=start,
            end=start + timedelta(minutes=org.slot_duration_minutes),
            remaining=max(org.max_orders_per_slot - booked, 0),
            capacity=org.max_orders_per_slot,
        ))
    return windows


def validate_slot(db: Session, org: OrganizationDB, slot_start: datetime) -> datetime:
    """
    Confirms a customer-submitted slot_start (from checkout) is a real,
    currently-available slot for this org - not just any arbitrary
    datetime the client felt like sending. Returns the matching slot's
    end time on success. Raises ValueError with a customer-facing
    message otherwise.
    """
    target_date = slot_start.date()
    if (target_date - datetime.utcnow().date()).days > MAX_ADVANCE_DAYS:
        raise ValueError(f"Delivery slots can only be booked up to {MAX_ADVANCE_DAYS} days in advance.")

    windows = get_slots_for_date(db, org, target_date)
    match = next((w for w in windows if w.start == slot_start), None)
    if not match:
        raise ValueError("That delivery slot isn't valid — please pick one of the available windows.")
    if not match.available:
        raise ValueError("That delivery slot just filled up — please pick another.")
    return match.end
