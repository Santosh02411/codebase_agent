"""
Fleet management routes (Phase 11). Follows the same dispatcher/admin
management split as workforce.py: vehicle CRUD, assignment, maintenance,
and fuel-record entry are dispatcher/admin actions; any staff member can
view fleet data relevant to doing their job (an agent can see their own
assigned vehicle).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.vehicle import (
    VehicleDB, VehicleMaintenanceDB, VehicleFuelRecordDB,
    VehicleCreate, VehicleUpdate, VehicleAssignRequest, VehicleOut,
    MaintenanceCreate, MaintenanceOut,
    FuelRecordCreate, FuelRecordOut,
    InspectionUpdate,
)
from app.routes.auth import get_current_user
from app.services import fleet as fleet_service
from app.services.action_log import record_action

router = APIRouter(prefix="/fleet", tags=["fleet"])


def require_dispatcher_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


def _get_vehicle_or_404(db: Session, vehicle_id: str, org_id: str) -> VehicleDB:
    vehicle = db.query(VehicleDB).filter(VehicleDB.id == vehicle_id, VehicleDB.org_id == org_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


# ---------- Vehicle CRUD ----------

@router.get("/vehicles", response_model=List[VehicleOut])
def list_vehicles(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    q = db.query(VehicleDB).filter(VehicleDB.org_id == current_user.org_id, VehicleDB.active == True)  # noqa: E712
    if status:
        q = q.filter(VehicleDB.status == status)
    # Agents only see fleet-wide read access for their own assigned vehicle,
    # matching this project's existing "own delivery" scoping pattern.
    if current_user.role == UserRole.agent:
        q = q.filter(VehicleDB.assigned_agent_id == current_user.id)
    return q.order_by(VehicleDB.created_at.asc()).all()


@router.post("/vehicles", response_model=VehicleOut)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    dup = db.query(VehicleDB).filter(
        VehicleDB.org_id == current_user.org_id,
        VehicleDB.registration_number == payload.registration_number,
        VehicleDB.active == True,  # noqa: E712
    ).first()
    if dup:
        raise HTTPException(status_code=400, detail="A vehicle with this registration number already exists.")

    vehicle = VehicleDB(org_id=current_user.org_id, **payload.dict())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="vehicle", entity_id=vehicle.id, entity_label=vehicle.registration_number,
        summary=f"Added vehicle '{vehicle.registration_number}'.",
    )
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: str, payload: VehicleUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(vehicle, field, value)
    vehicle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete("/vehicles/{vehicle_id}")
def deactivate_vehicle(vehicle_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    vehicle.active = False
    vehicle.assigned_agent_id = None
    vehicle.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Vehicle deactivated."}


# ---------- Assignment ----------

@router.post("/vehicles/{vehicle_id}/assign", response_model=VehicleOut)
def assign_vehicle(vehicle_id: str, payload: VehicleAssignRequest, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)

    if payload.agent_id:
        agent = db.query(UserDB).filter(UserDB.id == payload.agent_id, UserDB.org_id == current_user.org_id).first()
        if not agent or agent.role != UserRole.agent:
            raise HTTPException(status_code=400, detail="agent_id must be an agent in your organization.")
        already = db.query(VehicleDB).filter(
            VehicleDB.org_id == current_user.org_id, VehicleDB.assigned_agent_id == payload.agent_id,
            VehicleDB.id != vehicle_id, VehicleDB.active == True,  # noqa: E712
        ).first()
        if already:
            raise HTTPException(status_code=400, detail=f"This agent is already assigned to vehicle {already.registration_number}.")
        vehicle.assigned_agent_id = payload.agent_id
        vehicle.status = "in_use"
    else:
        vehicle.assigned_agent_id = None
        vehicle.status = "available"

    vehicle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(vehicle)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="vehicle", entity_id=vehicle.id, entity_label=vehicle.registration_number,
        summary=f"{'Assigned' if payload.agent_id else 'Unassigned'} vehicle '{vehicle.registration_number}'.",
    )
    return vehicle


@router.patch("/vehicles/{vehicle_id}/inspection", response_model=VehicleOut)
def record_inspection(vehicle_id: str, payload: InspectionUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    vehicle.last_inspection_date = payload.last_inspection_date
    vehicle.next_inspection_due = payload.next_inspection_due
    vehicle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(vehicle)
    return vehicle


# ---------- Maintenance ----------

@router.post("/vehicles/{vehicle_id}/maintenance", response_model=MaintenanceOut)
def add_maintenance_record(vehicle_id: str, payload: MaintenanceCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    record = VehicleMaintenanceDB(
        org_id=current_user.org_id, vehicle_id=vehicle.id,
        performed_by_user_id=current_user.id,
        **payload.dict(exclude={"performed_at"}, exclude_unset=False),
    )
    if payload.performed_at:
        record.performed_at = payload.performed_at
    if payload.odometer_km is not None:
        vehicle.odometer_km = max(vehicle.odometer_km, payload.odometer_km)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/vehicles/{vehicle_id}/maintenance", response_model=List[MaintenanceOut])
def list_maintenance_records(vehicle_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    return db.query(VehicleMaintenanceDB).filter(
        VehicleMaintenanceDB.org_id == current_user.org_id, VehicleMaintenanceDB.vehicle_id == vehicle_id,
    ).order_by(VehicleMaintenanceDB.performed_at.desc()).all()


# ---------- Fuel ----------

@router.post("/vehicles/{vehicle_id}/fuel", response_model=FuelRecordOut)
def add_fuel_record(vehicle_id: str, payload: FuelRecordCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    # Any staff member can log fuel for the vehicle they're driving (their own assigned vehicle);
    # dispatchers/admins can log for any vehicle in the org.
    if current_user.role == UserRole.agent and vehicle.assigned_agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only log fuel for your own assigned vehicle.")

    record = VehicleFuelRecordDB(
        org_id=current_user.org_id, vehicle_id=vehicle.id, recorded_by_user_id=current_user.id,
        **payload.dict(exclude={"recorded_at"}),
    )
    if payload.recorded_at:
        record.recorded_at = payload.recorded_at
    if payload.odometer_km is not None:
        vehicle.odometer_km = max(vehicle.odometer_km, payload.odometer_km)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/vehicles/{vehicle_id}/fuel", response_model=List[FuelRecordOut])
def list_fuel_records(vehicle_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    return db.query(VehicleFuelRecordDB).filter(
        VehicleFuelRecordDB.org_id == current_user.org_id, VehicleFuelRecordDB.vehicle_id == vehicle_id,
    ).order_by(VehicleFuelRecordDB.recorded_at.desc()).all()


# ---------- Location, utilization, reminders ----------

@router.get("/vehicles/{vehicle_id}/location")
def get_vehicle_location(vehicle_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    loc = fleet_service.current_vehicle_location(db, vehicle)
    if not loc:
        return {"vehicle_id": vehicle_id, "location": None, "message": "No agent assigned or no location reported yet."}
    return {"vehicle_id": vehicle_id, "location": loc}


@router.get("/vehicles/{vehicle_id}/utilization")
def get_vehicle_utilization(vehicle_id: str, days: int = 30, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicle = _get_vehicle_or_404(db, vehicle_id, current_user.org_id)
    return fleet_service.vehicle_utilization(db, vehicle, days)


@router.get("/utilization")
def get_fleet_utilization(days: int = 30, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    vehicles = db.query(VehicleDB).filter(VehicleDB.org_id == current_user.org_id, VehicleDB.active == True).all()  # noqa: E712
    return [fleet_service.vehicle_utilization(db, v, days) for v in vehicles]


@router.get("/reminders")
def get_fleet_reminders(within_days: int = 14, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    result = fleet_service.maintenance_and_expiry_reminders(db, current_user.org_id, within_days)
    horizon = datetime.utcnow()
    from datetime import timedelta
    horizon = horizon + timedelta(days=within_days)
    maintenance_due = db.query(VehicleMaintenanceDB).filter(
        VehicleMaintenanceDB.org_id == current_user.org_id,
        VehicleMaintenanceDB.next_due_date.isnot(None),
        VehicleMaintenanceDB.next_due_date <= horizon,
    ).order_by(VehicleMaintenanceDB.next_due_date.asc()).all()

    def _v(vlist):
        return [{"id": v.id, "registration_number": v.registration_number} for v in vlist]

    return {
        "insurance_due": _v(result["insurance_due"]),
        "registration_due": _v(result["registration_due"]),
        "inspection_due": _v(result["inspection_due"]),
        "maintenance_due": [
            {"vehicle_id": m.vehicle_id, "maintenance_type": m.maintenance_type, "next_due_date": m.next_due_date}
            for m in maintenance_due
        ],
    }
