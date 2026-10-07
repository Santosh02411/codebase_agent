"""
Routes for delivery records: create, update, list, delete, and role-specific
views (a dispatcher's full list vs. an agent's assigned-to-them list).

Every query in this file filters by `current_user.org_id` — this is what
makes multi-tenant isolation actually hold: two organizations sharing the
same deployment never see each other's deliveries, even though they're
all rows in the same physical `deliveries` table.

The offline sync flow (bulk upload with conflict resolution) lives
separately in routes/sync.py, since it has different logic (see
docs/TECHNICAL_ARCHITECTURE.md).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from app.db.session import get_db
from app.models.delivery import (
    DeliveryRecordDB,
    DeliveryRecordCreate,
    DeliveryRecordUpdate,
    DeliveryRecordOut,
    DeliveryStatus,
    DeliveryPriority,
    PRIORITY_RANK,
)
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.models.delivery_history import DeliveryHistoryDB, DeliveryHistoryOut
from app.models.failed_delivery_reason import FailedDeliveryReasonDB, FailedDeliveryReasonOut
from app.models.delivery_attempt import DeliveryAttemptDB, DeliveryAttemptOut
from app.services.history import record_history_entry
from app.services.delivery_attempts import record_delivery_attempt
from app.services.notifications import notify_customer_of_status_change, notify_agent_of_new_assignment, notify_agent_of_unassignment
from app.services.refund import refund_order_for_delivery
from app.services.returns_workflow import handle_return_pickup_completion
from app.services.websocket_manager import broadcast_sync, dispatcher_queue_room, tracking_room
from app.models.agent_location import AgentLocationDB
from app.models.zone import ZoneDB, AgentZoneAssignmentDB
from app.services.geo import haversine_km, find_zone_for_point
from app.services.routing import get_route_distance, optimize_stop_order
from app.models.organization import OrganizationDB
from app.models.proof_of_delivery import ProofOfDeliveryDB
from app.services.pod import org_requires_any_pod, pod_exists_for_delivery
from app.services.sla import assign_sla, classify_on_completion
from app.services import fleet as fleet_service
from app.services.webhooks import emit_event

REAL_ROUTING_TOP_K = 3  # how many top-tier candidates get a real routing call, per suggested-agents/auto-assign request
from app.routes.auth import get_current_user

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


def require_dispatcher(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    """
    FastAPI dependency allowing dispatchers AND admins through (an admin
    has a superset of dispatcher permissions within their own
    organization). Used on routes like creating/assigning a delivery, or
    viewing the full cross-agent list.
    """
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


def _sort_by_priority(deliveries: list) -> list:
    """
    Orders a list of deliveries urgent -> high -> normal -> low, and
    within the same priority tier, oldest-created first (so two
    "urgent" deliveries still queue fairly by whoever's been waiting
    longer, rather than in arbitrary DB row order). Done in Python
    rather than an ORDER BY clause because `priority` is a free-text-ish
    string column (see DeliveryPriority's docstring), and mapping it to
    a rank for SQL ordering would need a CASE expression per dialect —
    not worth it at this project's data scale, where the dispatcher
    queue is at most a few hundred rows.
    """
    return sorted(
        deliveries,
        key=lambda d: (-PRIORITY_RANK.get(d.priority, PRIORITY_RANK[DeliveryPriority.normal.value]), d.created_at),
    )


@router.post("/", response_model=DeliveryRecordOut)
def create_delivery(
    record: DeliveryRecordCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Create and assign a new delivery record to a specific agent.

    Dispatcher/admin-only: picks which agent (record.agent_id) this
    delivery is assigned to. The agent must belong to the SAME
    organization as the person assigning it — org_id is set here from
    the current user's own organization, never trusted from client input,
    so a dispatcher can never (even accidentally) create a delivery
    tagged to a different organization.
    """
    existing = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == record.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Delivery record with this ID already exists")

    # Confirm the target agent actually exists, is really an agent, AND
    # belongs to the same organization as the person assigning this
    target_agent = db.query(UserDB).filter(
        UserDB.id == record.agent_id,
        UserDB.org_id == current_user.org_id,
    ).first()
    if not target_agent or target_agent.role != UserRole.agent:
        raise HTTPException(status_code=400, detail="The selected agent doesn't exist in your organization.")

    db_record = DeliveryRecordDB(**record.model_dump(), org_id=current_user.org_id)
    # Coerce explicitly to the plain string value the column stores —
    # record.priority may come through model_dump() as a DeliveryPriority
    # enum member rather than its raw string, and the `priority` column
    # is a plain String (see DeliveryPriority's docstring for why).
    db_record.priority = (record.priority or DeliveryPriority.normal).value

    # Link to a real customer account if one exists matching this email —
    # that's what makes this delivery show up in that customer's logged-in
    # dashboard, not just via a one-off tracking link.
    if db_record.customer_email:
        matching_customer = db.query(CustomerDB).filter(CustomerDB.email == db_record.customer_email).first()
        if matching_customer:
            db_record.customer_id = matching_customer.id

    # SLA (Phase 2): pick the best-matching active policy for this
    # org/zone/type/priority combination and compute a deadline, now
    # that zone/delivery_type/priority/created_at are all final.
    assign_sla(db, db_record)

    db.add(db_record)
    db.commit()
    db.refresh(db_record)

    record_history_entry(
        db,
        delivery_id=db_record.id,
        changed_by_user_id=current_user.id,
        changed_by_display_name=current_user.display_name,
        old_status=None,
        new_status=db_record.status,
        changed_at=db_record.created_at,
        note=f"Created and assigned to {target_agent.display_name}",
    )
    notify_customer_of_status_change(
        db,
        delivery_id=db_record.id,
        order_id=db_record.order_id,
        new_status="confirmed",
        customer_email=db_record.customer_email,
        customer_phone=db_record.customer_phone,
        customer_id=db_record.customer_id,
    )
    notify_agent_of_new_assignment(db, delivery_id=db_record.id, order_id=db_record.order_id, agent_id=target_agent.id)

    return db_record


@router.get("/unassigned", response_model=List[DeliveryRecordOut])
def list_unassigned_deliveries(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Orders placed by customers through checkout, paid for, but not yet
    assigned to an agent — the dispatcher's "new orders" queue. Manually
    dispatcher-created deliveries never land here since they always pick
    an agent at creation time.
    """
    unassigned = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == current_user.org_id,
        DeliveryRecordDB.status == DeliveryStatus.pending,
    ).all()
    return _sort_by_priority(unassigned)


@router.get("/reason-codes/active", response_model=List[FailedDeliveryReasonOut])
def list_active_reason_codes(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    The picker an agent sees when marking a delivery attempt failed —
    active reason codes only (a deactivated one shouldn't be pickable
    for a NEW attempt, even though old attempts that already used it
    keep displaying fine via their own denormalized reason_label).
    Any authenticated org member can read this (agent, dispatcher, or
    admin); only an admin can manage the underlying list (see
    routes/failed_delivery_reasons.py).
    """
    return db.query(FailedDeliveryReasonDB).filter(
        FailedDeliveryReasonDB.org_id == current_user.org_id,
        FailedDeliveryReasonDB.active == True,  # noqa: E712
    ).order_by(FailedDeliveryReasonDB.label.asc()).all()


class AssignAgentRequest(BaseModel):
    agent_id: str


def _apply_agent_assignment(db: Session, current_user: UserDB, db_record: DeliveryRecordDB, target_agent: UserDB) -> DeliveryRecordDB:
    """
    Shared by the manual "pick an agent from the list" flow
    (assign_agent_to_delivery) and the "just assign the best one"
    one-click flow (auto_assign_delivery) — both end up doing the exact
    same state change, history entry, and notifications, so this is the
    one place that logic lives.
    """
    old_status = db_record.status
    db_record.agent_id = target_agent.id
    db_record.status = DeliveryStatus.picked_up
    db_record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_record)

    record_history_entry(
        db,
        delivery_id=db_record.id,
        changed_by_user_id=current_user.id,
        changed_by_display_name=current_user.display_name,
        old_status=old_status,
        new_status=db_record.status,
        changed_at=db_record.updated_at,
        note=f"Assigned to {target_agent.display_name}",
    )
    notify_customer_of_status_change(
        db,
        delivery_id=db_record.id,
        order_id=db_record.order_id,
        new_status=db_record.status.value,
        customer_email=db_record.customer_email,
        customer_phone=db_record.customer_phone,
        customer_id=db_record.customer_id,
    )
    notify_agent_of_new_assignment(db, delivery_id=db_record.id, order_id=db_record.order_id, agent_id=target_agent.id)
    broadcast_sync(dispatcher_queue_room(db_record.org_id), {"event": "queue_changed", "reason": "assigned"})
    broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})
    emit_event(db, db_record.org_id, "delivery.assigned", {
        "delivery_id": db_record.id, "order_id": db_record.order_id, "agent_id": target_agent.id,
    })
    return db_record


