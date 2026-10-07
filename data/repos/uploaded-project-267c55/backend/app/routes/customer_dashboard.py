"""
Customer dashboard — the REAL, logged-in customer experience: every
delivery linked to this customer's account (across ANY organization
using this platform, not just one), plus their in-app notification
inbox. This is what a customer actually uses day-to-day, as opposed to
the one-off public tracking link (still available for guests without an
account, or for sharing a single order with someone else).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB, DeliveryRecordOut, ClaimOrderRequest, DeliveryStatus
from app.models.delivery_history import DeliveryHistoryDB, DeliveryHistoryOut
from app.models.customer import CustomerDB
from app.models.customer_notification import CustomerNotificationDB, CustomerNotificationOut
from app.models.feedback import DeliveryFeedbackDB, FeedbackOut
from app.models.customer_address import CustomerAddressDB, CustomerAddressCreate, CustomerAddressOut
from app.models.agent_location import AgentLocationDB, AgentLocationOut
from app.models.push_subscription import PushSubscriptionDB, PushSubscriptionCreate
from app.services.history import record_history_entry
from app.services.push import VAPID_PUBLIC_KEY
from app.services.refund import refund_order_for_delivery
from app.services.webhooks import emit_event
from app.routes.customer_auth import get_current_customer
from app.models.proof_of_delivery import ProofOfDeliveryDB, ProofOfDeliveryOut

router = APIRouter(prefix="/customer", tags=["customer-dashboard"])

# Statuses a customer is still allowed to back out of. Once an agent has
# physically picked the order up, cancelling stops being self-serve —
# same rule any real delivery/e-commerce app applies.
CANCELLABLE_STATUSES = {DeliveryStatus.picked_up, DeliveryStatus.pending}


def _normalize_phone(raw: str) -> str:
    """Digits only, so '+91 98765-43210' and '9876543210' compare equal."""
    return "".join(ch for ch in raw if ch.isdigit())


@router.post("/deliveries/claim", response_model=DeliveryRecordOut)
def claim_order(
    payload: ClaimOrderRequest,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Manually link an order to the logged-in customer's account, for the
    case where it wasn't auto-linked (the dispatcher entered a different
    email than the one this customer signed up with — a common real-world
    mismatch: guest checkout, a typo, a work vs personal email, etc.).

    Verified with order_id + phone together, since order_id alone (a
    dispatcher-chosen reference number) isn't secret or guaranteed unique
    across organizations, so it can't prove ownership by itself.
    """
    normalized_input_phone = _normalize_phone(payload.phone)
    if not normalized_input_phone:
        raise HTTPException(status_code=400, detail="Enter the phone number on file for this order.")

    candidates = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.order_id == payload.order_id,
        DeliveryRecordDB.customer_phone.isnot(None),
    ).all()

    match = next(
        (d for d in candidates if _normalize_phone(d.customer_phone) == normalized_input_phone),
        None,
    )

    if not match:
        raise HTTPException(
            status_code=404,
            detail="No order found with that Order ID and phone number. Double-check both and try again.",
        )

    if match.customer_id and match.customer_id != current_customer.id:
        raise HTTPException(
            status_code=409,
            detail="This order is already linked to a different account.",
        )

    match.customer_id = current_customer.id
    db.commit()
    db.refresh(match)
    return match


@router.get("/deliveries", response_model=List[DeliveryRecordOut])
def list_my_deliveries(
    limit: Optional[int] = Query(None, ge=1, le=200, description="Max records to return. Omit to fetch everything (used for the offline cache)."),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Every delivery linked to this customer's account, across any
    organization, newest-updated first.

    `limit`/`offset` are optional, not defaulted: the main dashboard
    call omits them on purpose — that response also seeds this
    customer's offline cache (see cacheCustomerDeliveries() in the
    frontend), so it needs to stay complete for the offline fallback to
    actually work. When a caller DOES pass `limit` (e.g. a future
    "load more" UI over an already-large history), this paginates like
    any other list endpoint.
    """
    query = (
        db.query(DeliveryRecordDB)
        .filter(DeliveryRecordDB.customer_id == current_customer.id)
        .order_by(DeliveryRecordDB.updated_at.desc())
    )
    if limit is not None:
        query = query.offset(offset).limit(limit)
    return query.all()


@router.get("/deliveries/{delivery_id}/pod", response_model=ProofOfDeliveryOut)
def get_my_delivery_pod(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Proof of delivery for one of the customer's OWN deliveries only — 404s for any other delivery, same as get_my_delivery_history above."""
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    pod = db.query(ProofOfDeliveryDB).filter(
        ProofOfDeliveryDB.delivery_id == delivery_id,
    ).order_by(ProofOfDeliveryDB.captured_at.desc()).first()
    if not pod:
        raise HTTPException(status_code=404, detail="No proof of delivery has been captured for this delivery yet.")
    return pod


