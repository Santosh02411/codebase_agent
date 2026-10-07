"""
Enterprise organization management (Phase 16) — the org-level settings
NOT already covered by an existing, more specific settings surface:
POD rules live on OrganizationDB and are set via routes/pod.py, SLA
policies via routes/sla.py, delivery zones via routes/zones.py, pricing/
visibility/slot settings via routes/products.py's store_router. This
file adds exactly what none of those cover: branding, locale display
settings, usage metrics, self-service suspension, and a data export.

Every endpoint here is admin-only, same tier as every other
organization-configuration surface in this project.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.organization import OrganizationDB, OrganizationOut
from app.models.delivery import DeliveryRecordDB
from app.models.order import OrderDB, OrderStatus
from app.routes.admin import require_admin
from app.services.action_log import record_action

router = APIRouter(prefix="/admin/organization", tags=["organization"])

VALID_HEX_COLOR_LENGTH = {4, 7}  # "#fff" or "#ffffff"


class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None


class LocaleUpdate(BaseModel):
    timezone: Optional[str] = None
    currency_code: Optional[str] = None
    currency_symbol: Optional[str] = None


class SuspendRequest(BaseModel):
    reason: str


def _get_org(db: Session, org_id: str) -> OrganizationDB:
    org = db.query(OrganizationDB).filter(OrganizationDB.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return org


@router.patch("/branding", response_model=OrganizationOut)
def update_branding(payload: BrandingUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    org = _get_org(db, current_user.org_id)
    if payload.brand_color is not None:
        if len(payload.brand_color) not in VALID_HEX_COLOR_LENGTH or not payload.brand_color.startswith("#"):
            raise HTTPException(status_code=400, detail="brand_color must be a hex color like '#2563eb'.")
        org.brand_color = payload.brand_color
    if payload.logo_url is not None:
        org.logo_url = payload.logo_url
    db.commit()
    db.refresh(org)
    return org


@router.patch("/locale", response_model=OrganizationOut)
def update_locale(payload: LocaleUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    timezone is DISPLAY-ONLY at this point — stored so a frontend can
    show times in the org's local zone and so this is ready for a
    future feature to actually use it, but nothing in this project's
    backend currently converts stored UTC timestamps using it. Stating
    that plainly here beats quietly shipping a setting that looks like
    it does more than it does.
    """
    org = _get_org(db, current_user.org_id)
    if payload.timezone is not None:
        org.timezone = payload.timezone
    if payload.currency_code is not None:
        org.currency_code = payload.currency_code.upper()
    if payload.currency_symbol is not None:
        org.currency_symbol = payload.currency_symbol
    db.commit()
    db.refresh(org)
    return org


@router.get("/usage")
def usage_metrics(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    A snapshot of how much this org is actually using the platform —
    counts only, computed live (same "never drift from the underlying
    data" tradeoff the analytics dashboards already accept), not a
    maintained running total.
    """
    org_id = current_user.org_id
    return {
        "staff_count": db.query(UserDB).filter(UserDB.org_id == org_id).count(),
        "agent_count": db.query(UserDB).filter(UserDB.org_id == org_id, UserDB.role == UserRole.agent).count(),
        "total_deliveries": db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == org_id).count(),
        "total_orders": db.query(OrderDB).filter(OrderDB.org_id == org_id).count(),
        "paid_orders": db.query(OrderDB).filter(OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid).count(),
        "unique_customers": db.query(OrderDB.customer_id).filter(OrderDB.org_id == org_id).distinct().count(),
    }


@router.post("/suspend", response_model=OrganizationOut)
def suspend_organization(payload: SuspendRequest, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    A SELF-service "pause operations" toggle for the org's own admin —
    not a platform operator suspending a tenant from the outside
    (this project has no cross-org platform-superadmin role; every
    admin is scoped to exactly one org, so that's architecturally not
    what this endpoint can be). What it actually blocks: the org drops
    off the public storefront listing (routes/stores.py) and new
    invite-code signups (routes/auth.py) and new checkouts
    (routes/checkout.py) against this org are rejected. It does NOT
    block existing staff from logging in or managing existing
    deliveries/orders — an admin needs to still be able to operate the
    org enough to reactivate it and wind things down, which a total
    lockout would prevent.
    """
    org = _get_org(db, current_user.org_id)
    if org.is_suspended:
        raise HTTPException(status_code=400, detail="This organization is already suspended.")
    org.is_suspended = True
    org.suspended_at = datetime.utcnow()
    org.suspended_reason = payload.reason
    db.commit()
    db.refresh(org)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="organization", entity_id=org.id, entity_label=org.name,
        summary=f"Suspended organization: {payload.reason}",
    )
    return org


@router.post("/reactivate", response_model=OrganizationOut)
def reactivate_organization(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    org = _get_org(db, current_user.org_id)
    if not org.is_suspended:
        raise HTTPException(status_code=400, detail="This organization isn't suspended.")
    org.is_suspended = False
    org.suspended_at = None
    org.suspended_reason = None
    db.commit()
    db.refresh(org)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="organization", entity_id=org.id, entity_label=org.name,
        summary="Reactivated organization.",
    )
    return org


@router.get("/export")
def export_organization_data(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    A bulk JSON snapshot for backup/migration purposes — organization
    settings, staff roster (no password hashes), and delivery/order
    summaries. Deliberately NOT a dump of every single row in every
    table (deliveries/orders/messages could run into the tens of
    thousands for an established org) — this is a portable settings +
    roster + aggregate-counts export, not a full database backup;
    Phase 18's monitoring/backup work is where a real full-database
    backup belongs.
    """
    org = _get_org(db, current_user.org_id)
    org_id = current_user.org_id

    staff = db.query(UserDB).filter(UserDB.org_id == org_id).all()
    total_deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == org_id).count()
    total_orders = db.query(OrderDB).filter(OrderDB.org_id == org_id).count()

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "organization": {
            "id": org.id, "name": org.name, "created_at": org.created_at.isoformat(),
            "timezone": org.timezone, "currency_code": org.currency_code, "currency_symbol": org.currency_symbol,
            "delivery_fee": org.delivery_fee, "tax_rate_percent": org.tax_rate_percent,
            "category": org.category, "description": org.description,
        },
        "staff": [
            {"id": u.id, "username": u.username, "email": u.email, "role": u.role.value if hasattr(u.role, "value") else u.role,
             "display_name": u.display_name, "is_active": u.is_active}
            for u in staff
        ],
        "summary": {"total_deliveries": total_deliveries, "total_orders": total_orders},
    }