class AgentSuggestionOut(BaseModel):
    agent_id: str
    display_name: str
    distance_km: Optional[float] = None  # None if this agent has no live location, or the delivery has no coordinates to compare against
    active_delivery_count: int
    has_location: bool
    area_name: Optional[str] = None
    zone_match: bool = False  # True when this agent's detected area matches the delivery's free-text `zone` field
    covers_matched_zone: bool = False  # True when this agent is an assigned coverer of the real Zone (see models/zone.py) the delivery's coordinates fall inside
    routed: bool = False  # True when distance_km is a real road distance (services/routing.py), False when it's straight-line haversine
    vehicle_capacity_warning: Optional[str] = None  # Phase 11: set when this agent's assigned vehicle has a unit capacity that active_delivery_count + 1 would exceed. Advisory only — never affects ranking or blocks assignment.


class SuggestedAgentsOut(BaseModel):
    suggestions: List[AgentSuggestionOut]
    ranked_by_distance: bool  # False when the delivery has no coordinates — suggestions fall back to workload-only ranking
    matched_zone_id: Optional[str] = None
    matched_zone_name: Optional[str] = None
    zone_restricted: bool = False  # True when auto-assign would restrict candidates to the matched zone's coverers (POST /auto-assign only — this endpoint never hard-filters, just reports what auto-assign would do)
    used_real_routing: bool = False  # True when at least one candidate's distance reflects real road distance rather than straight-line


def _zone_matches_area(zone: Optional[str], area_name: Optional[str]) -> bool:
    """
    Loose, case-insensitive match between a delivery's dispatcher-entered
    `zone` and an agent's GPS-detected `area_name` — checks each as a
    substring of the other so "Koramangala" (agent's real detected area)
    matches a zone entered as "Koramangala, Bengaluru" or just
    "koramangala", without requiring an exact string match that would
    be fragile in practice.
    """
    if not zone or not area_name:
        return False
    zone_norm = zone.strip().lower()
    area_norm = area_name.strip().lower()
    if not zone_norm or not area_norm:
        return False
    return zone_norm in area_norm or area_norm in zone_norm


