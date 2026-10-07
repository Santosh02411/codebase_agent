"""
Refund handling for cancelled orders. Called from both cancellation
paths — the customer self-serve cancel (routes/customer_dashboard.py)
and the dispatcher/admin-side status update (routes/deliveries.py) —
so a paid order that gets cancelled either way actually gets money
moved back, not just marked "cancelled" in the database.

Mirrors services/payment.py's test-mode pattern deliberately: without
Razorpay keys configured, refunds still fully exercise the same code
path (order looked up, eligibility checked, refund_status/refunded_at
set) but the actual money-movement step is a clearly-labeled local
stand-in instead of a real gateway call — same reasoning as
is_test_mode_payment on the way in.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.order import OrderDB, OrderStatus
from app.services.payment import IS_CONFIGURED, create_razorpay_refund
from app.services.inventory import restock_order_if_needed
from app.services.reconciliation import log_ledger_entry
from app.services.finance import auto_generate_credit_note_for_refund
from app.services.webhooks import emit_event
from app.services.notification_templates import send_templated_notification

logger = logging.getLogger(__name__)


def _notify_customer_of_refund(db: Session, order: OrderDB, delivery_id: str) -> None:
    """Best-effort — see services/notification_templates.py. Looks up contact info from the delivery record (which carries customer_email/phone) rather than requiring OrderDB to duplicate them."""
    from app.models.delivery import DeliveryRecordDB
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
    if not delivery:
        return
    try:
        send_templated_notification(
            db, org_id=order.org_id, event_type="refund_processed", order_id=order.id,
            customer_id=order.customer_id, customer_email=delivery.customer_email,
            customer_phone=delivery.customer_phone, delivery_id=delivery_id,
        )
    except Exception:
        pass  # best-effort, same tolerance as every other notification send in this project


def refund_order_for_delivery(db: Session, delivery_id: str) -> Optional[OrderDB]:
    """
    Given a delivery that was just cancelled, find its linked Order (if
    any) and refund it if it was actually paid for. Safe to call for
    ANY cancelled delivery, including ones with no linked Order at all
    (a dispatcher-created manual delivery, never went through checkout)
    — those simply return None, nothing to do.

    Also restocks any stock-tracked products from the order (see
    services/inventory.py) — the items never shipped, so they go back
    on the shelf whenever the order gets refunded.

    Idempotent: calling this twice on an already-refunded order is a
    no-op, so it's safe even if cancellation logic ever runs twice.
    """
    order = db.query(OrderDB).filter(OrderDB.delivery_id == delivery_id).first()
    if not order:
        return None  # not a checkout-originated delivery — nothing to refund

    if order.status != OrderStatus.paid:
        return order  # never paid (or already failed) — nothing to refund

    if order.refund_status == "refunded":
        return order  # already handled

    if order.payment_method == "cod":
        # Cash on delivery — nothing was ever charged, so there's
        # nothing to refund. Still restock (the items never shipped),
        # and mark it clearly so it doesn't look like an oversight.
        order.refund_status = "not_applicable"
        db.commit()
        db.refresh(order)
        restock_order_if_needed(db, order)
        return order

    # The actual amount the customer was charged — includes delivery fee
    # and tax, not just the product subtotal. Falls back to subtotal for
    # any pre-existing order row that predates these columns.
    refund_amount = order.total if order.total else order.subtotal

    if order.is_test_mode_payment:
        # No real gateway was ever charged for this order, so there's
        # nothing to call — but the refund is still recorded as having
        # happened, exactly as clearly-labeled as the test-mode payment
        # itself was on the way in.
        order.refund_status = "refunded"
        order.refunded_at = datetime.utcnow()
        db.commit()
        db.refresh(order)
        restock_order_if_needed(db, order)
        log_ledger_entry(db, order.org_id, "refund", refund_amount, order_id=order.id, delivery_id=delivery_id, note="Test-mode refund")
        auto_generate_credit_note_for_refund(db, order, refund_amount)
        emit_event(db, order.org_id, "refund.created", {"order_id": order.id, "amount": refund_amount, "delivery_id": delivery_id})
        _notify_customer_of_refund(db, order, delivery_id)
        return order

    if not IS_CONFIGURED or not order.razorpay_payment_id:
        # A real order that somehow has no captured payment ID to refund
        # against — shouldn't normally happen, but fail loudly into the
        # "failed" state rather than silently pretending it's refunded.
        order.refund_status = "failed"
        db.commit()
        db.refresh(order)
        return order

    amount_paise = int(round(refund_amount * 100))
    try:
        refund = create_razorpay_refund(order.razorpay_payment_id, amount_paise)
        order.razorpay_refund_id = refund.get("id")
        order.refund_status = "refunded"
        order.refunded_at = datetime.utcnow()
    except Exception:
        # Never let a refund failure block the cancellation itself from
        # having already gone through — surface it as a failed refund
        # instead, so it's visible and can be retried/handled manually.
        logger.exception("Razorpay refund failed for order %s", order.id)
        order.refund_status = "failed"

    db.commit()
    db.refresh(order)
    if order.refund_status == "refunded":
        restock_order_if_needed(db, order)
        log_ledger_entry(db, order.org_id, "refund", refund_amount, order_id=order.id, delivery_id=delivery_id, reference=order.razorpay_refund_id)
        auto_generate_credit_note_for_refund(db, order, refund_amount, ledger_reference=order.razorpay_refund_id)
        emit_event(db, order.org_id, "refund.created", {"order_id": order.id, "amount": refund_amount, "delivery_id": delivery_id})
        _notify_customer_of_refund(db, order, delivery_id)
    return order
