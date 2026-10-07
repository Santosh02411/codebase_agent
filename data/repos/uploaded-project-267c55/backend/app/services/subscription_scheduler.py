"""
Turns a due SubscriptionDB into a real OrderDB row (pending_payment,
subscription_id set), on the same pricing formula as a normal cart
checkout (routes/checkout.py) — subtotal -> coupon discount -> tax ->
delivery fee -> total. Nothing is charged here; see
models/subscription.py's module docstring for the full "manual confirm
& pay each cycle" design this implements.

Two ways this runs:
  1. `run_subscription_cycle(db)` — called by the background loop
     (`start_subscription_scheduler`, wired up in main.py's startup
     event) on a fixed interval, for every subscription actually due.
  2. `generate_order_for_subscription(db, subscription)` directly —
     called by routes/subscriptions.py's "run now" endpoint, so the
     feature is demoable/testable without waiting for the interval to
     elapse.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.subscription import SubscriptionDB, SubscriptionItemDB, SubscriptionStatus
from app.models.product import ProductDB
from app.models.organization import OrganizationDB
from app.models.order import OrderDB, OrderItemDB, OrderStatus
from app.services.coupons import find_and_validate_coupon, compute_discount, CouponError
from app.services.inventory import check_stock_available, InsufficientStockError
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

# How often the background loop checks for due subscriptions. Kept short
# (relative to realistic interval_days values, which are always >= 1 day)
# so a subscription created or edited mid-demo doesn't need an app
# restart to be picked up, and so "run now" isn't the only practical way
# to see this feature work end-to-end.
SCHEDULER_INTERVAL_SECONDS = 60


def generate_order_for_subscription(db: Session, subscription: SubscriptionDB) -> OrderDB | None:
    """
    Build one OrderDB (+ OrderItemDB rows) for this subscription's
    current items, at today's prices/stock. Returns None (and leaves the
    subscription otherwise untouched) if every item is currently
    unavailable — there's nothing useful to charge for. The caller is
    responsible for advancing next_run_date; this function only builds
    the order.
    """
    items = db.query(SubscriptionItemDB).filter(SubscriptionItemDB.subscription_id == subscription.id).all()

    subtotal = 0.0
    line_snapshots = []
    for item in items:
        product = db.query(ProductDB).filter(
            ProductDB.id == item.product_id,
            ProductDB.org_id == subscription.org_id,
            ProductDB.is_active == True,  # noqa: E712
        ).first()
        if not product:
            continue
        try:
            check_stock_available(db, product.id, item.quantity)
        except InsufficientStockError:
            continue  # skip just this item this cycle rather than failing the whole order
        subtotal += product.price * item.quantity
        line_snapshots.append((product, item.quantity))

    if not line_snapshots:
        return None

    subtotal = round(subtotal, 2)

    discount_amount = 0.0
    coupon_code_to_store = None
    if subscription.coupon_code:
        try:
            coupon = find_and_validate_coupon(db, subscription.org_id, subscription.coupon_code, subtotal)
            discount_amount = compute_discount(coupon, subtotal)
            coupon_code_to_store = coupon.code
        except CouponError:
            pass  # coupon no longer valid (expired/used up) - order still goes out, just without the discount

    org = db.query(OrganizationDB).filter(OrganizationDB.id == subscription.org_id).first()
    delivery_fee = org.delivery_fee if org else 0.0
    tax_rate_percent = org.tax_rate_percent if org else 0.0

    taxable_amount = max(round(subtotal - discount_amount, 2), 0.0)
    tax_amount = round(taxable_amount * (tax_rate_percent / 100.0), 2)
    total = round(taxable_amount + tax_amount + delivery_fee, 2)

    order = OrderDB(
        id=str(uuid.uuid4()),
        customer_id=subscription.customer_id,
        org_id=subscription.org_id,
        status=OrderStatus.pending_payment,
        payment_method=subscription.payment_method,
        address_line=subscription.address_line,
        city=subscription.city,
        phone=subscription.phone,
        subtotal=subtotal,
        coupon_code=coupon_code_to_store,
        discount_amount=discount_amount,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        total=total,
        subscription_id=subscription.id,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()

    for product, quantity in line_snapshots:
        db.add(OrderItemDB(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=quantity,
        ))

    return order


def run_subscription_cycle(db: Session) -> int:
    """Generate an order for every subscription due right now. Returns how many were generated."""
    from app.services.notifications import notify_customer_of_subscription_order_ready

    due = db.query(SubscriptionDB).filter(
        SubscriptionDB.status == SubscriptionStatus.active,
        SubscriptionDB.next_run_date <= datetime.utcnow(),
    ).all()

    generated = 0
    for subscription in due:
        try:
            order = generate_order_for_subscription(db, subscription)
            # Next cycle always advances on schedule, whether or not this
            # cycle produced a payable order (e.g. everything sold out) -
            # see module docstring for why.
            subscription.next_run_date = subscription.next_run_date + timedelta(days=subscription.interval_days)
            subscription.reminder_sent_at = None  # Phase 10: fresh reminder eligibility for the new cycle
            db.commit()
            if order:
                notify_customer_of_subscription_order_ready(db, subscription.customer_id, order)
                generated += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to generate subscription order for subscription %s", subscription.id)
    return generated


async def _scheduler_loop(session_factory):
    while True:
        start = time.monotonic()
        try:
            db = session_factory()
            try:
                count = run_subscription_cycle(db)
                if count:
                    logger.info("Subscription scheduler generated %d order(s).", count)
                monitoring_svc.record_job_heartbeat(db, "subscription_scheduler", "success", int((time.monotonic() - start) * 1000))
            finally:
                db.close()
        except Exception as error:
            logger.exception("Subscription scheduler tick failed")
            try:
                db = session_factory()
                monitoring_svc.record_job_heartbeat(db, "subscription_scheduler", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
                db.close()
            except Exception:
                pass
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


def start_subscription_scheduler(session_factory) -> asyncio.Task:
    """Call once at app startup (see main.py). Returns the task so the caller can hold a reference to it."""
    return asyncio.create_task(_scheduler_loop(session_factory))