def _rank_agents_for_delivery(db: Session, org_id: str, db_record: DeliveryRecordDB):
    """
    Core of "smart assignment": ranks every agent in the org by how good
    a fit they are for one specific delivery, using the same live GPS
    data already being collected for the customer tracking map
    (AgentLocationDB) — previously collected but never actually used to
    help a dispatcher decide who to assign.

    Ranking, in order:
    1. Real Zone coverage FIRST — if the delivery's coordinates fall
       inside an admin-defined Zone (models/zone.py — a real circular
       territory, not just a string), agents assigned to COVER that
       zone are placed ahead of everyone else. This is what
       POST /auto-assign actually restricts to (see there); this
       function still ranks and returns every agent so a dispatcher
       manually assigning retains full override power.
    2. Free-text zone match — an agent whose GPS-detected coverage area
       (UserDB.area_name) matches this delivery's `zone` string is
       placed ahead of any remaining non-matching agents. This is the
       older, looser signal — still useful for orgs that haven't set up
       formal Zones yet, or for a delivery whose coordinates don't fall
       inside any defined Zone.
    3. Within each of those groups, distance from the agent's last-known
       position to the delivery's coordinates (haversine, straight-line
       — good enough for ranking without a paid routing API).
    4. Workload (active delivery count) as the final tiebreaker.

    Falls back gracefully at every level: no matched zone, no zone on
    the delivery, no area on an agent, no coordinates, no shared
    location — all just mean that particular signal doesn't contribute,
    not that ranking fails.

    Returns (suggestions, ranked_by_distance, matched_zone) where
    matched_zone is the ZoneDB row the delivery's coordinates fall
    inside, or None.
    """
    agents = db.query(UserDB).filter(UserDB.org_id == org_id, UserDB.role == UserRole.agent).all()
    if not agents:
        return [], False, None

    locations = {
        loc.agent_id: loc
        for loc in db.query(AgentLocationDB).filter(AgentLocationDB.agent_id.in_([a.id for a in agents])).all()
    }

    delivery_lat = delivery_lon = None
    if db_record.latitude and db_record.longitude:
        try:
            delivery_lat = float(db_record.latitude)
            delivery_lon = float(db_record.longitude)
        except (TypeError, ValueError):
            delivery_lat = delivery_lon = None
    ranked_by_distance = delivery_lat is not None and delivery_lon is not None

    matched_zone = None
    covering_agent_ids = set()
    if ranked_by_distance:
        org_zones = db.query(ZoneDB).filter(ZoneDB.org_id == org_id).all()
        matched_zone = find_zone_for_point(org_zones, delivery_lat, delivery_lon)
        if matched_zone:
            covering_agent_ids = {
                row.agent_id for row in
                db.query(AgentZoneAssignmentDB).filter(AgentZoneAssignmentDB.zone_id == matched_zone.id).all()
            }

    suggestions = []
    for agent in agents:
        active_count = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.org_id == org_id,
            DeliveryRecordDB.agent_id == agent.id,
            DeliveryRecordDB.status.in_([DeliveryStatus.picked_up, DeliveryStatus.out_for_delivery]),
        ).count()

        location = locations.get(agent.id)
        distance_km = None
        if ranked_by_distance and location:
            distance_km = round(haversine_km(delivery_lat, delivery_lon, location.latitude, location.longitude), 2)

        suggestions.append(AgentSuggestionOut(
            agent_id=agent.id,
            display_name=agent.display_name,
            distance_km=distance_km,
            active_delivery_count=active_count,
            has_location=location is not None,
            area_name=agent.area_name,
            zone_match=_zone_matches_area(db_record.zone, agent.area_name),
            covers_matched_zone=agent.id in covering_agent_ids,
            vehicle_capacity_warning=fleet_service.capacity_warning(db, agent.id, org_id, active_count + 1),
        ))

    # Sort: zone-coverers first, then free-text zone-matched agents,
    # then agents with a computed distance (nearest first), then
    # workload as the final tiebreaker; agents with no distance
    # available sort after, ordered by workload alone within their group.
    suggestions.sort(key=lambda s: (
        not s.covers_matched_zone,
        not s.zone_match,
        s.distance_km is None,
        s.distance_km if s.distance_km is not None else 0,
        s.active_delivery_count,
    ))

    # Real-routing refinement: replace haversine with actual road
    # distance for a small, bounded set of candidates — specifically
    # the leading run that already shares the TOP priority tier
    # (zone-coverage / zone-match), never mixed across tiers, so a real
    # route can never let a non-zone-covering agent leapfrog a
    # zone-covering one just because the road happens to be shorter —
    # that would silently undermine the zone restriction this same
    # function enforces. See services/routing.py's module docstring for
    # why this is bounded to a handful of candidates rather than every
    # agent: a real routing call is neither free nor instant the way
    # haversine is.
    if suggestions and ranked_by_distance:
        top_tier_key = (suggestions[0].covers_matched_zone, suggestions[0].zone_match)
        run_end = 0
        while run_end < len(suggestions) and (suggestions[run_end].covers_matched_zone, suggestions[run_end].zone_match) == top_tier_key:
            run_end += 1

        candidates = [s for s in suggestions[:run_end] if s.has_location][:REAL_ROUTING_TOP_K]
        if candidates:
            for s in candidates:
                location = locations[s.agent_id]
                real = get_route_distance(delivery_lat, delivery_lon, location.latitude, location.longitude)
                if real:
                    s.distance_km = round(real["distance_km"], 2)
                    s.routed = True
            top_run = suggestions[:run_end]
            top_run.sort(key=lambda s: (s.distance_km is None, s.distance_km if s.distance_km is not None else 0, s.active_delivery_count))
            suggestions = top_run + suggestions[run_end:]

    return suggestions, ranked_by_distance, matched_zone


