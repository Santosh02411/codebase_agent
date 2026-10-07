"""
Recurring / subscription orders.

Design (matches the "manual confirm & pay each cycle" decision, not
auto-billing): a SubscriptionDB is a saved cart-shape (items + address +
payment preference + a custom N-day interval) that the scheduler
(services/subscription_scheduler.py) turns into a real, ordinary
OrderDB row — status=pending_payment, subscription_id set — the moment
it's due. Nothing is ever charged automatically. The customer sees a
"ready to reorder" in-app notification + a banner in their Subscriptions
view, and pays it via the existing checkout payment machinery
(routes/subscriptions.py's initiate-payment endpoint + the existing,
unchanged POST /customer/checkout/verify). If they never pay, that
cycle's order just sits pending_payment forever — same as an abandoned
cart checkout today — and the NEXT cycle still fires on schedule,
because next_run_date always advances by interval_days when a cycle
runs, regardless of whether the previous cycle's order got paid.

Deliberately scoped to ONE store (org_id), same as CartItemDB — a
subscription is "reorder this from this store every N days", not a
cross-store bundle.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Enum as SqlEnum
from pydantic import BaseModel
from typing import Optional, List

from app.db.session import Base


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    cancelled = "cancelled"


class SubscriptionDB(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    status = Column(SqlEnum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.active)

    interval_days = Column(Integer, nullable=False)  # custom N-day cadence, admin/coupon-free — just "every N days"
    next_run_date = Column(DateTime, nullable=False, index=True)

    address_line = Column(String, nullable=False)
    city = Column(String, nullable=True)
    phone = Column(String, nullable=False)
    payment_method = Column(String, nullable=False, default="online")  # "online" or "cod" — same meaning as OrderDB
    coupon_code = Column(String, nullable=True)  # re-validated fresh against each generated order; silently dropped if no longer valid

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    paused_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    # Phase 10: set once a pre-renewal reminder has been sent for the
    # CURRENT next_run_date, so the reminder scan never double-sends.
    # Cleared back to null whenever next_run_date advances (see
    # services/subscription_scheduler.py's run_subscription_cycle) so
    # each new cycle gets its own fresh reminder.
    reminder_sent_at = Column(DateTime, nullable=True)


class SubscriptionItemDB(Base):
    __tablename__ = "subscription_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id = Column(String, index=True, nullable=False)
    product_id = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)


# ---- Pydantic schemas ----

class SubscriptionItemIn(BaseModel):
    product_id: str
    quantity: int = 1


class SubscriptionItemOut(BaseModel):
    product_id: str
    quantity: int
    # Denormalized at read time (see routes/subscriptions.py) so the
    # frontend can show a name/price without a second round trip - not
    # stored, since unlike an OrderItem this should always reflect the
    # product's CURRENT price/name, not a snapshot from when the
    # subscription was created.
    product_name: Optional[str] = None
    unit_price: Optional[float] = None

    class Config:
        from_attributes = True


class SubscriptionCreate(BaseModel):
    org_id: str
    items: List[SubscriptionItemIn]
    interval_days: int
    address_line: str
    city: Optional[str] = None
    phone: str
    payment_method: str = "online"
    coupon_code: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    items: Optional[List[SubscriptionItemIn]] = None
    interval_days: Optional[int] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    payment_method: Optional[str] = None
    coupon_code: Optional[str] = None


class SubscriptionOut(BaseModel):
    id: str
    org_id: str
    status: SubscriptionStatus
    interval_days: int
    next_run_date: datetime
    address_line: str
    city: Optional[str] = None
    phone: str
    payment_method: str
    coupon_code: Optional[str] = None
    created_at: datetime
    items: List[SubscriptionItemOut] = []
    # Set only when a generated order from this subscription is still
    # awaiting payment - lets the frontend show a "Confirm & Pay" banner
    # without a separate lookup.
    pending_order_id: Optional[str] = None
    pending_order_total: Optional[float] = None

    class Config:
        from_attributes = True
