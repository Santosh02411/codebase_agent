"""
Checkout: cart -> Order (+ Razorpay payment) -> on verified payment,
a real DeliveryRecordDB row is created (status=pending, unassigned),
which immediately flows into the existing dispatcher/agent pipeline
completely unchanged, and shows up in the customer's existing "My
Orders" tracking view.

Pricing at checkout, in order:
  1. subtotal          - sum of product price * quantity
  2. - discount_amount - from an applied coupon, if any (see services/coupons.py)
  3. + tax_amount      - org's tax_rate_percent applied to the discounted subtotal (GST)
  4. + delivery_fee    - org's flat delivery_fee
  = total              - the actual amount charged via Razorpay

Stock is checked (not yet decremented) here at checkout-creation time
for early feedback, and checked again + actually decremented at
verify_payment() - see services/inventory.py's module docstring for why
decrementing happens there and not here.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.cart import CartItemDB
from app.models.product import ProductDB
from app.models.organization import OrganizationDB
from app.models.coupon import CouponApply, CouponPreviewOut, CouponDB
from app.models.order import (
    OrderDB, OrderItemDB, OrderStatus,
    CheckoutRequest, CheckoutResponse, VerifyPaymentRequest, OrderOut, OrderItemOut,
)
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.customer import CustomerDB
from app.routes.customer_auth import get_current_customer
from app.services.payment import IS_CONFIGURED, RAZORPAY_KEY_ID, create_razorpay_order, create_razorpay_refund, verify_razorpay_signature
from app.services.history import record_history_entry
from app.services.notifications import notify_customer_of_status_change, notify_dispatchers_of_new_order
from app.services.inventory import check_stock_available, decrement_stock_for_order, InsufficientStockError
from app.services.coupons import find_and_validate_coupon, compute_discount, CouponError
from app.services.slots import validate_slot
from app.services.websocket_manager import broadcast_sync, dispatcher_queue_room
from app.services.rate_limiter import limiter
from app.services.reconciliation import log_ledger_entry
from app.services.finance import auto_generate_invoice_for_order
from app.services.webhooks import emit_event

router = APIRouter(prefix="/customer", tags=["checkout"])


def _load_cart(db: Session, customer_id: str):
    """Shared by checkout and coupon preview: cart lines + subtotal for one customer."""
    cart_items = db.query(CartItemDB).filter(CartItemDB.customer_id == customer_id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")

    org_id = cart_items[0].org_id
    subtotal = 0.0
    line_snapshots = []
    for item in cart_items:
        product = db.query(ProductDB).filter(ProductDB.id == item.product_id).first()
        if not product:
            continue
        subtotal += product.price * item.quantity
        line_snapshots.append((product, item.quantity))

    if not line_snapshots:
        raise HTTPException(status_code=400, detail="Every item in your cart is no longer available.")

    return org_id, line_snapshots, round(subtotal, 2)


@router.post("/checkout/validate-coupon", response_model=CouponPreviewOut)
@limiter.limit("20/minute")
def validate_coupon(
    request: Request,
    payload: CouponApply,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Preview a coupon's discount against the current cart, before committing to checkout."""
    org_id, _line_snapshots, subtotal = _load_cart(db, current_customer.id)
    try:
        coupon = find_and_validate_coupon(db, org_id, payload.code, subtotal)
    except CouponError as e:
        raise HTTPException(status_code=400, detail=e.message)
    discount = compute_discount(coupon, subtotal)
    return CouponPreviewOut(
        code=coupon.code,
        discount_amount=discount,
        subtotal=subtotal,
        new_subtotal=round(subtotal - discount, 2),
    )


