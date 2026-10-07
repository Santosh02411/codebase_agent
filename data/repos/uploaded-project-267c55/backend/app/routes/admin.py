"""
Admin routes: manage users within the admin's own organization —
view all users, deactivate/reactivate accounts, and reset a user's
password directly.

Honest limitation, worth stating plainly: there's no email service
available (no budget for one), so "reset password" here means the admin
sets a new password directly and communicates it to the user
out-of-band (in person, chat, etc.) — NOT an emailed reset link, which is
what a production system would use instead. This is documented as a
known gap in docs/SECURITY_AND_ACCESS.md.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole, UserOut
from app.models.organization import OrganizationDB, OrganizationOut
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_history import DeliveryHistoryDB
from app.models.action_log import ActionLogDB, ActionLogOut
from app.routes.auth import get_current_user
from app.services.auth import hash_password
from app.services.action_log import record_action

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admins can do this.")
    return current_user


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("/organization", response_model=OrganizationOut)
def get_my_organization(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    """
    Returns the admin's own organization, including its invite_code — this
    is what makes good on the promise shown at signup ("any admin can look
    it up later"), since the code is otherwise only ever shown once, at
    the moment the organization is first created.
    """
    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return org


@router.get("/users", response_model=List[UserOut])
def list_organization_users(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    """List every user (agent, dispatcher, admin) in the admin's own organization."""
    return db.query(UserDB).filter(UserDB.org_id == current_user.org_id).all()


@router.patch("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account.")

    target = db.query(UserDB).filter(
        UserDB.id == user_id, UserDB.org_id == current_user.org_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your organization.")

    target.is_active = False
    db.commit()
    db.refresh(target)
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="user.deactivate", entity_type="user", entity_id=target.id,
        entity_label=target.display_name,
        summary=f"Deactivated user {target.display_name}",
    )
    return target


@router.patch("/users/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    target = db.query(UserDB).filter(
        UserDB.id == user_id, UserDB.org_id == current_user.org_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your organization.")

    target.is_active = True
    db.commit()
    db.refresh(target)
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="user.activate", entity_type="user", entity_id=target.id,
        entity_label=target.display_name,
        summary=f"Reactivated user {target.display_name}",
    )
    return target


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    target = db.query(UserDB).filter(
        UserDB.id == user_id, UserDB.org_id == current_user.org_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your organization.")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")

    target.hashed_password = hash_password(payload.new_password)
    db.commit()
    record_action(
        db, org_id=current_user.org_id,
        actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="user.reset_password", entity_type="user", entity_id=target.id,
        entity_label=target.display_name,
        summary=f"Reset password for {target.display_name}",
    )
    return {"success": True, "message": f"Password reset for {target.display_name}."}


# ---------- Audit log viewer ----------
# Browses the delivery status-change history (DeliveryHistoryDB) that
# already gets written on every status change — see services/history.py.
# That table has existed since early in the project (it's what powers
# the per-delivery "history" timeline agents/dispatchers already see),
# but there was no UI to browse it BROADLY, across every delivery in the
# organization at once, filterable by who made the change and when. This
# is that missing admin-facing view — "who changed what, when" as a
# proper audit trail rather than something you can only see one delivery
# at a time.
#
# DeliveryHistoryDB doesn't store org_id directly (it's a child record of
# a delivery, not a top-level tenant-scoped table), so every query here
# joins through DeliveryRecordDB to enforce the same multi-tenant
# isolation as everywhere else in the app: an admin only ever sees audit
# entries for deliveries that belong to their own organization.

class AuditLogEntryOut(BaseModel):
    id: str
    delivery_id: str
    delivery_order_id: str
    changed_by_display_name: str
    old_status: Optional[str] = None
    new_status: str
    changed_at: datetime
    note: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/audit-log", response_model=List[AuditLogEntryOut])
def get_audit_log(
    date_from: Optional[date] = Query(None, description="Include entries changed on/after this date"),
    date_to: Optional[date] = Query(None, description="Include entries changed on/before this date"),
    changed_by_user_id: Optional[str] = Query(None, description="Filter to changes made by one user"),
    order_id: Optional[str] = Query(None, description="Filter by delivery order ID (partial match)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    query = (
        db.query(DeliveryHistoryDB, DeliveryRecordDB.order_id)
        .join(DeliveryRecordDB, DeliveryHistoryDB.delivery_id == DeliveryRecordDB.id)
        .filter(DeliveryRecordDB.org_id == current_user.org_id)
    )

    if date_from:
        query = query.filter(DeliveryHistoryDB.changed_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(DeliveryHistoryDB.changed_at <= datetime.combine(date_to, datetime.max.time()))
    if changed_by_user_id:
        query = query.filter(DeliveryHistoryDB.changed_by_user_id == changed_by_user_id)
    if order_id:
        query = query.filter(DeliveryRecordDB.order_id.ilike(f"%{order_id}%"))

    rows = (
        query.order_by(DeliveryHistoryDB.changed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        AuditLogEntryOut(
            id=history.id,
            delivery_id=history.delivery_id,
            delivery_order_id=order_id_value,
            changed_by_display_name=history.changed_by_display_name,
            old_status=history.old_status,
            new_status=history.new_status,
            changed_at=history.changed_at,
            note=history.note,
        )
        for history, order_id_value in rows
    ]


# ---------- General admin action log (users, products, coupons, store settings) ----------
# Separate from the delivery status-change audit log above — this is
# "who changed what, when" for every OTHER admin write action. Written
# to by admin.py itself (user management), products.py (product CRUD +
# store settings), and coupons.py (coupon CRUD) via
# services/action_log.py.

@router.get("/action-log", response_model=List[ActionLogOut])
def get_action_log(
    action: Optional[str] = Query(None, description="Filter by exact action, e.g. product.update"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type, e.g. product, user, coupon"),
    actor_user_id: Optional[str] = Query(None, description="Filter to actions taken by one user"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    query = db.query(ActionLogDB).filter(ActionLogDB.org_id == current_user.org_id)

    if action:
        query = query.filter(ActionLogDB.action == action)
    if entity_type:
        query = query.filter(ActionLogDB.entity_type == entity_type)
    if actor_user_id:
        query = query.filter(ActionLogDB.actor_user_id == actor_user_id)

    return (
        query.order_by(ActionLogDB.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