@router.get("/{delivery_id}/suggested-agents", response_model=SuggestedAgentsOut)
def get_suggested_agents(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Ranked agent suggestions for one delivery — nearest-by-live-GPS
    first, workload as tiebreaker — so a dispatcher isn't just picking
    blind from an alphabetical list. Doesn't assign anything itself; see
    POST /{delivery_id}/auto-assign for the one-click version.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    suggestions, ranked_by_distance, matched_zone = _rank_agents_for_delivery(db, current_user.org_id, db_record)
    zone_has_coverers = bool(matched_zone and any(s.covers_matched_zone for s in suggestions))
    return SuggestedAgentsOut(
        suggestions=suggestions,
        ranked_by_distance=ranked_by_distance,
        matched_zone_id=matched_zone.id if matched_zone else None,
        matched_zone_name=matched_zone.name if matched_zone else None,
        zone_restricted=zone_has_coverers,
        used_real_routing=any(s.routed for s in suggestions),
    )


@router.post("/{delivery_id}/auto-assign", response_model=DeliveryRecordOut)
def auto_assign_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    One-click "just assign the best agent" — computes the same ranking
    as GET /suggested-agents and assigns the top result, with no
    dispatcher pick required. Same eligibility rule as the manual assign
    endpoint: only unassigned customer (checkout) orders can be assigned
    this way.

    REAL zone restriction happens here (not just ranking): if the
    delivery's coordinates fall inside an admin-defined Zone that has at
    least one agent assigned to cover it, candidates are hard-filtered
    to ONLY those covering agents before picking the best one — an
    auto-assign inside a defined zone can never silently hand the
    delivery to someone who doesn't cover that territory. Falls back to
    org-wide ranking when there's no matched zone, or the matched zone
    has no covering agents assigned yet (an empty zone can't block
    deliveries from being assigned at all).
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    if db_record.status != DeliveryStatus.pending or not db_record.customer_id:
        raise HTTPException(status_code=400, detail="Only unassigned customer orders can be assigned this way.")

    suggestions, _, matched_zone = _rank_agents_for_delivery(db, current_user.org_id, db_record)
    if not suggestions:
        raise HTTPException(status_code=400, detail="There are no agents in your organization to assign.")

    zone_coverers = [s for s in suggestions if s.covers_matched_zone]
    if matched_zone and zone_coverers:
        # Real restriction: only agents covering the matched zone are
        # eligible at all — already sorted first by _rank_agents_for_delivery,
        # but filtering explicitly here makes the restriction airtight
        # rather than just "probably first in the list".
        candidates = zone_coverers
    else:
        candidates = suggestions

    best = candidates[0]
    target_agent = db.query(UserDB).filter(UserDB.id == best.agent_id, UserDB.org_id == current_user.org_id).first()
    return _apply_agent_assignment(db, current_user, db_record, target_agent)


@router.patch("/{delivery_id}/assign-agent", response_model=DeliveryRecordOut)
def assign_agent_to_delivery(
    delivery_id: str,
    payload: AssignAgentRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Dispatcher assigns a customer-placed (checkout) order to an agent.

    Deliberately restricted to orders still in `pending` status — that
    status is ONLY ever set by the checkout flow (see routes/checkout.py),
    never by a dispatcher's manual delivery creation, which always picks
    an agent immediately. So this guard is what actually enforces "only
    real customer orders can be assigned/reassigned here, never an
    arbitrary already-fulfilled or manually-created delivery."
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    if db_record.status != DeliveryStatus.pending or not db_record.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Only unassigned customer orders can be assigned this way.",
        )

    target_agent = db.query(UserDB).filter(
        UserDB.id == payload.agent_id,
        UserDB.org_id == current_user.org_id,
    ).first()
    if not target_agent or target_agent.role != UserRole.agent:
        raise HTTPException(status_code=400, detail="The selected agent doesn't exist in your organization.")

    return _apply_agent_assignment(db, current_user, db_record, target_agent)


@router.patch("/{delivery_id}/return-to-pool", response_model=DeliveryRecordOut)
def return_delivery_to_pool(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Dispatcher pulls a customer order back off its currently-assigned
    agent and drops it back into the unassigned pool (GET
    /deliveries/unassigned), so it can be picked up by — or handed to —
    a different agent. Mirrors assign_agent_to_delivery()'s own
    restriction to customer-placed (checkout) orders, since a manually
    created delivery has no "pool" to return to (it always has an
    agent from creation). Only makes sense before the agent has
    actually moved the package (picked_up is the "just assigned, not
    yet touched" state) — once it's out_for_delivery, delivered, or
    cancelled, returning it to the pool would be confusing rather than
    useful, so those are rejected the same way bulk-assign-agent
    rejects delivered/cancelled.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    if not db_record.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Only customer-placed orders can be returned to the unassigned pool.",
        )
    if db_record.status != DeliveryStatus.picked_up:
        raise HTTPException(
            status_code=400,
            detail="Only a just-assigned order (not yet out for delivery, delivered, or cancelled) can be returned to the pool.",
        )

    old_agent_id = db_record.agent_id
    old_agent = db.query(UserDB).filter(UserDB.id == old_agent_id).first() if old_agent_id else None
    now = datetime.utcnow()

    db_record.agent_id = None
    db_record.status = DeliveryStatus.pending
    db_record.updated_at = now
    db.commit()
    db.refresh(db_record)

    record_history_entry(
        db,
        delivery_id=db_record.id,
        changed_by_user_id=current_user.id,
        changed_by_display_name=current_user.display_name,
        old_status=DeliveryStatus.picked_up,
        new_status=db_record.status,
        changed_at=now,
        note=f"Returned to unassigned pool by {current_user.display_name}"
        + (f" (was assigned to {old_agent.display_name})" if old_agent else ""),
    )
    if old_agent_id:
        notify_agent_of_unassignment(db, delivery_id=db_record.id, order_id=db_record.order_id, agent_id=old_agent_id)
    broadcast_sync(dispatcher_queue_room(current_user.org_id), {"event": "queue_changed", "reason": "returned_to_pool"})
    broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})
    return db_record


