"""
Customer-facing recurring/subscription orders.

Everything here is scoped to the logged-in customer (get_current_customer)
the same way routes/cart.py and routes/checkout.py are. See
models/subscription.py's module docstring for the overall design
("manual confirm & pay each cycle", never auto-charged) and
services/subscription_scheduler.py for how a due subscription actually
turns into a payable order.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.customer import CustomerDB
from app.models.product import ProductDB
from app.models.order import OrderDB, OrderStatus, CheckoutResponse
from app.models.subscription import (
    SubscriptionDB, SubscriptionItemDB, SubscriptionStatus,
    SubscriptionCreate, SubscriptionUpdate, SubscriptionOut, SubscriptionItemOut,
)
from app.routes.customer_auth import get_current_customer
from app.services.payment import IS_CONFIGURED, RAZORPAY_KEY_ID, create_razorpay_order
from app.services.subscription_scheduler import generate_order_for_subscription

router = APIRouter(prefix="/customer/subscriptions", tags=["subscriptions"])


def _serialize(db: Session, subscription: SubscriptionDB) -> SubscriptionOut:
    item_rows = db.query(SubscriptionItemDB).filter(SubscriptionItemDB.subscription_id == subscription.id).all()
    items = []
    for row in item_rows:
        product = db.query(ProductDB).filter(ProductDB.id == row.product_id).first()
        items.append(SubscriptionItemOut(
            product_id=row.product_id,
            quantity=row.quantity,
            product_name=product.name if product else None,
            unit_price=product.price if product else None,
        ))

    pending_order = db.query(OrderDB).filter(
        OrderDB.subscription_id == subscription.id,
        OrderDB.status == OrderStatus.pending_payment,
    ).order_by(OrderDB.created_at.desc()).first()

    out = SubscriptionOut.model_validate(subscription)
    out.items = items
    if pending_order:
        out.pending_order_id = pending_order.id
        out.pending_order_total = pending_order.total
    return out


def _require_items_belong_to_org(db: Session, org_id: str, items: list) -> None:
    if not items:
        raise HTTPException(status_code=400, detail="A subscription needs at least one item.")
    for item in items:
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be at least 1.")
        product = db.query(ProductDB).filter(
            ProductDB.id == item.product_id, ProductDB.org_id == org_id, ProductDB.is_active == True  # noqa: E712
        ).first()
        if not product:
            raise HTTPException(status_code=400, detail="One of these items isn't available from this store.")


@router.post("/", response_model=SubscriptionOut)
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    if payload.interval_days < 1:
        raise HTTPException(status_code=400, detail="interval_days must be at least 1.")
    if payload.payment_method not in ("online", "cod"):
        raise HTTPException(status_code=400, detail="payment_method must be 'online' or 'cod'.")
    _require_items_belong_to_org(db, payload.org_id, payload.items)

    subscription = SubscriptionDB(
        id=str(uuid.uuid4()),
        customer_id=current_customer.id,
        org_id=payload.org_id,
        status=SubscriptionStatus.active,
        interval_days=payload.interval_days,
        next_run_date=datetime.utcnow(),  # due immediately - first cycle's order is generated the next scheduler tick, or via "run now"
        address_line=payload.address_line,
        city=payload.city,
        phone=payload.phone,
        payment_method=payload.payment_method,
        coupon_code=payload.coupon_code,
        created_at=datetime.utcnow(),
    )
    db.add(subscription)
    db.flush()
    for item in payload.items:
        db.add(SubscriptionItemDB(
            id=str(uuid.uuid4()), subscription_id=subscription.id,
            product_id=item.product_id, quantity=item.quantity,
        ))
    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.get("/", response_model=List[SubscriptionOut])
def list_my_subscriptions(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    subs = db.query(SubscriptionDB).filter(
        SubscriptionDB.customer_id == current_customer.id
    ).order_by(SubscriptionDB.created_at.desc()).all()
    return [_serialize(db, s) for s in subs]


def _get_owned_subscription(db: Session, subscription_id: str, customer_id: str) -> SubscriptionDB:
    subscription = db.query(SubscriptionDB).filter(
        SubscriptionDB.id == subscription_id, SubscriptionDB.customer_id == customer_id
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return subscription


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    subscription = _get_owned_subscription(db, subscription_id, current_customer.id)
    if subscription.status == SubscriptionStatus.cancelled:
        raise HTTPException(status_code=400, detail="This subscription has been cancelled.")

    if payload.interval_days is not None:
        if payload.interval_days < 1:
            raise HTTPException(status_code=400, detail="interval_days must be at least 1.")
        subscription.interval_days = payload.interval_days
    if payload.address_line is not None:
        subscription.address_line = payload.address_line
    if payload.city is not None:
        subscription.city = payload.city
    if payload.phone is not None:
        subscription.phone = payload.phone
    if payload.payment_method is not None:
        if payload.payment_method not in ("online", "cod"):
            raise HTTPException(status_code=400, detail="payment_method must be 'online' or 'cod'.")
        subscription.payment_method = payload.payment_method
    if payload.coupon_code is not None:
        subscription.coupon_code = payload.coupon_code or None
    if payload.items is not None:
        _require_items_belong_to_org(db, subscription.org_id, payload.items)
        db.query(SubscriptionItemDB).filter(SubscriptionItemDB.subscription_id == subscription.id).delete()
        for item in payload.items:
            db.add(SubscriptionItemDB(
                id=str(uuid.uuid4()), subscription_id=subscription.id,
                product_id=item.product_id, quantity=item.quantity,
            ))

    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.post("/{subscription_id}/pause", response_model=SubscriptionOut)
def pause_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    subscription = _get_owned_subscription(db, subscription_id, current_customer.id)
    if subscription.status == SubscriptionStatus.cancelled:
        raise HTTPException(status_code=400, detail="This subscription has been cancelled.")
    subscription.status = SubscriptionStatus.paused
    subscription.paused_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.post("/{subscription_id}/resume", response_model=SubscriptionOut)
def resume_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    subscription = _get_owned_subscription(db, subscription_id, current_customer.id)
    if subscription.status == SubscriptionStatus.cancelled:
        raise HTTPException(status_code=400, detail="This subscription has been cancelled — create a new one instead.")
    subscription.status = SubscriptionStatus.active
    subscription.paused_at = None
    # Resuming doesn't retroactively owe every cycle that was missed
    # while paused - just pick up from today, same as a plan you unpause.
    if subscription.next_run_date < datetime.utcnow():
        subscription.next_run_date = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionOut)
def cancel_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    subscription = _get_owned_subscription(db, subscription_id, current_customer.id)
    subscription.status = SubscriptionStatus.cancelled
    subscription.cancelled_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.post("/{subscription_id}/run-now", response_model=SubscriptionOut)
def run_subscription_now(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Generate this cycle's order immediately instead of waiting for the
    background scheduler or the next_run_date to arrive - lets the
    feature be tested/demoed on demand. Same effect either way: builds
    an order at current prices/stock and advances next_run_date by
    interval_days.
    """
    subscription = _get_owned_subscription(db, subscription_id, current_customer.id)
    if subscription.status != SubscriptionStatus.active:
        raise HTTPException(status_code=400, detail="Only an active subscription can be run.")

    existing_pending = db.query(OrderDB).filter(
        OrderDB.subscription_id == subscription.id, OrderDB.status == OrderStatus.pending_payment,
    ).first()
    if existing_pending:
        raise HTTPException(
            status_code=400,
            detail="There's already an order from this subscription awaiting payment. Pay or let it lapse first.",
        )

    order = generate_order_for_subscription(db, subscription)
    if not order:
        raise HTTPException(status_code=400, detail="Every item in this subscription is currently unavailable.")

    from datetime import timedelta
    subscription.next_run_date = subscription.next_run_date + timedelta(days=subscription.interval_days)
    db.commit()
    db.refresh(subscription)
    return _serialize(db, subscription)


