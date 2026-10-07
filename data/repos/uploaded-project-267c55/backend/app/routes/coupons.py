"""
Admin/dispatcher-facing coupon management - create, list, update
(toggle active, change limits), and delete promo codes for the org's
own storefront. The customer-facing side (applying a code at checkout)
lives in routes/checkout.py, and the shared eligibility/discount math
both sides rely on lives in services/coupons.py.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List

from app.db.session import get_db
from app.models.coupon import CouponDB, CouponCreate, CouponUpdate, CouponOut
from app.models.user import UserDB
from app.routes.deliveries import require_dispatcher
from app.services.action_log import record_action

router = APIRouter(prefix="/admin/coupons", tags=["coupons"])


@router.get("/", response_model=List[CouponOut])
def list_my_coupons(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    return (
        db.query(CouponDB)
        .filter(CouponDB.org_id == current_user.org_id)
        .order_by(CouponDB.created_at.desc())
        .all()
    )


@router.post("/", response_model=CouponOut)
def create_coupon(
    payload: CouponCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    coupon = CouponDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        code=payload.code.strip().upper(),
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        min_order_value=payload.min_order_value,
        max_uses=payload.max_uses,
        used_count=0,
        expires_at=payload.expires_at,
        is_active=payload.is_active,
        created_at=datetime.utcnow(),
    )
    db.add(coupon)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"A coupon with code \"{coupon.code}\" already exists.")
    db.refresh(coupon)
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="coupon.create", entity_type="coupon", entity_id=coupon.id,
        entity_label=coupon.code,
        summary=f"Created coupon {coupon.code}",
    )
    return coupon


@router.patch("/{coupon_id}", response_model=CouponOut)
def update_coupon(
    coupon_id: str,
    payload: CouponUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    coupon = db.query(CouponDB).filter(CouponDB.id == coupon_id, CouponDB.org_id == current_user.org_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found.")
    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(coupon, field) for field in updates}
    for field, value in updates.items():
        setattr(coupon, field, value)
    db.commit()
    db.refresh(coupon)
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="coupon.update", entity_type="coupon", entity_id=coupon.id,
        entity_label=coupon.code,
        summary=f"Updated coupon {coupon.code}",
        before=before, after=updates,
    )
    return coupon


@router.delete("/{coupon_id}")
def delete_coupon(
    coupon_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    coupon = db.query(CouponDB).filter(CouponDB.id == coupon_id, CouponDB.org_id == current_user.org_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found.")
    coupon_code = coupon.code
    db.delete(coupon)
    db.commit()
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="coupon.delete", entity_type="coupon", entity_id=coupon_id,
        entity_label=coupon_code,
        summary=f"Deleted coupon {coupon_code}",
    )
    return {"deleted": True}
