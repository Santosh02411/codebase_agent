"""
Public, unauthenticated endpoint for browsing an org's bookable
delivery time slots - what powers the "pick a delivery window" UI in
Storefront.jsx during checkout. No login required, same as browsing
the storefront's product list itself (routes/stores.py).
"""

from datetime import datetime, date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.organization import OrganizationDB, DeliverySlotOut
from app.services.slots import get_slots_for_date, MAX_ADVANCE_DAYS
from app.services.rate_limiter import limiter

router = APIRouter(prefix="/stores", tags=["delivery-slots"])


@router.get("/{org_id}/delivery-slots", response_model=List[DeliverySlotOut])
@limiter.limit("60/minute")
def list_delivery_slots(
    request: Request,
    org_id: str,
    date: date_cls = Query(..., description="YYYY-MM-DD, must be today or within the next few days"),
    db: Session = Depends(get_db),
):
    org = db.query(OrganizationDB).filter(OrganizationDB.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Store not found.")

    today = datetime.utcnow().date()
    if date < today:
        raise HTTPException(status_code=400, detail="Can't book a delivery slot in the past.")
    if (date - today).days > MAX_ADVANCE_DAYS:
        raise HTTPException(status_code=400, detail=f"Delivery slots can only be booked up to {MAX_ADVANCE_DAYS} days in advance.")

    windows = get_slots_for_date(db, org, date)
    return [
        DeliverySlotOut(start=w.start, end=w.end, available=w.available, remaining=w.remaining, capacity=w.capacity)
        for w in windows
    ]
