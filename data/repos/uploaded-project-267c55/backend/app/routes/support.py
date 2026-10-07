"""
Customer support routes (Phase 12): a customer-facing router
(create/view/reply to their own tickets, org isolation enforced via
customer_id + org_id together) and a staff-facing router
(triage/assign/status/internal notes/resolve, dispatcher/admin only —
the same tier as RTO/returns approval elsewhere in this project).

Attachment upload reuses routes/products.py's exact validation
approach (allowed types, size cap) rather than inventing a second one,
saved to a separate uploads/support/ directory so ticket attachments
never collide with product images on disk.
"""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.models.support_ticket import (
    SupportTicketDB, SupportTicketMessageDB,
    SupportTicketCreate, SupportTicketUpdate, SupportTicketResolve, SupportTicketOut,
    TicketMessageCreate, TicketMessageOut, TicketAttachmentUploadOut,
)
from app.routes.auth import get_current_user
from app.routes.customer_auth import get_current_customer
from app.services.action_log import record_action

customer_router = APIRouter(prefix="/customer/support", tags=["support"])
admin_router = APIRouter(prefix="/admin/support", tags=["support"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "support")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "application/pdf": ".pdf",
}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

CATEGORIES = {"delivery_issue", "order_issue", "payment_issue", "product_issue", "account_issue", "other"}
PRIORITIES = {"low", "normal", "high", "urgent"}
STATUSES = {"open", "in_progress", "resolved", "closed"}


def require_dispatcher_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


# =========================================================================
# Customer-facing
# =========================================================================

