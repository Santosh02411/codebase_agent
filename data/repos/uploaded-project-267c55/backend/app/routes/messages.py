"""
Per-delivery messaging routes (staff side). Access rules:
- An agent can only read/send messages on deliveries ASSIGNED TO THEM.
- A dispatcher/admin can read/send messages on any delivery in their own
  organization (they're coordinating across all their agents' work).
- Everything is still org-scoped underneath — an agent or dispatcher from
  a different organization can never reach another org's delivery thread,
  same isolation guarantee as every other endpoint in this app.

Phase 6 adds: marking customer-sent messages read when staff view the
thread, notifying the customer when staff send a message, an unread
count for a "new messages" badge, and a small set of predefined quick-
reply templates. The customer side of the SAME thread lives in
routes/customer_messages.py — both routes read/write the same
DeliveryMessageDB rows and broadcast into the same chat_room(), so
there is exactly one conversation, not two.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_message import DeliveryMessageDB, MessageCreate, MessageOut
from app.models.user import UserDB, UserRole
from app.routes.auth import get_current_user
from app.services.websocket_manager import broadcast_sync, chat_room
from app.services.notifications import notify_customer_of_new_message

router = APIRouter(prefix="/deliveries", tags=["messages"])
templates_router = APIRouter(tags=["messages"])  # separate router: avoids colliding with GET /deliveries/{delivery_id} (single path segment, registered earlier in main.py)

# Predefined quick-reply templates a staff member (agent/dispatcher) can
# send with one tap instead of typing — plain strings, sent through the
# exact same send_message() endpoint below, so there's no separate
# "templated message" concept in the data model to keep in sync with
# this list; editing this list is the only thing needed to add/change one.
PREDEFINED_MESSAGES = [
    "I'm arriving in a few minutes.",
    "I'm unable to reach you — please call back when you can.",
    "Could you share your exact location?",
    "This delivery is running a bit delayed — sorry for the wait.",
]


def _get_authorized_delivery(delivery_id: str, current_user: UserDB, db: Session) -> DeliveryRecordDB:
    """Shared access check for both the GET and POST message endpoints."""
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    if delivery.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only message about your own deliveries.")

    return delivery


@templates_router.get("/message-templates")
def get_message_templates(current_user: UserDB = Depends(get_current_user)):
    return {"templates": PREDEFINED_MESSAGES}


@router.get("/{delivery_id}/messages", response_model=List[MessageOut])
def list_messages(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_authorized_delivery(delivery_id, current_user, db)
    messages = (
        db.query(DeliveryMessageDB)
        .filter(DeliveryMessageDB.delivery_id == delivery_id)
        .order_by(DeliveryMessageDB.created_at.asc())
        .all()
    )

    # Mark every customer-sent message not yet seen by staff as read —
    # "seen by staff" means seen by ANY staff member, so this is a
    # simple sweep on every authorized GET, not per-user tracking.
    now = datetime.utcnow()
    changed = False
    for m in messages:
        if m.sender_role == "customer" and m.read_by_staff_at is None:
            m.read_by_staff_at = now
            changed = True
    if changed:
        db.commit()

    return messages


@router.get("/{delivery_id}/messages/unread-count")
def get_unread_count(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_delivery(delivery_id, current_user, db)
    count = db.query(DeliveryMessageDB).filter(
        DeliveryMessageDB.delivery_id == delivery_id,
        DeliveryMessageDB.sender_role == "customer",
        DeliveryMessageDB.read_by_staff_at.is_(None),
    ).count()
    return {"unread_count": count}


@router.post("/{delivery_id}/messages", response_model=MessageOut)
def send_message(
    delivery_id: str,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_authorized_delivery(delivery_id, current_user, db)

    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    message = DeliveryMessageDB(
        delivery_id=delivery_id,
        sender_id=current_user.id,
        sender_display_name=current_user.display_name,
        sender_role=current_user.role.value,
        message=payload.message.strip(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    broadcast_sync(chat_room(delivery_id), {
        "event": "new_message",
        "message": MessageOut.model_validate(message).model_dump(mode="json"),
    })

    if delivery.customer_id:
        notify_customer_of_new_message(db, delivery_id, delivery.order_id, delivery.customer_id, current_user.display_name)

    return message
