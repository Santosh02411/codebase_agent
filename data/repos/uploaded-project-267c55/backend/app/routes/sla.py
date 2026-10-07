"""
SLA routes (Phase 2): admin policy CRUD, a dispatcher-facing dashboard
of at-risk/breached deliveries, and analytics. Mirrors
routes/failed_delivery_reasons.py and routes/zones.py's shape.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.sla import SLAPolicyDB, SLAPolicyCreate, SLAPolicyUpdate, SLAPolicyOut
from app.models.delivery import DeliveryRecordDB, DeliveryRecordOut
from app.models.user import UserDB
from app.routes.admin import require_admin
from app.routes.deliveries import require_dispatcher
from app.services.sla import ACTIVE_STATUSES, compute_sla_analytics
from app.services.action_log import record_action

router = APIRouter(prefix="/admin/sla", tags=["sla"])


# ---------- Policy CRUD (admin-only) ----------

@router.get("/policies", response_model=List[SLAPolicyOut])
def list_sla_policies(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    return db.query(SLAPolicyDB).filter(
        SLAPolicyDB.org_id == current_user.org_id
    ).order_by(SLAPolicyDB.created_at.asc()).all()


@router.post("/policies", response_model=SLAPolicyOut)
def create_sla_policy(
    payload: SLAPolicyCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name can't be empty.")
    policy = SLAPolicyDB(org_id=current_user.org_id, **payload.dict())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="create",
        entity_type="sla_policy", entity_id=policy.id, entity_label=policy.name,
        summary=f"Created SLA policy '{policy.name}' ({policy.target_minutes} min).",
    )
    return policy


@router.patch("/policies/{policy_id}", response_model=SLAPolicyOut)
def update_sla_policy(
    policy_id: str,
    payload: SLAPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    policy = db.query(SLAPolicyDB).filter(
        SLAPolicyDB.id == policy_id,
        SLAPolicyDB.org_id == current_user.org_id,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="SLA policy not found.")

    updates = payload.dict(exclude_unset=True)
    for field, value in updates.items():
        setattr(policy, field, value)
    db.commit()
    db.refresh(policy)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="update",
        entity_type="sla_policy", entity_id=policy.id, entity_label=policy.name,
        summary=f"Updated SLA policy '{policy.name}'.",
    )
    return policy


@router.delete("/policies/{policy_id}")
def delete_sla_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    policy = db.query(SLAPolicyDB).filter(
        SLAPolicyDB.id == policy_id,
        SLAPolicyDB.org_id == current_user.org_id,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="SLA policy not found.")
    db.delete(policy)
    db.commit()
    return {"message": "SLA policy deleted."}


# ---------- Dispatcher dashboard ----------

@router.get("/dashboard", response_model=List[DeliveryRecordOut])
def sla_dashboard(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher)):
    """
    Every currently in-progress, SLA-tracked delivery for the org that's
    at_risk or breached, worst-first (breached before at_risk), then
    soonest deadline first — the dispatcher's actionable worklist.
    """
    deliveries = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == current_user.org_id,
        DeliveryRecordDB.status.in_(ACTIVE_STATUSES),
        DeliveryRecordDB.sla_status.in_(["at_risk", "breached"]),
    ).all()
    rank = {"breached": 0, "at_risk": 1}
    return sorted(deliveries, key=lambda d: (rank.get(d.sla_status, 2), d.sla_target_at or d.created_at))


# ---------- Analytics ----------

@router.get("/analytics")
def sla_analytics(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher)):
    return compute_sla_analytics(db, current_user.org_id)