@customer_router.post("/tickets", response_model=SupportTicketOut)
def create_ticket(payload: SupportTicketCreate, db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    if payload.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(CATEGORIES)}.")

    # org_id is never trusted from the client — derived from the customer's
    # own order/delivery record (or their most recent order's org, since a
    # CustomerDB spans stores in this project's marketplace model) so a
    # customer can never create a ticket in an org they haven't ordered from.
    org_id = None
    if payload.order_id:
        from app.models.order import OrderDB
        order = db.query(OrderDB).filter(OrderDB.id == payload.order_id, OrderDB.customer_id == current_customer.id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found.")
        org_id = order.org_id
    elif payload.delivery_id:
        from app.models.delivery import DeliveryRecordDB
        delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == payload.delivery_id).first()
        if not delivery or delivery.customer_id != current_customer.id:
            raise HTTPException(status_code=404, detail="Delivery not found.")
        org_id = delivery.org_id
    else:
        from app.models.order import OrderDB
        latest_order = db.query(OrderDB).filter(OrderDB.customer_id == current_customer.id).order_by(OrderDB.created_at.desc()).first()
        if not latest_order:
            raise HTTPException(status_code=400, detail="No order or delivery on file to associate this ticket with — include order_id or delivery_id.")
        org_id = latest_order.org_id

    ticket = SupportTicketDB(
        org_id=org_id, customer_id=current_customer.id,
        order_id=payload.order_id, delivery_id=payload.delivery_id,
        category=payload.category, is_dispute=payload.is_dispute,
        subject=payload.subject, description=payload.description,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@customer_router.get("/tickets", response_model=List[SupportTicketOut])
def list_my_tickets(db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    return db.query(SupportTicketDB).filter(
        SupportTicketDB.customer_id == current_customer.id,
    ).order_by(SupportTicketDB.created_at.desc()).all()


def _get_customer_ticket_or_404(db: Session, ticket_id: str, customer_id: str) -> SupportTicketDB:
    ticket = db.query(SupportTicketDB).filter(SupportTicketDB.id == ticket_id, SupportTicketDB.customer_id == customer_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ticket


@customer_router.get("/tickets/{ticket_id}", response_model=SupportTicketOut)
def get_my_ticket(ticket_id: str, db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    return _get_customer_ticket_or_404(db, ticket_id, current_customer.id)


@customer_router.get("/tickets/{ticket_id}/messages", response_model=List[TicketMessageOut])
def list_my_ticket_messages(ticket_id: str, db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    _get_customer_ticket_or_404(db, ticket_id, current_customer.id)
    # Internal notes are never returned here — this is the customer-facing view.
    return db.query(SupportTicketMessageDB).filter(
        SupportTicketMessageDB.ticket_id == ticket_id, SupportTicketMessageDB.is_internal_note == False,  # noqa: E712
    ).order_by(SupportTicketMessageDB.created_at.asc()).all()


@customer_router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut)
def reply_to_my_ticket(ticket_id: str, payload: TicketMessageCreate, db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    ticket = _get_customer_ticket_or_404(db, ticket_id, current_customer.id)
    if ticket.status == "closed":
        raise HTTPException(status_code=400, detail="This ticket is closed. Contact support to reopen it.")

    msg = SupportTicketMessageDB(
        org_id=ticket.org_id, ticket_id=ticket.id,
        sender_type="customer", sender_id=current_customer.id, sender_display_name=current_customer.name,
        message=payload.message, attachment_url=payload.attachment_url, is_internal_note=False,
    )
    db.add(msg)
    # A customer reply on a resolved ticket reopens it — silence isn't
    # "still fine", and a closed status shouldn't require staff to notice
    # a stray reply to know the issue isn't actually done.
    if ticket.status == "resolved":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return msg


@customer_router.post("/attachment", response_model=TicketAttachmentUploadOut)
async def upload_ticket_attachment(file: UploadFile = File(...), current_customer: CustomerDB = Depends(get_current_customer)):
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_ATTACHMENT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a JPEG, PNG, WebP, GIF, or PDF.")
    contents = await file.read()
    if len(contents) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="File is too large — max 5 MB.")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="That file is empty.")
    filename = f"{uuid.uuid4()}{extension}"
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(contents)
    return TicketAttachmentUploadOut(attachment_url=f"/uploads/support/{filename}")


# =========================================================================
# Staff-facing
# =========================================================================

def _get_org_ticket_or_404(db: Session, ticket_id: str, org_id: str) -> SupportTicketDB:
    ticket = db.query(SupportTicketDB).filter(SupportTicketDB.id == ticket_id, SupportTicketDB.org_id == org_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ticket


@admin_router.get("/tickets", response_model=List[SupportTicketOut])
def list_tickets(
    status: Optional[str] = None, category: Optional[str] = None, priority: Optional[str] = None,
    assigned_to_user_id: Optional[str] = None, is_dispute: Optional[bool] = None,
    db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    q = db.query(SupportTicketDB).filter(SupportTicketDB.org_id == current_user.org_id)
    if status:
        q = q.filter(SupportTicketDB.status == status)
    if category:
        q = q.filter(SupportTicketDB.category == category)
    if priority:
        q = q.filter(SupportTicketDB.priority == priority)
    if assigned_to_user_id:
        q = q.filter(SupportTicketDB.assigned_to_user_id == assigned_to_user_id)
    if is_dispute is not None:
        q = q.filter(SupportTicketDB.is_dispute == is_dispute)
    return q.order_by(SupportTicketDB.created_at.desc()).all()


@admin_router.get("/tickets/{ticket_id}", response_model=SupportTicketOut)
def get_ticket(ticket_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    return _get_org_ticket_or_404(db, ticket_id, current_user.org_id)


@admin_router.get("/tickets/{ticket_id}/messages", response_model=List[TicketMessageOut])
def list_ticket_messages(ticket_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    _get_org_ticket_or_404(db, ticket_id, current_user.org_id)
    # Staff sees everything, including internal notes.
    return db.query(SupportTicketMessageDB).filter(
        SupportTicketMessageDB.ticket_id == ticket_id,
    ).order_by(SupportTicketMessageDB.created_at.asc()).all()


@admin_router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut)
def reply_to_ticket(ticket_id: str, payload: TicketMessageCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    ticket = _get_org_ticket_or_404(db, ticket_id, current_user.org_id)
    msg = SupportTicketMessageDB(
        org_id=ticket.org_id, ticket_id=ticket.id,
        sender_type="staff", sender_id=current_user.id, sender_display_name=current_user.display_name,
        message=payload.message, attachment_url=payload.attachment_url, is_internal_note=payload.is_internal_note,
    )
    db.add(msg)
    # A staff reply that ISN'T an internal note is customer-visible progress —
    # move a brand-new ticket out of "open" into "in_progress" automatically,
    # same convention as a delivery moving out of "pending" on first agent action.
    if not payload.is_internal_note and ticket.status == "open":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return msg


@admin_router.patch("/tickets/{ticket_id}", response_model=SupportTicketOut)
def update_ticket(ticket_id: str, payload: SupportTicketUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    ticket = _get_org_ticket_or_404(db, ticket_id, current_user.org_id)

    updates = payload.dict(exclude_unset=True)
    if "status" in updates and updates["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(STATUSES)}.")
    if "priority" in updates and updates["priority"] not in PRIORITIES:
        raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(PRIORITIES)}.")
    if "category" in updates and updates["category"] not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(CATEGORIES)}.")
    if "assigned_to_user_id" in updates and updates["assigned_to_user_id"]:
        assignee = db.query(UserDB).filter(
            UserDB.id == updates["assigned_to_user_id"], UserDB.org_id == current_user.org_id,
            UserDB.role.in_([UserRole.dispatcher, UserRole.admin]),
        ).first()
        if not assignee:
            raise HTTPException(status_code=400, detail="assigned_to_user_id must be a dispatcher or admin in your organization.")

    for field, value in updates.items():
        setattr(ticket, field, value)
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="support_ticket", entity_id=ticket.id, entity_label=ticket.subject,
        summary=f"Updated support ticket '{ticket.subject}'.",
    )
    return ticket


@admin_router.post("/tickets/{ticket_id}/resolve", response_model=SupportTicketOut)
def resolve_ticket(ticket_id: str, payload: SupportTicketResolve, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    ticket = _get_org_ticket_or_404(db, ticket_id, current_user.org_id)
    if ticket.status == "closed":
        raise HTTPException(status_code=400, detail="This ticket is already closed.")

    ticket.status = "resolved"
    ticket.resolution_notes = payload.resolution_notes
    ticket.resolved_at = datetime.utcnow()
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="support_ticket", entity_id=ticket.id, entity_label=ticket.subject,
        summary=f"Resolved support ticket '{ticket.subject}'.",
    )
    return ticket


@admin_router.get("/analytics")
def support_analytics(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    tickets = db.query(SupportTicketDB).filter(SupportTicketDB.org_id == current_user.org_id).all()

    by_status = {s: 0 for s in STATUSES}
    by_category = {c: 0 for c in CATEGORIES}
    by_priority = {p: 0 for p in PRIORITIES}
    resolution_hours = []
    disputes_open = 0

    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        by_category[t.category] = by_category.get(t.category, 0) + 1
        by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        if t.is_dispute and t.status in ("open", "in_progress"):
            disputes_open += 1
        if t.resolved_at:
            resolution_hours.append((t.resolved_at - t.created_at).total_seconds() / 3600)

    return {
        "total_tickets": len(tickets),
        "by_status": by_status,
        "by_category": by_category,
        "by_priority": by_priority,
        "open_disputes": disputes_open,
        "avg_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None,
    }
