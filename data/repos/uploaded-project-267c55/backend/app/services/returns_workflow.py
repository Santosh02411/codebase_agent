"""
Return/exchange workflow logic shared between the two places a delivery
status change can happen: the normal online PATCH endpoint
(routes/deliveries.py) and the offline-sync conflict resolver
(services/conflict_resolver.py) — both need to trigger the same
completion behavior when a return_pickup delivery reaches "delivered",
so it lives here once rather than being duplicated (and drifting) in
two places.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.return_request import ReturnRequestDB, ReturnRequestType, ReturnRequestStatus
from app.models.order import OrderDB
from app.services.refund import refund_order_for_delivery
from app.services.inventory import restock_order_if_needed
from app.services.websocket_manager import broadcast_sync, dispatcher_queue_room

logger = logging.getLogger(__name__)


def create_return_pickup_delivery(db: Session, return_request: ReturnRequestDB, original_delivery: DeliveryRecordDB) -> DeliveryRecordDB:
    """
    Called when a dispatcher/admin APPROVES a return/exchange request:
    creates a new DeliveryRecordDB for an agent to go collect the item
    back from the customer. Reuses the original delivery's
    address/contact info (a return is picked up from wherever the item
    was originally delivered) and drops straight into the same
    unassigned queue every normal checkout order does.
    """
    label = "Return" if return_request.request_type == ReturnRequestType.return_ else "Exchange"
    now = datetime.utcnow()
    pickup = DeliveryRecordDB(
        id=str(uuid.uuid4()),
        agent_id=None,
        order_id=original_delivery.order_id,
        status=DeliveryStatus.pending,
        notes=f"{label} pickup for order {original_delivery.order_id}. Reason: {return_request.reason}",
        location_note=original_delivery.location_note,
        created_at=now,
        updated_at=now,
        zone=original_delivery.zone,
        latitude=original_delivery.latitude,
        longitude=original_delivery.longitude,
        org_id=original_delivery.org_id,
        customer_email=original_delivery.customer_email,
        customer_phone=original_delivery.customer_phone,
        customer_id=original_delivery.customer_id,
        delivery_type="return_pickup",
    )
    db.add(pickup)
    db.commit()
    db.refresh(pickup)
    broadcast_sync(dispatcher_queue_room(pickup.org_id), {"event": "queue_changed", "reason": "return_pickup_created"})
    return pickup


def handle_return_pickup_completion(db: Session, pickup_delivery: DeliveryRecordDB) -> None:
    """
    Called whenever ANY delivery transitions to `delivered`, from either
    status-change path — it's a no-op unless that delivery is actually a
    return_pickup (checked first, cheaply, before doing anything else).

    For a RETURN: refunds the original order (services/refund.py — the
    same real/test-mode-aware refund logic cancellation uses) and
    restocks the item, then marks the request completed.

    For an EXCHANGE: creates a brand new forward delivery for the
    replacement item and marks the request completed with that new
    delivery linked. Simplification, disclosed here rather than hidden:
    the replacement delivery doesn't re-run checkout's stock-decrement
    logic for a specific NEW product (that would need the customer to
    pick a replacement item through a real product-selection flow) — it
    restocks the returned item exactly like a return does, and creates
    an unassigned pickup-style delivery a dispatcher can point at
    whatever replacement was agreed with the customer.
    """
    if pickup_delivery.delivery_type != "return_pickup":
        return

    return_request = db.query(ReturnRequestDB).filter(
        ReturnRequestDB.pickup_delivery_id == pickup_delivery.id
    ).first()
    if not return_request or return_request.status == ReturnRequestStatus.completed:
        return  # not a tracked return, or already handled (idempotent)

    if return_request.request_type == ReturnRequestType.return_:
        # Real refund (or its clearly-labeled test-mode stand-in) AND
        # restock together — a return means the customer is getting
        # their money back.
        refund_order_for_delivery(db, return_request.delivery_id)
    else:
        original = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == return_request.delivery_id).first()
        if original:
            now = datetime.utcnow()
            exchange_delivery = DeliveryRecordDB(
                id=str(uuid.uuid4()),
                agent_id=None,
                order_id=original.order_id,
                status=DeliveryStatus.pending,
                notes=f"Exchange replacement for order {original.order_id}",
                location_note=original.location_note,
                created_at=now,
                updated_at=now,
                zone=original.zone,
                latitude=original.latitude,
                longitude=original.longitude,
                org_id=original.org_id,
                customer_email=original.customer_email,
                customer_phone=original.customer_phone,
                customer_id=original.customer_id,
                delivery_type="delivery",
            )
            db.add(exchange_delivery)
            db.commit()
            db.refresh(exchange_delivery)
            return_request.exchange_delivery_id = exchange_delivery.id
            broadcast_sync(dispatcher_queue_room(exchange_delivery.org_id), {"event": "queue_changed", "reason": "exchange_delivery_created"})

        # An exchange restocks the returned item WITHOUT refunding —
        # no money is owed back, the customer is getting a replacement
        # instead. Deliberately calls restock_order_if_needed directly
        # rather than refund_order_for_delivery, which would also
        # (wrongly) process a real refund.
        order = db.query(OrderDB).filter(OrderDB.id == return_request.order_id).first()
        if order:
            restock_order_if_needed(db, order)
            db.commit()

    return_request.status = ReturnRequestStatus.completed
    return_request.resolved_at = datetime.utcnow()
    db.commit()
