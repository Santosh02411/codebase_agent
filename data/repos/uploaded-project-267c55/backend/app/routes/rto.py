"""
RTO routes (Phase 7). Gated on the existing deliveries.* permissions
from Phase 4 — viewing/managing an RTO request is fundamentally a
delivery-management action, not a distinct resource, so it reuses
deliveries.view / deliveries.update rather than inventing a new
permission just for this.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.rto import RtoRequestDB, RtoStatus, RtoApproveIn, RtoCancelIn, RtoRequestOut
from app.models.organization import OrganizationDB
from app.models.user import UserDB
from app.routes.admin import require_admin
from app.services.permissions import require_permission
from app.services import rto as rto_service
from pydantic import BaseModel, Field

router = APIRouter(prefix="/admin/rto", tags=["rto"])


class RtoSettingsUpdate(BaseModel):
    rto_max_attempts: int = Field(gt=0)


@router.get("/settings")
def get_rto_settings(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
    return {"rto_max_attempts": org.rto_max_attempts if org else 3}


@router.patch("/settings")
def update_rto_settings(payload: RtoSettingsUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    org.rto_max_attempts = payload.rto_max_attempts
    db.commit()
    return {"rto_max_attempts": org.rto_max_attempts}


def _get_rto_or_404(db: Session, rto_id: str, org_id: str) -> RtoRequestDB:
    rto = db.query(RtoRequestDB).filter(RtoRequestDB.id == rto_id, RtoRequestDB.org_id == org_id).first()
    if not rto:
        raise HTTPException(status_code=404, detail="RTO request not found.")
    return rto


@router.get("/requests", response_model=List[RtoRequestOut])
def list_rto_requests(
    status: Optional[RtoStatus] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.view")),
):
    query = db.query(RtoRequestDB).filter(RtoRequestDB.org_id == current_user.org_id)
    if status:
        query = query.filter(RtoRequestDB.status == status)
    return query.order_by(RtoRequestDB.created_at.desc()).all()


@router.get("/requests/{rto_id}", response_model=RtoRequestOut)
def get_rto_request(rto_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("deliveries.view"))):
    return _get_rto_or_404(db, rto_id, current_user.org_id)


@router.post("/requests/{rto_id}/approve", response_model=RtoRequestOut)
def approve_rto_request(
    rto_id: str,
    payload: RtoApproveIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.assign")),
):
    rto = _get_rto_or_404(db, rto_id, current_user.org_id)
    try:
        return rto_service.approve_rto(db, rto, payload.note)
    except rto_service.RtoError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/requests/{rto_id}/in-transit", response_model=RtoRequestOut)
def mark_rto_in_transit_route(
    rto_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.assign")),
):
    rto = _get_rto_or_404(db, rto_id, current_user.org_id)
    try:
        return rto_service.mark_rto_in_transit(db, rto)
    except rto_service.RtoError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/requests/{rto_id}/received", response_model=RtoRequestOut)
def mark_rto_received_route(
    rto_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.assign")),
):
    rto = _get_rto_or_404(db, rto_id, current_user.org_id)
    try:
        return rto_service.mark_rto_received(db, rto)
    except rto_service.RtoError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/requests/{rto_id}/cancel", response_model=RtoRequestOut)
def cancel_rto_request(
    rto_id: str,
    payload: RtoCancelIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.assign")),
):
    rto = _get_rto_or_404(db, rto_id, current_user.org_id)
    try:
        return rto_service.cancel_rto(db, rto, payload.note)
    except rto_service.RtoError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/analytics")
def rto_analytics(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("deliveries.view"))):
    return rto_service.compute_rto_analytics(db, current_user.org_id)