@router.get("/deliveries/{delivery_id}/history", response_model=List[DeliveryHistoryOut])
def get_my_delivery_history(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Full status timeline for one of the customer's own deliveries."""
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    return (
        db.query(DeliveryHistoryDB)
        .filter(DeliveryHistoryDB.delivery_id == delivery_id)
        .order_by(DeliveryHistoryDB.changed_at.asc())
        .all()
    )


@router.get("/deliveries/{delivery_id}/feedback", response_model=Optional[FeedbackOut])
def get_my_delivery_feedback(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    return db.query(DeliveryFeedbackDB).filter(DeliveryFeedbackDB.delivery_id == delivery_id).first()


@router.post("/deliveries/{delivery_id}/cancel", response_model=DeliveryRecordOut)
def cancel_my_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Self-serve cancellation, restricted to orders that haven't moved
    past the initial "picked_up" stage yet — matches how real delivery/
    e-commerce apps gate this (Amazon, Swiggy, etc. all stop letting you
    cancel once the order is genuinely in motion).
    """
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    if delivery.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="This order can no longer be cancelled — it's already out for delivery or further along.",
        )

    old_status = delivery.status
    delivery.status = DeliveryStatus.cancelled
    delivery.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)

    record_history_entry(
        db=db,
        delivery_id=delivery.id,
        changed_by_user_id=current_customer.id,
        changed_by_display_name=current_customer.name,
        old_status=old_status,
        new_status=DeliveryStatus.cancelled,
        changed_at=delivery.updated_at,
        note="Cancelled by customer",
    )

    # If this delivery came from a paid checkout order, actually move
    # the money back — see services/refund.py. A no-op for manually
    # created deliveries with no linked Order, or ones that were never
    # paid in the first place.
    refund_order_for_delivery(db, delivery.id)

    emit_event(db, delivery.org_id, "order.cancelled", {"delivery_id": delivery.id, "order_id": delivery.order_id})

    return delivery


@router.post("/deliveries/{delivery_id}/reorder", response_model=DeliveryRecordOut)
def reorder_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Places a fresh delivery cloned from a past one — same org, agent,
    zone, and address details, new order ID and a clean status/timeline.
    The one-click "reorder" button standard on any order history page.
    """
    original = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not original:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    now = datetime.utcnow()
    new_delivery = DeliveryRecordDB(
        id=str(uuid.uuid4()),
        agent_id=original.agent_id,
        order_id=f"{original.order_id}-RE{int(now.timestamp())}",
        status=DeliveryStatus.picked_up,
        notes=original.notes,
        location_note=original.location_note,
        created_at=now,
        updated_at=now,
        zone=original.zone,
        latitude=original.latitude,
        longitude=original.longitude,
        expected_by=None,
        org_id=original.org_id,
        customer_email=original.customer_email,
        customer_phone=original.customer_phone,
        customer_id=current_customer.id,
    )
    db.add(new_delivery)
    db.commit()
    db.refresh(new_delivery)

    record_history_entry(
        db=db,
        delivery_id=new_delivery.id,
        changed_by_user_id=current_customer.id,
        changed_by_display_name=current_customer.name,
        old_status=None,
        new_status=DeliveryStatus.picked_up,
        changed_at=now,
        note=f"Reordered from {original.order_id}",
    )
    return new_delivery


@router.get("/deliveries/{delivery_id}/agent-location", response_model=AgentLocationOut)
def get_my_delivery_agent_location(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Live agent GPS position for one of the customer's own deliveries, for the tracking map."""
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    location = db.query(AgentLocationDB).filter(AgentLocationDB.agent_id == delivery.agent_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Agent hasn't shared a live location yet.")
    return location


@router.get("/addresses", response_model=List[CustomerAddressOut])
def list_my_addresses(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    return (
        db.query(CustomerAddressDB)
        .filter(CustomerAddressDB.customer_id == current_customer.id)
        .order_by(CustomerAddressDB.created_at.desc())
        .all()
    )


@router.post("/addresses", response_model=CustomerAddressOut)
def add_my_address(
    payload: CustomerAddressCreate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    if payload.is_default:
        db.query(CustomerAddressDB).filter(
            CustomerAddressDB.customer_id == current_customer.id
        ).update({"is_default": False})

    address = CustomerAddressDB(
        id=str(uuid.uuid4()),
        customer_id=current_customer.id,
        label=payload.label,
        address_line=payload.address_line,
        city=payload.city,
        phone=payload.phone,
        is_default=payload.is_default,
        created_at=datetime.utcnow(),
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/addresses/{address_id}")
def delete_my_address(
    address_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    address = db.query(CustomerAddressDB).filter(
        CustomerAddressDB.id == address_id,
        CustomerAddressDB.customer_id == current_customer.id,
    ).first()
    if not address:
        raise HTTPException(status_code=404, detail="Address not found.")
    db.delete(address)
    db.commit()
    return {"message": "Address deleted."}


@router.get("/push/vapid-public-key")
def get_vapid_public_key():
    """Public key the frontend needs to create a PushManager subscription. Safe to expose — it's public by design."""
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/push/subscribe")
def subscribe_to_push(
    payload: PushSubscriptionCreate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Saves a browser's push subscription so future status changes trigger a real OS-level notification."""
    existing = db.query(PushSubscriptionDB).filter(PushSubscriptionDB.endpoint == payload.endpoint).first()
    if existing:
        existing.customer_id = current_customer.id
        existing.p256dh = payload.keys.get("p256dh", "")
        existing.auth = payload.keys.get("auth", "")
    else:
        db.add(PushSubscriptionDB(
            id=str(uuid.uuid4()),
            customer_id=current_customer.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.get("p256dh", ""),
            auth=payload.keys.get("auth", ""),
            created_at=datetime.utcnow(),
        ))
    db.commit()
    return {"message": "Subscribed to push notifications."}


@router.get("/notifications", response_model=List[CustomerNotificationOut])
def list_my_notifications(
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """Paginated so the notification bell dropdown loads fast even after months of activity."""
    return (
        db.query(CustomerNotificationDB)
        .filter(CustomerNotificationDB.customer_id == current_customer.id)
        .order_by(CustomerNotificationDB.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.patch("/notifications/{notification_id}/read", response_model=CustomerNotificationOut)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    notification = db.query(CustomerNotificationDB).filter(
        CustomerNotificationDB.id == notification_id,
        CustomerNotificationDB.customer_id == current_customer.id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found.")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/notifications/mark-all-read")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    db.query(CustomerNotificationDB).filter(
        CustomerNotificationDB.customer_id == current_customer.id,
        CustomerNotificationDB.is_read == False,  # noqa: E712
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read."}


@router.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    notification = db.query(CustomerNotificationDB).filter(
        CustomerNotificationDB.id == notification_id,
        CustomerNotificationDB.customer_id == current_customer.id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found.")

    db.delete(notification)
    db.commit()
    return {"message": "Notification deleted."}


@router.delete("/notifications")
def clear_notifications(
    only_read: bool = Query(True, description="If true (default), only deletes already-read notifications. If false, deletes everything."),
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Bulk-clears notifications — defaults to only the already-read ones
    (the safe, "clean up what I've already seen" action a bell-icon
    clear button usually means), with `only_read=false` available for a
    genuine "clear everything" action.
    """
    query = db.query(CustomerNotificationDB).filter(CustomerNotificationDB.customer_id == current_customer.id)
    if only_read:
        query = query.filter(CustomerNotificationDB.is_read == True)  # noqa: E712
    deleted_count = query.delete()
    db.commit()
    return {"message": f"Deleted {deleted_count} notification(s)."}