@router.post("/checkout", response_model=CheckoutResponse)
@limiter.limit("10/minute")
def checkout(
    request: Request,
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    org_id, line_snapshots, subtotal = _load_cart(db, current_customer.id)

    org = db.query(OrganizationDB).filter(OrganizationDB.id == org_id).first()
    if org and org.is_suspended:
        raise HTTPException(status_code=403, detail="This store is temporarily unavailable and isn't accepting new orders.")

    if payload.payment_method not in ("online", "cod"):
        raise HTTPException(status_code=400, detail="payment_method must be 'online' or 'cod'.")

    # Stock check - early feedback here; the authoritative, final check +
    # actual decrement happens again at verify_payment() (see that
    # function's docstring for why).
    try:
        for product, quantity in line_snapshots:
            check_stock_available(db, product.id, quantity)
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=e.message)

    # Coupon (optional)
    coupon_code_to_store = None
    discount_amount = 0.0
    if payload.coupon_code:
        try:
            coupon = find_and_validate_coupon(db, org_id, payload.coupon_code, subtotal)
        except CouponError as e:
            raise HTTPException(status_code=400, detail=e.message)
        discount_amount = compute_discount(coupon, subtotal)
        coupon_code_to_store = coupon.code

    # Delivery fee + tax (GST) - org-configured, see models/organization.py
    org = db.query(OrganizationDB).filter(OrganizationDB.id == org_id).first()
    delivery_fee = org.delivery_fee if org else 0.0
    tax_rate_percent = org.tax_rate_percent if org else 0.0

    # Delivery time slot (optional) - validated against the same
    # generation logic that produced the options the customer was shown
    # (GET /stores/{org_id}/delivery-slots), so a slot picked from that
    # list can never be rejected here, and one NOT from that list
    # (stale/tampered/full) always is.
    slot_start = slot_end = None
    if payload.slot_start:
        if not org:
            raise HTTPException(status_code=400, detail="This store isn't accepting scheduled deliveries.")
        try:
            slot_end = validate_slot(db, org, payload.slot_start)
            slot_start = payload.slot_start
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    taxable_amount = max(round(subtotal - discount_amount, 2), 0.0)
    tax_amount = round(taxable_amount * (tax_rate_percent / 100.0), 2)
    total = round(taxable_amount + tax_amount + delivery_fee, 2)

    order = OrderDB(
        id=str(uuid.uuid4()),
        customer_id=current_customer.id,
        org_id=org_id,
        status=OrderStatus.pending_payment,
        payment_method=payload.payment_method,
        address_line=payload.address_line,
        city=payload.city,
        phone=payload.phone,
        subtotal=subtotal,
        coupon_code=coupon_code_to_store,
        discount_amount=discount_amount,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        total=total,
        slot_start=slot_start,
        slot_end=slot_end,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()  # so order.id is usable for the OrderItem rows below, before commit

    for product, quantity in line_snapshots:
        db.add(OrderItemDB(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=quantity,
        ))

    amount_paise = int(round(total * 100))

    breakdown = dict(
        subtotal=subtotal,
        coupon_code=coupon_code_to_store,
        discount_amount=discount_amount,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        total=total,
        slot_start=slot_start,
        slot_end=slot_end,
    )

    if payload.payment_method == "cod":
        # Cash on delivery — nothing to charge right now at all, so
        # there's no gateway step and no separate "verify" round trip
        # needed the way an online payment has. The frontend calls
        # POST /customer/checkout/verify immediately after this with
        # just the order_id (same as the test-mode online path already
        # does) — see verify_payment() below, which skips signature
        # checking for any is_test_mode_payment OR "cod" order and goes
        # straight to fulfillment (stock decrement, Delivery creation,
        # dispatcher notification).
        db.commit()
        emit_event(db, org_id, "order.created", {"order_id": order.id, "total": total, "payment_method": "cod"})
        return CheckoutResponse(
            order_id=order.id,
            razorpay_order_id=None,
            razorpay_key_id=None,
            amount_paise=amount_paise,
            is_test_mode=False,
            payment_method="cod",
            **breakdown,
        )

    if IS_CONFIGURED:
        try:
            razorpay_order = create_razorpay_order(amount_paise=amount_paise, receipt=order.id)
        except Exception as e:
            # A configured-but-invalid key pair (wrong/placeholder
            # RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET), an expired test
            # key, or Razorpay's API being unreachable all land here.
            # This MUST be caught and turned into a clean HTTPException
            # rather than left to propagate — an uncaught exception this
            # deep can, depending on the middleware stack, fail to reach
            # the client as a proper response at all (see main.py's
            # add_security_headers for the general-purpose backstop),
            # which is exactly what previously showed up in the browser
            # as a misleading "you're offline" message instead of the
            # real problem.
            db.rollback()
            raise HTTPException(
                status_code=502,
                detail=(
                    "Couldn't reach the payment gateway. If you're testing locally, double-check "
                    "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env are a real, matching "
                    "Test Mode key pair from your Razorpay dashboard — or unset them entirely to use "
                    "the built-in test-mode checkout instead."
                ),
            )
        order.razorpay_order_id = razorpay_order["id"]
        db.commit()
        emit_event(db, org_id, "order.created", {"order_id": order.id, "total": total, "payment_method": "online"})
        return CheckoutResponse(
            order_id=order.id,
            razorpay_order_id=razorpay_order["id"],
            razorpay_key_id=RAZORPAY_KEY_ID,
            amount_paise=amount_paise,
            is_test_mode=False,
            payment_method="online",
            **breakdown,
        )

    # No gateway configured - order + items are still real, saved rows;
    # only the payment step itself is a local stand-in. Clearly flagged
    # both in the DB (is_test_mode_payment) and in this response, so the
    # frontend can visibly label it rather than pretending it's real.
    order.is_test_mode_payment = 1
    db.commit()
    emit_event(db, org_id, "order.created", {"order_id": order.id, "total": total, "payment_method": "online"})
    return CheckoutResponse(
        order_id=order.id,
        razorpay_order_id=None,
        razorpay_key_id=None,
        amount_paise=amount_paise,
        is_test_mode=True,
        payment_method="online",
        **breakdown,
    )


@router.post("/checkout/verify", response_model=OrderOut)
@limiter.limit("10/minute")
def verify_payment(
    request: Request,
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    order = db.query(OrderDB).filter(
        OrderDB.id == payload.order_id,
        OrderDB.customer_id == current_customer.id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status == OrderStatus.paid:
        raise HTTPException(status_code=400, detail="This order was already paid for.")

    if order.is_test_mode_payment or order.payment_method == "cod":
        pass  # no gateway signature to verify — test-mode stand-in, or a COD order paid in cash on arrival
    else:
        if not (payload.razorpay_payment_id and payload.razorpay_order_id and payload.razorpay_signature):
            raise HTTPException(status_code=400, detail="Missing payment verification details.")
        is_valid = verify_razorpay_signature(
            payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
        )
        if not is_valid:
            order.status = OrderStatus.payment_failed
            db.commit()
            raise HTTPException(status_code=400, detail="Payment verification failed. No charge was accepted.")
        order.razorpay_payment_id = payload.razorpay_payment_id

    # Final stock check, right before actually committing to fulfilling
    # this order - items may have sold out to someone else between this
    # customer's checkout-creation and now. For a real (non test-mode)
    # payment, Razorpay has already captured the money by this point, so
    # an insufficient-stock failure here means immediately refunding it
    # back rather than leaving the customer charged for nothing.
    items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
    try:
        for item in items:
            check_stock_available(db, item.product_id, item.quantity)
    except InsufficientStockError as e:
        order.status = OrderStatus.payment_failed
        if not order.is_test_mode_payment and order.razorpay_payment_id:
            try:
                refund = create_razorpay_refund(order.razorpay_payment_id, int(round(order.total * 100)))
                order.razorpay_refund_id = refund.get("id")
                order.refund_status = "refunded"
                order.refunded_at = datetime.utcnow()
            except Exception:
                order.refund_status = "failed"
        db.commit()
        suffix = " You've been refunded in full." if order.refund_status == "refunded" else ""
        raise HTTPException(status_code=400, detail=f"{e.message}{suffix}")

    decrement_stock_for_order(db, order)

    order.status = OrderStatus.paid

    # Coupon usage is only ever counted against a PAID order, so an
    # abandoned/failed checkout never burns a limited coupon's uses.
    if order.coupon_code:
        coupon = db.query(CouponDB).filter(CouponDB.org_id == order.org_id, CouponDB.code == order.coupon_code).first()
        if coupon:
            coupon.used_count = coupon.used_count + 1

    # Fulfillment: create the actual Delivery, unassigned, for a
    # dispatcher to pick up from their "Unassigned Orders" queue.
    items_summary = "; ".join(f"{i.quantity}x {i.product_name}" for i in items)
    now = datetime.utcnow()

    # Purely numeric order ID for customer-placed orders - YYMMDDHHMMSS
    # (from the order's creation instant) is unique enough for a single
    # organization's order volume without needing a database sequence,
    # and reads clearly as a receipt/order number with no letters mixed
    # in. Dispatcher-created deliveries keep using whatever human-chosen
    # order_id the dispatcher types in themselves - this generator only
    # applies to the checkout path.
    numeric_order_id = now.strftime("%y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"

    delivery = DeliveryRecordDB(
        id=str(uuid.uuid4()),
        agent_id=None,
        order_id=numeric_order_id,
        status=DeliveryStatus.pending,
        notes=f"Items: {items_summary}",
        location_note=f"{order.address_line}" + (f", {order.city}" if order.city else ""),
        created_at=now,
        updated_at=now,
        org_id=order.org_id,
        customer_email=current_customer.email,
        customer_phone=order.phone,
        customer_id=current_customer.id,
        slot_start=order.slot_start,
        slot_end=order.slot_end,
    )
    db.add(delivery)
    order.delivery_id = delivery.id

    # Cart is now spent - clear it.
    db.query(CartItemDB).filter(CartItemDB.customer_id == current_customer.id).delete()

    db.commit()
    db.refresh(order)
    db.refresh(delivery)

    fulfillment_note = (
        "Order placed (cash on delivery) - awaiting dispatcher assignment"
        if order.payment_method == "cod"
        else "Order placed and paid - awaiting dispatcher assignment"
    )
    record_history_entry(
        db=db,
        delivery_id=delivery.id,
        changed_by_user_id=current_customer.id,
        changed_by_display_name=current_customer.name,
        old_status=None,
        new_status=DeliveryStatus.pending,
        changed_at=now,
        note=fulfillment_note,
    )
    notify_customer_of_status_change(
        db,
        delivery_id=delivery.id,
        order_id=delivery.order_id,
        new_status="confirmed",
        customer_email=delivery.customer_email,
        customer_phone=delivery.customer_phone,
        customer_id=delivery.customer_id,
    )
    notify_dispatchers_of_new_order(db, org_id=order.org_id, order_id=delivery.order_id)
    broadcast_sync(dispatcher_queue_room(order.org_id), {"event": "queue_changed", "reason": "new_order"})

    # Financial ledger (Phase 5): log the charge, but only for an actual
    # online payment — a COD order hasn't been charged anything yet (the
    # agent collects cash on arrival, tracked separately via
    # routes/reconciliation.py's COD collection flow), so it gets no
    # "charge" ledger entry here.
    if order.payment_method != "cod":
        log_ledger_entry(
            db, order.org_id, "charge", order.total,
            order_id=order.id, delivery_id=delivery.id,
            reference=order.razorpay_payment_id, user_id=current_customer.id,
        )

    # Phase 13: an invoice represents what was SOLD, so it's generated for
    # every paid order — including COD, where nothing has been collected
    # yet (that's tracked separately by Phase 5's reconciliation system).
    auto_generate_invoice_for_order(db, order)

    # Phase 14: webhooks — order.paid fires once fulfillment created the
    # delivery, so a subscriber's order.paid handler can already look up
    # the associated delivery if it wants to.
    emit_event(db, order.org_id, "order.paid", {"order_id": order.id, "total": order.total, "delivery_id": delivery.id})
    emit_event(db, order.org_id, "delivery.created", {"delivery_id": delivery.id, "order_id": delivery.order_id, "status": "pending"})


    # Re-query items fresh rather than reusing the pre-commit list above -
    # SQLAlchemy expires all session objects on commit by default, and
    # serializing already-expired instances after the fact is what
    # produced empty {} objects here during testing.
    fresh_items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
    order_out = OrderOut.model_validate(order)
    order_out.items = [OrderItemOut.model_validate(i) for i in fresh_items]
    return order_out


@router.get("/orders", response_model=List[OrderOut])
def list_my_orders(
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    delivery_id: Optional[str] = Query(None, description="Filter to the order linked to one delivery"),
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Itemized purchase history - separate from /customer/deliveries,
    which tracks fulfillment/shipment status. Paginated (newest first).

    `delivery_id` is a targeted filter, not part of the pagination
    scheme: it exists because the frontend also uses this endpoint to
    look up ONE order's refund status by its linked delivery (see
    CustomerDeliveryCard's cancelled-order handling) — a lookup that
    would otherwise silently miss older orders once the main list
    became paginated with a small default page size.
    """
    query = db.query(OrderDB).filter(OrderDB.customer_id == current_customer.id)
    if delivery_id:
        query = query.filter(OrderDB.delivery_id == delivery_id)
    orders = (
        query
        .order_by(OrderDB.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    results = []
    for order in orders:
        items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
        order_out = OrderOut.model_validate(order)
        order_out.items = [OrderItemOut.model_validate(i) for i in items]
        results.append(order_out)
    return results