class BulkStatusUpdateRequest(BaseModel):
    delivery_ids: List[str]
    status: DeliveryStatus


class BulkAssignAgentRequest(BaseModel):
    delivery_ids: List[str]
    agent_id: str


class BulkActionItemResult(BaseModel):
    delivery_id: str
    success: bool
    error: Optional[str] = None


class BulkActionResponse(BaseModel):
    results: List[BulkActionItemResult]
    success_count: int
    failure_count: int


@router.patch("/bulk-status", response_model=BulkActionResponse)
def bulk_update_status(
    payload: BulkStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Apply one status to many deliveries at once — the dispatcher table's
    "select rows, bulk-update" action. Deliberately partial-success
    rather than all-or-nothing (same choice bulk_import_deliveries makes
    for the same reason): one delivery in a large selection belonging to
    another org, already deleted, or otherwise invalid shouldn't block
    the other 49 from updating. Each delivery still goes through the
    exact same history-entry / customer-notify / refund-on-cancel /
    return-pickup-on-delivered side effects a single-record status
    update would, by reusing the same helpers update_delivery() uses —
    so a bulk update is indistinguishable downstream from doing the same
    updates one at a time.

    Deliberately does NOT support bulk-moving deliveries to
    failed_attempt: that status requires a real, specific reason code
    per delivery (see update_delivery()'s enforcement), and one shared
    reason across an arbitrary batch would defeat the point of having
    standardized, meaningful reason codes at all. Use the single-record
    PATCH /deliveries/{id} for that.
    """
    if payload.status == DeliveryStatus.failed_attempt:
        raise HTTPException(
            status_code=400,
            detail="Marking a delivery failed requires a specific reason code — update deliveries individually for this status.",
        )

    results: List[BulkActionItemResult] = []

    for delivery_id in payload.delivery_ids:
        db_record = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.id == delivery_id,
            DeliveryRecordDB.org_id == current_user.org_id,
        ).first()
        if not db_record:
            results.append(BulkActionItemResult(delivery_id=delivery_id, success=False, error="Not found"))
            continue

        old_status = db_record.status
        if old_status == payload.status:
            results.append(BulkActionItemResult(delivery_id=delivery_id, success=True))
            continue

        now = datetime.utcnow()
        db_record.status = payload.status
        db_record.updated_at = now
        db.commit()
        db.refresh(db_record)

        record_history_entry(
            db,
            delivery_id=db_record.id,
            changed_by_user_id=current_user.id,
            changed_by_display_name=current_user.display_name,
            old_status=old_status,
            new_status=payload.status,
            changed_at=now,
            note="Updated via bulk action",
        )
        notify_customer_of_status_change(
            db,
            delivery_id=db_record.id,
            order_id=db_record.order_id,
            new_status=db_record.status.value,
            customer_email=db_record.customer_email,
            customer_phone=db_record.customer_phone,
            customer_id=db_record.customer_id,
        )
        broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})

        if payload.status == DeliveryStatus.cancelled:
            refund_order_for_delivery(db, db_record.id)
        if payload.status == DeliveryStatus.delivered:
            handle_return_pickup_completion(db, db_record)
            record_delivery_attempt(
                db, db_record, agent_id=db_record.agent_id, outcome="delivered",
                notes="Marked delivered via bulk action", attempted_at=now,
            )

        results.append(BulkActionItemResult(delivery_id=delivery_id, success=True))

    broadcast_sync(dispatcher_queue_room(current_user.org_id), {"event": "queue_changed", "reason": "bulk_status_update"})

    success_count = sum(1 for r in results if r.success)
    return BulkActionResponse(results=results, success_count=success_count, failure_count=len(results) - success_count)


@router.patch("/bulk-assign-agent", response_model=BulkActionResponse)
def bulk_assign_agent(
    payload: BulkAssignAgentRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Reassign many deliveries to one agent at once. Unlike
    assign_agent_to_delivery() (which only accepts still-`pending`
    customer orders, since that's a narrower "first assignment" flow),
    this is a general reassignment: it works on a delivery in any
    status, including one already assigned to a different agent
    mid-route — a dispatcher pulling several deliveries off an agent
    who called in sick is exactly the kind of situation bulk reassign
    exists for. A delivery still sitting in `pending` also gets bumped
    to `picked_up`, matching what assigning it normally does; a
    delivery already further along (picked_up/out_for_delivery) just
    gets its agent_id swapped, since its status genuinely hasn't
    changed by being handed to someone else.
    """
    target_agent = db.query(UserDB).filter(
        UserDB.id == payload.agent_id,
        UserDB.org_id == current_user.org_id,
    ).first()
    if not target_agent or target_agent.role != UserRole.agent:
        raise HTTPException(status_code=400, detail="The selected agent doesn't exist in your organization.")

    results: List[BulkActionItemResult] = []

    for delivery_id in payload.delivery_ids:
        db_record = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.id == delivery_id,
            DeliveryRecordDB.org_id == current_user.org_id,
        ).first()
        if not db_record:
            results.append(BulkActionItemResult(delivery_id=delivery_id, success=False, error="Not found"))
            continue
        if db_record.status in (DeliveryStatus.delivered, DeliveryStatus.cancelled):
            results.append(BulkActionItemResult(
                delivery_id=delivery_id, success=False,
                error=f"Already {db_record.status.value} — can't reassign.",
            ))
            continue

        old_status = db_record.status
        old_agent_id = db_record.agent_id
        now = datetime.utcnow()

        db_record.agent_id = target_agent.id
        if old_status == DeliveryStatus.pending:
            db_record.status = DeliveryStatus.picked_up
        db_record.updated_at = now
        db.commit()
        db.refresh(db_record)

        record_history_entry(
            db,
            delivery_id=db_record.id,
            changed_by_user_id=current_user.id,
            changed_by_display_name=current_user.display_name,
            old_status=old_status,
            new_status=db_record.status,
            changed_at=now,
            note=f"Reassigned to {target_agent.display_name} via bulk action" if old_agent_id else f"Assigned to {target_agent.display_name} via bulk action",
        )
        notify_agent_of_new_assignment(db, delivery_id=db_record.id, order_id=db_record.order_id, agent_id=target_agent.id)
        broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})

        results.append(BulkActionItemResult(delivery_id=delivery_id, success=True))

    broadcast_sync(dispatcher_queue_room(current_user.org_id), {"event": "queue_changed", "reason": "bulk_reassign"})

    success_count = sum(1 for r in results if r.success)
    return BulkActionResponse(results=results, success_count=success_count, failure_count=len(results) - success_count)


