"""
Advanced routing routes (Phase 9). Per-delivery endpoints follow the
same "own delivery for an agent, any org delivery for dispatcher/admin"
access pattern used throughout this project (routes/pod.py, routes/scan.py);
org-wide endpoints (heatmap, multi-agent optimization) are gated on
deliveries.view / deliveries.assign from Phase 4.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.location_history import LocationHistoryPointOut
from app.models.user import UserDB, UserRole
from app.services.permissions import require_permission
from app.services.route_analytics import (
    compute_dynamic_eta, detect_route_deviation, get_route_replay,
    compute_route_efficiency, compute_delivery_heatmap, optimize_multi_agent_routes,
)
from app.routes.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(tags=["routing"])


def _get_delivery_or_404(db: Session, delivery_id: str, org_id: str) -> DeliveryRecordDB:
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id, DeliveryRecordDB.org_id == org_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return delivery


def _require_route_access(delivery: DeliveryRecordDB, current_user: UserDB) -> None:
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view routing info for your own assigned deliveries.")


@router.get("/deliveries/{delivery_id}/eta")
def get_dynamic_eta(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_route_access(delivery, current_user)
    eta = compute_dynamic_eta(db, delivery)
    if eta is None:
        raise HTTPException(status_code=404, detail="No live ETA available yet — the agent may not have shared a location, or the delivery has no destination coordinates.")
    return eta


@router.get("/deliveries/{delivery_id}/route-deviation")
def get_route_deviation(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_route_access(delivery, current_user)
    result = detect_route_deviation(db, delivery)
    return result or {"deviated": False}


@router.get("/deliveries/{delivery_id}/route-replay", response_model=List[LocationHistoryPointOut])
def get_route_replay_route(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_route_access(delivery, current_user)
    return get_route_replay(db, delivery_id)


@router.get("/deliveries/{delivery_id}/route-efficiency")
def get_route_efficiency(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_route_access(delivery, current_user)
    result = compute_route_efficiency(db, delivery)
    if result is None:
        raise HTTPException(status_code=404, detail="Not enough location history for this delivery yet.")
    return result


@router.get("/admin/routing/heatmap")
def get_delivery_heatmap(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("deliveries.view"))):
    return {"points": compute_delivery_heatmap(db, current_user.org_id)}


class AgentStart(BaseModel):
    latitude: float
    longitude: float


class MultiAgentOptimizeIn(BaseModel):
    agent_starts: Dict[str, AgentStart]


@router.post("/admin/routing/optimize-multi-agent")
def optimize_multi_agent(
    payload: MultiAgentOptimizeIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.assign")),
):
    agent_starts = {agent_id: start.dict() for agent_id, start in payload.agent_starts.items()}
    routes = optimize_multi_agent_routes(db, current_user.org_id, agent_starts)
    return {"routes": routes}
