"""
Return/exchange requests. Customer-facing creation lives under
/customer/... (mirrors the pattern of every other customer-self-serve
route); dispatcher/admin review lives under /admin/... . See
models/return_request.py's module docstring for the full workflow.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.return_request import (
    ReturnRequestDB, ReturnRequestType, ReturnRequestStatus,
    ReturnRequestCreate, ReturnRequestResolve, ReturnRequestOut,
)
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.customer import CustomerDB
from app.models.user import UserDB
from app.routes.customer_auth import get_current_customer
from app.routes.deliveries import require_dispatcher
from app.services.returns_workflow import create_return_pickup_delivery
from app.services.notification_templates import send_templated_notification
from app.services.webhooks import emit_event

customer_router = APIRouter(prefix="/customer/return-requests", tags=["returns"])
admin_router = APIRouter(prefix="/admin/return-requests", tags=["returns"])


# ---------- Customer-facing ----------

@customer_router.post("/", response_model=ReturnRequestOut)
def create_return_request(
    payload: ReturnRequestCreate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Only allowed on a delivery that's actually DELIVERED (the whole
    point of this being distinct from cancellation — see this feature's
    module docstring) and belongs to the requesting customer, with no
    other active (non-rejected) request already open on it.
    """
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == payload.delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found on your account.")
    if delivery.status != DeliveryStatus.delivered:
        raise HTTPException(status_code=400, detail="Only a delivered order can be returned or exchanged.")
    if delivery.delivery_type != "delivery":
        raise HTTPException(status_code=400, detail="This delivery isn't eligible for a return or exchange.")

    existing = db.query(ReturnRequestDB).filter(
        ReturnRequestDB.delivery_id == delivery.id,
        ReturnRequestDB.status != ReturnRequestStatus.rejected,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="There's already an active return/exchange request for this order.")

    if not payload.reason or not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Please provide a reason.")

    request = ReturnRequestDB(
        order_id=delivery.order_id,
        delivery_id=delivery.id,
        customer_id=current_customer.id,
        org_id=delivery.org_id,
        request_type=payload.request_type,
        reason=payload.reason.strip(),
        status=ReturnRequestStatus.requested,
        requested_at=datetime.utcnow(),
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    emit_event(db, request.org_id, "return.created", {
        "return_request_id": request.id, "order_id": request.order_id, "delivery_id": request.delivery_id,
        "request_type": request.request_type,
    })
    return request


@customer_router.get("/", response_model=List[ReturnRequestOut])
def list_my_return_requests(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    return (
        db.query(ReturnRequestDB)
        .filter(ReturnRequestDB.customer_id == current_customer.id)
        .order_by(ReturnRequestDB.requested_at.desc())
        .all()
    )


# ---------- Dispatcher/admin-facing ----------

@admin_router.get("/", response_model=List[ReturnRequestOut])
def list_return_requests(
    status_filter: Optional[ReturnRequestStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    query = db.query(ReturnRequestDB).filter(ReturnRequestDB.org_id == current_user.org_id)
    if status_filter:
        query = query.filter(ReturnRequestDB.status == status_filter)
    return query.order_by(ReturnRequestDB.requested_at.desc()).all()


@admin_router.post("/{request_id}/approve", response_model=ReturnRequestOut)
def approve_return_request(
    request_id: str,
    payload: ReturnRequestResolve,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Approving creates a new return_pickup delivery for an agent to
    collect the item — it lands in the normal unassigned queue exactly
    like any other delivery. The return/exchange itself completes
    automatically once that pickup delivery is marked "delivered" (see
    routes/deliveries.py's update_delivery -> handle_return_pickup_completion).
    """
    request = db.query(ReturnRequestDB).filter(
        ReturnRequestDB.id == request_id, ReturnRequestDB.org_id == current_user.org_id
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Return request not found.")
    if request.status != ReturnRequestStatus.requested:
        raise HTTPException(status_code=400, detail=f"This request is already {request.status.value}.")

    original_delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == request.delivery_id).first()
    if not original_delivery:
        raise HTTPException(status_code=404, detail="The original delivery for this request no longer exists.")

    pickup = create_return_pickup_delivery(db, request, original_delivery)

    request.status = ReturnRequestStatus.approved
    request.pickup_delivery_id = pickup.id
    request.resolution_note = payload.resolution_note
    db.commit()
    db.refresh(request)

    try:
        customer = db.query(CustomerDB).filter(CustomerDB.id == request.customer_id).first()
        send_templated_notification(
            db, org_id=current_user.org_id, event_type="return_approved", order_id=request.order_id,
            customer_id=request.customer_id, customer_email=customer.email if customer else None,
            customer_phone=original_delivery.customer_phone, delivery_id=original_delivery.id,
        )
    except Exception:
        pass  # best-effort, same tolerance as every other notification send in this project

    return request


@admin_router.post("/{request_id}/reject", response_model=ReturnRequestOut)
def reject_return_request(
    request_id: str,
    payload: ReturnRequestResolve,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    request = db.query(ReturnRequestDB).filter(
        ReturnRequestDB.id == request_id, ReturnRequestDB.org_id == current_user.org_id
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Return request not found.")
    if request.status != ReturnRequestStatus.requested:
        raise HTTPException(status_code=400, detail=f"This request is already {request.status.value}.")

    request.status = ReturnRequestStatus.rejected
    request.resolution_note = payload.resolution_note
    request.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(request)
    return request
