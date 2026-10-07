"""
Per-delivery messaging routes (customer side) — Phase 6's other half.
Reads/writes the exact same DeliveryMessageDB rows and broadcasts into
the exact same chat_room(delivery_id) as routes/messages.py's staff
side, so both sides see one shared conversation, not two separate ones.

Access rule: a customer can only read/send messages on a delivery that
belongs to THEIR OWN order (delivery.customer_id must match), same
ownership check every other customer-facing endpoint in
routes/customer_dashboard.py already uses.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_message import DeliveryMessageDB, MessageCreate, MessageOut
from app.models.customer import CustomerDB
from app.routes.customer_auth import get_current_customer
from app.services.websocket_manager import broadcast_sync, chat_room
from app.services.notifications import notify_staff_of_new_message

router = APIRouter(prefix="/customer/deliveries", tags=["messages"])


def _get_owned_delivery(delivery_id: str, current_customer: CustomerDB, db: Session) -> DeliveryRecordDB:
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return delivery


@router.get("/{delivery_id}/messages", response_model=List[MessageOut])
def list_messages_as_customer(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    _get_owned_delivery(delivery_id, current_customer, db)
    messages = (
        db.query(DeliveryMessageDB)
        .filter(DeliveryMessageDB.delivery_id == delivery_id)
        .order_by(DeliveryMessageDB.created_at.asc())
        .all()
    )

    now = datetime.utcnow()
    changed = False
    for m in messages:
        if m.sender_role != "customer" and m.read_by_customer_at is None:
            m.read_by_customer_at = now
            changed = True
    if changed:
        db.commit()

    return messages


@router.get("/{delivery_id}/messages/unread-count")
def get_unread_count_as_customer(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    _get_owned_delivery(delivery_id, current_customer, db)
    count = db.query(DeliveryMessageDB).filter(
        DeliveryMessageDB.delivery_id == delivery_id,
        DeliveryMessageDB.sender_role != "customer",
        DeliveryMessageDB.read_by_customer_at.is_(None),
    ).count()
    return {"unread_count": count}


@router.post("/{delivery_id}/messages", response_model=MessageOut)
def send_message_as_customer(
    delivery_id: str,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    delivery = _get_owned_delivery(delivery_id, current_customer, db)

    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    message = DeliveryMessageDB(
        delivery_id=delivery_id,
        sender_id=current_customer.id,
        sender_display_name=current_customer.name,
        sender_role="customer",
        message=payload.message.strip(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    broadcast_sync(chat_room(delivery_id), {
        "event": "new_message",
        "message": MessageOut.model_validate(message).model_dump(mode="json"),
    })

    notify_staff_of_new_message(db, delivery.org_id, delivery_id, delivery.order_id, delivery.agent_id, current_customer.name)

    return message
