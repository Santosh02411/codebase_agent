"""
Admin management of an org's failed-delivery reason codes. See
models/failed_delivery_reason.py for the enforcement story — this
router is just CRUD; the enforcement itself lives in
routes/deliveries.py's update_delivery().

Mirrors routes/zones.py's shape (list/create/update/delete, all
admin-only, all org-scoped).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.failed_delivery_reason import (
    FailedDeliveryReasonDB,
    FailedDeliveryReasonCreate,
    FailedDeliveryReasonUpdate,
    FailedDeliveryReasonOut,
)
from app.models.user import UserDB
from app.routes.admin import require_admin

router = APIRouter(prefix="/admin/failed-delivery-reasons", tags=["failed-delivery-reasons"])


@router.get("/", response_model=List[FailedDeliveryReasonOut])
def list_reason_codes(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    Every reason code for the org, active and inactive alike — the
    admin management screen needs to show and let someone reactivate a
    retired one. Agents picking a reason during a failed delivery hit
    GET /deliveries/reason-codes/active instead, which filters to
    active=True only.
    """
    return db.query(FailedDeliveryReasonDB).filter(
        FailedDeliveryReasonDB.org_id == current_user.org_id
    ).order_by(FailedDeliveryReasonDB.created_at.asc()).all()


@router.post("/", response_model=FailedDeliveryReasonOut)
def create_reason_code(
    payload: FailedDeliveryReasonCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    code = payload.code.strip().upper().replace(" ", "_")
    if not code:
        raise HTTPException(status_code=400, detail="Code can't be empty.")
    if not payload.label.strip():
        raise HTTPException(status_code=400, detail="Label can't be empty.")

    existing = db.query(FailedDeliveryReasonDB).filter(
        FailedDeliveryReasonDB.org_id == current_user.org_id,
        FailedDeliveryReasonDB.code == code,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Reason code '{code}' already exists.")

    reason = FailedDeliveryReasonDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        code=code,
        label=payload.label.strip(),
        description=payload.description,
        active=True,
        eligible_for_rto=payload.eligible_for_rto,
        created_at=datetime.utcnow(),
    )
    db.add(reason)
    db.commit()
    db.refresh(reason)
    return reason


@router.patch("/{reason_id}", response_model=FailedDeliveryReasonOut)
def update_reason_code(
    reason_id: str,
    payload: FailedDeliveryReasonUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    reason = db.query(FailedDeliveryReasonDB).filter(
        FailedDeliveryReasonDB.id == reason_id,
        FailedDeliveryReasonDB.org_id == current_user.org_id,
    ).first()
    if not reason:
        raise HTTPException(status_code=404, detail="Reason code not found.")

    if payload.label is not None:
        if not payload.label.strip():
            raise HTTPException(status_code=400, detail="Label can't be empty.")
        reason.label = payload.label.strip()
    if payload.description is not None:
        reason.description = payload.description
    if payload.active is not None:
        reason.active = payload.active
    if payload.eligible_for_rto is not None:
        reason.eligible_for_rto = payload.eligible_for_rto

    db.commit()
    db.refresh(reason)
    return reason


@router.delete("/{reason_id}")
def delete_reason_code(
    reason_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    """
    Hard delete — allowed since attempt log rows keep their own
    denormalized reason_label copy (models/delivery_attempt.py), so
    deleting a reason code here never breaks a historical attempt's
    readability. For a code that's still actively in use, deactivating
    it (PATCH active=false) is almost always the better choice; delete
    is for cleaning up a code created by mistake.
    """
    reason = db.query(FailedDeliveryReasonDB).filter(
        FailedDeliveryReasonDB.id == reason_id,
        FailedDeliveryReasonDB.org_id == current_user.org_id,
    ).first()
    if not reason:
        raise HTTPException(status_code=404, detail="Reason code not found.")

    db.delete(reason)
    db.commit()
    return {"message": "Reason code deleted."}
