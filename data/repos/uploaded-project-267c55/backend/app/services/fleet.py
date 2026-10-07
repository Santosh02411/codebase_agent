"""
Fleet service logic (Phase 11). Kept separate from routes/fleet.py so
the utilization/reminder calculations (the only genuinely non-trivial
logic in this phase — everything else is straightforward CRUD) are
unit-testable on their own.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.vehicle import VehicleDB
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.agent_location import AgentLocationDB


def current_vehicle_location(db: Session, vehicle: VehicleDB) -> Optional[dict]:
    """
    A vehicle's live position is derived from its assigned agent's
    existing AgentLocationDB row (Phase 9's "latest position" table) —
    deliberately not a second, independently-updated location field on
    VehicleDB, which would risk drifting out of sync with the agent's
    real position.
    """
    if not vehicle.assigned_agent_id:
        return None
    loc = db.query(AgentLocationDB).filter(AgentLocationDB.agent_id == vehicle.assigned_agent_id).first()
    if not loc:
        return None
    return {"latitude": loc.latitude, "longitude": loc.longitude, "updated_at": loc.updated_at}


def vehicle_utilization(db: Session, vehicle: VehicleDB, days: int) -> dict:
    """
    A vehicle's utilization is computed from deliveries completed by
    its CURRENTLY assigned agent over the window — an honest scope
    given this project has no vehicle-assignment history table (a
    vehicle reassigned mid-window would attribute the whole window to
    its current agent). Documented, not hidden.
    """
    since = datetime.utcnow() - timedelta(days=days)
    if not vehicle.assigned_agent_id:
        return {
            "vehicle_id": vehicle.id, "assigned_agent_id": None,
            "deliveries_completed": 0, "period_days": days,
            "note": "No agent currently assigned to this vehicle.",
        }

    completed = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.agent_id == vehicle.assigned_agent_id,
        DeliveryRecordDB.status == DeliveryStatus.delivered,
        DeliveryRecordDB.updated_at >= since,
    ).count()

    return {
        "vehicle_id": vehicle.id,
        "assigned_agent_id": vehicle.assigned_agent_id,
        "deliveries_completed": completed,
        "period_days": days,
    }


def maintenance_and_expiry_reminders(db: Session, org_id: str, within_days: int = 14) -> dict:
    """
    Everything that needs attention soon: vehicles whose insurance,
    registration, or next inspection falls within `within_days`, plus
    (via routes/fleet.py, which queries VehicleMaintenanceDB directly)
    any scheduled maintenance next_due_date in the same window.
    """
    horizon = datetime.utcnow() + timedelta(days=within_days)
    vehicles = db.query(VehicleDB).filter(VehicleDB.org_id == org_id, VehicleDB.active == True).all()  # noqa: E712

    insurance_due, registration_due, inspection_due = [], [], []
    for v in vehicles:
        if v.insurance_expiry and v.insurance_expiry <= horizon:
            insurance_due.append(v)
        if v.registration_expiry and v.registration_expiry <= horizon:
            registration_due.append(v)
        if v.next_inspection_due and v.next_inspection_due <= horizon:
            inspection_due.append(v)

    return {
        "insurance_due": insurance_due,
        "registration_due": registration_due,
        "inspection_due": inspection_due,
    }


def capacity_warning(db: Session, agent_id: str, org_id: str, pending_delivery_count: int) -> Optional[str]:
    """
    Used by routes/deliveries.py's suggested-agents/auto-assign flow
    (Phase 9) as an optional, additive check: if the agent's assigned
    vehicle has a unit capacity and the number of deliveries about to
    be on it would exceed that capacity, return a human-readable
    warning string; otherwise None. Never blocks assignment — this
    project's existing auto-assign is advisory, and capacity is a
    dispatcher judgment call, not a hard rule with no override.
    """
    vehicle = db.query(VehicleDB).filter(
        VehicleDB.org_id == org_id, VehicleDB.assigned_agent_id == agent_id, VehicleDB.active == True,  # noqa: E712
    ).first()
    if not vehicle or not vehicle.capacity_units:
        return None
    if pending_delivery_count > vehicle.capacity_units:
        return (
            f"Assigned vehicle ({vehicle.registration_number}) has a capacity of "
            f"{vehicle.capacity_units} but this agent would have {pending_delivery_count} pending deliveries."
        )
    return None
