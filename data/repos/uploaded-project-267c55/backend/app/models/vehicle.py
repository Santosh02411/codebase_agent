"""
Fleet management (Phase 11) — vehicles, agent/driver assignment,
maintenance records, and fuel records, additive alongside the existing
AgentLocationDB/AgentLocationHistoryDB (Phase 9) location system. A
vehicle's live location is deliberately NOT duplicated here: it is
derived from its currently-assigned agent's existing location rows
(see services/fleet.py), so there is exactly one source of truth for
"where is this thing right now" instead of two systems that could
drift apart.

Three tables:
  VehicleDB              — one row per vehicle: type, registration,
                            capacity, status, current assignment,
                            odometer/mileage, insurance/registration/
                            inspection expiry dates.
  VehicleMaintenanceDB    — service history + scheduled next-due dates,
                            used to power the maintenance-reminders
                            endpoint.
  VehicleFuelRecordDB     — fuel purchase log, used for cost/efficiency
                            analytics.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean, Float
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class VehicleDB(Base):
    __tablename__ = "vehicles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)

    vehicle_type = Column(String, nullable=False)  # "bike" | "van" | "truck" | "car"
    registration_number = Column(String, nullable=False)
    capacity_kg = Column(Float, nullable=True)
    capacity_units = Column(Integer, nullable=True)  # e.g. max parcels, when weight isn't tracked

    # "available" | "in_use" | "maintenance" | "inactive"
    status = Column(String, nullable=False, default="available")

    assigned_agent_id = Column(String, nullable=True, index=True)  # a UserDB.id, must be an agent in the same org

    odometer_km = Column(Float, nullable=False, default=0)

    insurance_expiry = Column(DateTime, nullable=True)
    registration_expiry = Column(DateTime, nullable=True)
    last_inspection_date = Column(DateTime, nullable=True)
    next_inspection_due = Column(DateTime, nullable=True)

    active = Column(Boolean, nullable=False, default=True)  # soft-delete flag
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VehicleMaintenanceDB(Base):
    __tablename__ = "vehicle_maintenance_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    vehicle_id = Column(String, index=True, nullable=False)

    maintenance_type = Column(String, nullable=False)  # e.g. "oil_change", "tire_replacement", "general_service"
    description = Column(String, nullable=True)
    cost = Column(Float, nullable=True)
    odometer_km = Column(Float, nullable=True)

    performed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    next_due_date = Column(DateTime, nullable=True)  # when this kind of maintenance is next expected
    performed_by_user_id = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VehicleFuelRecordDB(Base):
    __tablename__ = "vehicle_fuel_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    vehicle_id = Column(String, index=True, nullable=False)

    liters = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    odometer_km = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    recorded_by_user_id = Column(String, nullable=True)


# ---------- Pydantic Schemas ----------

class VehicleCreate(BaseModel):
    vehicle_type: str
    registration_number: str
    capacity_kg: Optional[float] = None
    capacity_units: Optional[int] = None
    insurance_expiry: Optional[datetime] = None
    registration_expiry: Optional[datetime] = None


class VehicleUpdate(BaseModel):
    vehicle_type: Optional[str] = None
    registration_number: Optional[str] = None
    capacity_kg: Optional[float] = None
    capacity_units: Optional[int] = None
    status: Optional[str] = None
    insurance_expiry: Optional[datetime] = None
    registration_expiry: Optional[datetime] = None
    active: Optional[bool] = None


class VehicleAssignRequest(BaseModel):
    agent_id: Optional[str] = None  # null unassigns


class VehicleOut(BaseModel):
    id: str
    org_id: str
    vehicle_type: str
    registration_number: str
    capacity_kg: Optional[float] = None
    capacity_units: Optional[int] = None
    status: str
    assigned_agent_id: Optional[str] = None
    odometer_km: float
    insurance_expiry: Optional[datetime] = None
    registration_expiry: Optional[datetime] = None
    last_inspection_date: Optional[datetime] = None
    next_inspection_due: Optional[datetime] = None
    active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MaintenanceCreate(BaseModel):
    maintenance_type: str
    description: Optional[str] = None
    cost: Optional[float] = Field(default=None, ge=0)
    odometer_km: Optional[float] = None
    performed_at: Optional[datetime] = None
    next_due_date: Optional[datetime] = None


class MaintenanceOut(BaseModel):
    id: str
    vehicle_id: str
    maintenance_type: str
    description: Optional[str] = None
    cost: Optional[float] = None
    odometer_km: Optional[float] = None
    performed_at: datetime
    next_due_date: Optional[datetime] = None
    performed_by_user_id: Optional[str] = None

    class Config:
        from_attributes = True


class FuelRecordCreate(BaseModel):
    liters: float = Field(gt=0)
    cost: float = Field(ge=0)
    odometer_km: Optional[float] = None
    recorded_at: Optional[datetime] = None


class FuelRecordOut(BaseModel):
    id: str
    vehicle_id: str
    liters: float
    cost: float
    odometer_km: Optional[float] = None
    recorded_at: datetime
    recorded_by_user_id: Optional[str] = None

    class Config:
        from_attributes = True


class InspectionUpdate(BaseModel):
    last_inspection_date: datetime
    next_inspection_due: Optional[datetime] = None