@router.patch("/{delivery_id}", response_model=DeliveryRecordOut)
def update_delivery(
    delivery_id: str,
    update: DeliveryRecordUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Update an existing delivery record's status. Any logged-in user can
    call this (an agent updating their own delivery, in the normal online
    flow — offline updates go through the /sync batch endpoint instead).
    Scoped to the caller's own organization, so a user from one
    organization can never update a delivery belonging to another.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    old_status = db_record.status

    # ENFORCEMENT: a failed_attempt update must carry a real, active
    # reason code — this is what makes the delivery-attempts log
    # (models/delivery_attempt.py) trustworthy instead of relying on
    # whatever free-text `notes` an agent happened to type. Checked
    # before any mutation so a rejected update leaves the record
    # untouched.
    reason = None
    if update.status == DeliveryStatus.failed_attempt:
        if not update.reason_code_id:
            raise HTTPException(status_code=400, detail="A reason code is required to mark a delivery failed.")
        reason = db.query(FailedDeliveryReasonDB).filter(
            FailedDeliveryReasonDB.id == update.reason_code_id,
            FailedDeliveryReasonDB.org_id == current_user.org_id,
            FailedDeliveryReasonDB.active == True,  # noqa: E712
        ).first()
        if not reason:
            raise HTTPException(status_code=400, detail="That reason code doesn't exist or is no longer active.")

    # ENFORCEMENT (Phase 1 — Proof of Delivery): if this org has opted
    # into ANY pod_require_* setting (see models/organization.py,
    # routes/pod.py), a delivery can't be marked `delivered` until a
    # POD row exists for it (submitted via POST /deliveries/{id}/pod,
    # which itself already validated the payload against these same
    # requirements at capture time — this is a defense-in-depth check,
    # not a duplicate UI). Off by default, so an org that's never
    # touched POD settings sees no change in behavior at all.
    if update.status == DeliveryStatus.delivered:
        org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
        if org and org_requires_any_pod(org):
            if not pod_exists_for_delivery(db, db_record.id, current_user.org_id):
                raise HTTPException(
                    status_code=400,
                    detail="Proof of delivery is required before this delivery can be marked as delivered. "
                           "Capture it first, then try again.",
                )

    db_record.status = update.status
    db_record.notes = update.notes
    db_record.location_note = update.location_note
    db_record.updated_at = update.updated_at
    if update.proof_of_delivery is not None:
        db_record.proof_of_delivery = update.proof_of_delivery
    if update.status == DeliveryStatus.delivered:
        db_record.is_partial = update.is_partial
        db_record.partial_notes = update.partial_notes if update.is_partial else None
        classify_on_completion(db_record, update.updated_at)

    db.commit()
    db.refresh(db_record)

    if old_status != update.status:
        record_history_entry(
            db,
            delivery_id=db_record.id,
            changed_by_user_id=current_user.id,
            changed_by_display_name=current_user.display_name,
            old_status=old_status,
            new_status=update.status,
            changed_at=update.updated_at,
            note=(f"Failed: {reason.label}" if reason else (
                "Partially delivered" if (update.status == DeliveryStatus.delivered and update.is_partial) else None
            )),
        )
        notify_customer_of_status_change(
            db,
            delivery_id=db_record.id,
            order_id=db_record.order_id,
            new_status=(
                "partial_delivery" if (update.status == DeliveryStatus.delivered and update.is_partial)
                else update.status.value
            ),
            customer_email=db_record.customer_email,
            customer_phone=db_record.customer_phone,
            customer_id=db_record.customer_id,
        )
        broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})

        if update.status == DeliveryStatus.cancelled:
            # Dispatcher/admin-side cancellation of a paid checkout order
            # needs the same real refund as the customer's own self-serve
            # cancel button — see services/refund.py.
            refund_order_for_delivery(db, db_record.id)

        if update.status == DeliveryStatus.delivered:
            # No-op for a normal delivery — only actually does anything
            # when this delivery is a return_pickup (see
            # services/returns_workflow.py).
            handle_return_pickup_completion(db, db_record)

        # Log the attempt itself (see services/delivery_attempts.py) —
        # only for outcomes that represent a real attempt at the door.
        outcome = None
        if update.status == DeliveryStatus.failed_attempt:
            outcome = "failed_attempt"
        elif update.status == DeliveryStatus.delivered:
            outcome = "partial_delivery" if update.is_partial else "delivered"
        if outcome:
            record_delivery_attempt(
                db,
                db_record,
                agent_id=db_record.agent_id or current_user.id,
                outcome=outcome,
                reason_code_id=reason.id if reason else None,
                reason_label=reason.label if reason else None,
                notes=update.notes or update.partial_notes,
                attempted_at=update.updated_at,
            )

    # Phase 14: webhooks — one outbound event per delivery-status
    # transition, mapped from this project's internal DeliveryStatus
    # values to the public webhook event vocabulary. Only fires on an
    # ACTUAL transition, for statuses the public event catalog
    # recognizes — a same-status no-op update never queues a delivery
    # no subscriber asked for.
    if old_status != update.status:
        event_map = {
            DeliveryStatus.picked_up: "delivery.picked_up",
            DeliveryStatus.out_for_delivery: "delivery.out_for_delivery",
            DeliveryStatus.delivered: "delivery.delivered",
            DeliveryStatus.failed_attempt: "delivery.failed",
        }
        event_type = event_map.get(update.status)
        if event_type:
            emit_event(db, db_record.org_id, event_type, {
                "delivery_id": db_record.id, "order_id": db_record.order_id, "status": update.status.value,
            })

    return db_record