@router.post("/orders/{order_id}/initiate-payment", response_model=CheckoutResponse)
def initiate_subscription_order_payment(
    order_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Same payment-initiation tail as routes/checkout.py's checkout()
    endpoint (COD needs no gateway step, an online order gets a real
    Razorpay order or the local test-mode stand-in) — but applied to an
    order the SUBSCRIPTION scheduler already created, instead of
    building a brand new one from the cart. The frontend then calls the
    existing, unmodified POST /customer/checkout/verify with the
    returned order_id exactly as it does for a normal checkout.
    """
    order = db.query(OrderDB).filter(
        OrderDB.id == order_id,
        OrderDB.customer_id == current_customer.id,
        OrderDB.subscription_id.isnot(None),
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Subscription order not found.")
    if order.status != OrderStatus.pending_payment:
        raise HTTPException(status_code=400, detail="This order has already been paid or is no longer payable.")

    amount_paise = int(round(order.total * 100))
    breakdown = dict(
        subtotal=order.subtotal,
        coupon_code=order.coupon_code,
        discount_amount=order.discount_amount,
        delivery_fee=order.delivery_fee,
        tax_amount=order.tax_amount,
        total=order.total,
    )

    if order.payment_method == "cod":
        return CheckoutResponse(
            order_id=order.id, razorpay_order_id=None, razorpay_key_id=None,
            amount_paise=amount_paise, is_test_mode=False, payment_method="cod", **breakdown,
        )

    if order.razorpay_order_id:
        # Already initiated once (e.g. the customer navigated away mid-payment) - reuse it rather than
        # creating a second Razorpay order for the same DB order.
        return CheckoutResponse(
            order_id=order.id, razorpay_order_id=order.razorpay_order_id, razorpay_key_id=RAZORPAY_KEY_ID,
            amount_paise=amount_paise, is_test_mode=bool(order.is_test_mode_payment),
            payment_method="online", **breakdown,
        )

    if IS_CONFIGURED:
        try:
            razorpay_order = create_razorpay_order(amount_paise=amount_paise, receipt=order.id)
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="Couldn't reach the payment gateway. Check RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET in backend/.env.",
            )
        order.razorpay_order_id = razorpay_order["id"]
        db.commit()
        return CheckoutResponse(
            order_id=order.id, razorpay_order_id=razorpay_order["id"], razorpay_key_id=RAZORPAY_KEY_ID,
            amount_paise=amount_paise, is_test_mode=False, payment_method="online", **breakdown,
        )

    order.is_test_mode_payment = 1
    db.commit()
    return CheckoutResponse(
        order_id=order.id, razorpay_order_id=None, razorpay_key_id=None,
        amount_paise=amount_paise, is_test_mode=True, payment_method="online", **breakdown,
    )