class RescheduleRequest(BaseModel):
    rescheduled_to: datetime
    reason: str


class PriorityUpdateRequest(BaseModel):
    priority: DeliveryPriority


@router.post("/{delivery_id}/reschedule", response_model=DeliveryRecordOut)
def reschedule_delivery(
    delivery_id: str,
    payload: RescheduleRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Reschedule a delivery to a new date/window — typically used after a
    failed_attempt (customer wasn't available, asked for another day),
    but not restricted to that: a dispatcher can also proactively
    reschedule a still-pending or picked_up delivery.

    Available to the assigned agent themselves (they're the one
    standing at the door finding out a redelivery is needed) as well
    as any dispatcher/admin in the org — not just dispatchers, unlike
    most delivery-mutating endpoints in this file, since an agent
    reschedules in the moment far more often than a dispatcher does.

    Sets status to failed_attempt (this delivery still needs a real
    attempt — it hasn't been delivered) and logs BOTH a history entry
    and a failed_attempt delivery-attempt (see
    services/delivery_attempts.py), since a reschedule genuinely is a
    failed attempt at the original time, just one with a concrete
    next-attempt date attached rather than an open-ended failure.
    Refuses on an already-terminal delivery (delivered/cancelled) —
    rescheduling a delivery that's already done or cancelled doesn't
    make sense.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    if current_user.role == UserRole.agent and db_record.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only reschedule your own assigned deliveries.")

    if db_record.status in (DeliveryStatus.delivered, DeliveryStatus.cancelled):
        raise HTTPException(status_code=400, detail=f"Can't reschedule a delivery that's already {db_record.status.value}.")

    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to reschedule.")

    old_status = db_record.status
    now = datetime.utcnow()

    db_record.status = DeliveryStatus.failed_attempt
    db_record.rescheduled_to = payload.rescheduled_to
    db_record.reschedule_reason = payload.reason.strip()
    db_record.reschedule_count = (db_record.reschedule_count or 0) + 1
    db_record.updated_at = now
    db.commit()
    db.refresh(db_record)

    record_history_entry(
        db,
        delivery_id=db_record.id,
        changed_by_user_id=current_user.id,
        changed_by_display_name=current_user.display_name,
        old_status=old_status,
        new_status=db_record.status,
        changed_at=now,
        note=f"Rescheduled to {payload.rescheduled_to.strftime('%Y-%m-%d %H:%M')}: {payload.reason.strip()}",
    )
    record_delivery_attempt(
        db, db_record, agent_id=db_record.agent_id, outcome="failed_attempt",
        notes=f"Rescheduled: {payload.reason.strip()}", attempted_at=now,
    )
    notify_customer_of_status_change(
        db,
        delivery_id=db_record.id,
        order_id=db_record.order_id,
        new_status="rescheduled",
        customer_email=db_record.customer_email,
        customer_phone=db_record.customer_phone,
        customer_id=db_record.customer_id,
    )
    broadcast_sync(tracking_room(db_record.id), {"event": "status_changed", "status": db_record.status.value})
    broadcast_sync(dispatcher_queue_room(current_user.org_id), {"event": "queue_changed", "reason": "rescheduled"})

    return db_record


@router.patch("/{delivery_id}/priority", response_model=DeliveryRecordOut)
def update_delivery_priority(
    delivery_id: str,
    payload: PriorityUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Dispatcher/admin-only: bump or lower a delivery's queue priority.
    Doesn't touch status/history the way a real delivery event does —
    just re-sorts where this delivery lands in list_deliveries()
    (see _sort_by_priority) and list_unassigned_deliveries().
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    db_record.priority = payload.priority.value
    assign_sla(db, db_record)  # priority is a matching dimension for SLA policies — re-pick on change
    db.commit()
    db.refresh(db_record)

    broadcast_sync(dispatcher_queue_room(current_user.org_id), {"event": "queue_changed", "reason": "priority_changed"})
    return db_record


@router.get("/{delivery_id}/attempts", response_model=List[DeliveryAttemptOut])
def get_delivery_attempts(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Every logged delivery ATTEMPT (delivered/failed_attempt/partial_delivery
    outcome) for this delivery, oldest first — distinct from
    /{delivery_id}/history, which logs every status change including
    non-attempt ones like assignment. See models/delivery_attempt.py.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    return (
        db.query(DeliveryAttemptDB)
        .filter(DeliveryAttemptDB.delivery_id == delivery_id)
        .order_by(DeliveryAttemptDB.attempted_at.asc())
        .all()
    )


class RouteOptimizeRequest(BaseModel):
    delivery_ids: List[str]
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None


class RouteOptimizeOut(BaseModel):
    ordered_delivery_ids: List[str]
    used_real_routing: bool  # False means every delivery lacked coordinates, or no routing provider was reachable — caller should fall back to the client-side heuristic (routeOptimizer.js)


@router.post("/optimize-route", response_model=RouteOptimizeOut)
def optimize_route(
    payload: RouteOptimizeRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Real multi-stop route optimization (services/routing.py — an actual
    TSP-approximation via OSRM/Google, not hand-rolled nearest-neighbor)
    for a batch of an agent's own deliveries. Falls back to returning
    the original order (used_real_routing=False) when deliveries lack
    coordinates or no routing provider is reachable — the frontend's
    existing client-side heuristic (routeOptimizer.js) takes over in
    that case, so a batch of deliveries always gets SOME ordering, real
    routing or not.
    """
    deliveries = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id.in_(payload.delivery_ids),
        DeliveryRecordDB.org_id == current_user.org_id,
    ).all()
    if current_user.role == UserRole.agent:
        deliveries = [d for d in deliveries if d.agent_id == current_user.id]

    stops = []
    for d in deliveries:
        if not d.latitude or not d.longitude:
            continue
        try:
            stops.append({"id": d.id, "latitude": float(d.latitude), "longitude": float(d.longitude)})
        except (TypeError, ValueError):
            continue

    if len(stops) < 2:
        return RouteOptimizeOut(ordered_delivery_ids=[d.id for d in deliveries], used_real_routing=False)

    start = None
    if payload.start_latitude is not None and payload.start_longitude is not None:
        start = {"latitude": payload.start_latitude, "longitude": payload.start_longitude}

    ordered_ids = optimize_stop_order(stops, start)
    if not ordered_ids:
        return RouteOptimizeOut(ordered_delivery_ids=[d.id for d in deliveries], used_real_routing=False)

    # Any delivery that had no usable coordinates rides along at the
    # end, in its original order — real routing can't place a stop it
    # was never given a location for, but it shouldn't just disappear
    # from the batch either.
    no_coord_ids = [d.id for d in deliveries if d.id not in {s["id"] for s in stops}]
    return RouteOptimizeOut(ordered_delivery_ids=ordered_ids + no_coord_ids, used_real_routing=True)


@router.get("/", response_model=List[DeliveryRecordOut])
def list_deliveries(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    List all delivery records within the caller's organization —
    dispatcher/admin dashboard only.

    Deliberately NOT paginated server-side: this response is the
    dispatcher's full offline cache (see cacheDispatcherDeliveries() in
    the frontend), which is what makes the dashboard usable when the
    network drops. Slicing this at the API would silently make the
    offline fallback incomplete. The dispatcher TABLE itself still
    paginates on screen (PAGE_SIZE in DispatcherTable.jsx) — that's a
    display concern over data that's already local, which is the right
    place to page a dataset this shape.

    Sorted urgent -> high -> normal -> low (see _sort_by_priority) so
    the dispatcher table's default order surfaces the deliveries that
    need attention first, without requiring a manual sort click.
    """
    deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == current_user.org_id).all()
    return _sort_by_priority(deliveries)


@router.get("/mine", response_model=List[DeliveryRecordOut])
def list_my_deliveries(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    List deliveries assigned to the currently logged-in agent. This is what
    the Agent view "pulls" from the server, so dispatcher-assigned
    deliveries actually show up in the agent's local (IndexedDB) list —
    without this, an agent would only ever see deliveries they created
    themselves, never ones assigned to them by a dispatcher. Not
    paginated server-side for the same offline-cache-completeness reason
    as list_deliveries() above.
    """
    return db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.agent_id == current_user.id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).all()


@router.get("/{delivery_id}", response_model=DeliveryRecordOut)
def get_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Get a single delivery record by ID, scoped to the caller's organization."""
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    return db_record


@router.get("/{delivery_id}/history", response_model=List[DeliveryHistoryOut])
def get_delivery_history(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Returns the full audit trail for a delivery — every status change,
    who made it, and when — ordered oldest first so it reads top-to-bottom
    like a timeline. Confirms the delivery belongs to the caller's
    organization before returning any history for it.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    return (
        db.query(DeliveryHistoryDB)
        .filter(DeliveryHistoryDB.delivery_id == delivery_id)
        .order_by(DeliveryHistoryDB.changed_at.asc())
        .all()
    )


@router.delete("/{delivery_id}")
def delete_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Delete a delivery record permanently, scoped to the caller's
    organization.

    Used when the agent removes a record from their local list — if the
    record was already synced, this also removes it from the server so
    the two stay consistent. If it was never synced (server never had it),
    this simply does nothing on the server side, which is fine.
    """
    db_record = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not db_record:
        # Nothing to delete server-side — not an error, since the record
        # may have only ever existed locally (never synced)
        return {"deleted": False, "reason": "not found on server"}

    db.delete(db_record)
    db.commit()
    return {"deleted": True}
