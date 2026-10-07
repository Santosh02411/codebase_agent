"""
Admin management of delivery zones/territories and which agents cover
each one. See models/zone.py for the "why a circle, not a polygon"
reasoning.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.zone import ZoneDB, AgentZoneAssignmentDB, ZoneCreate, ZoneUpdate, ZoneOut
from app.models.user import UserDB, UserRole
from app.routes.admin import require_admin

router = APIRouter(prefix="/admin/zones", tags=["zones"])


def _zone_out(db: Session, zone: ZoneDB) -> ZoneOut:
    agent_ids = [
        row.agent_id for row in
        db.query(AgentZoneAssignmentDB).filter(AgentZoneAssignmentDB.zone_id == zone.id).all()
    ]
    return ZoneOut(
        id=zone.id, name=zone.name, description=zone.description,
        center_latitude=zone.center_latitude, center_longitude=zone.center_longitude,
        radius_km=zone.radius_km, covering_agent_ids=agent_ids,
    )


@router.get("/", response_model=List[ZoneOut])
def list_zones(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    zones = db.query(ZoneDB).filter(ZoneDB.org_id == current_user.org_id).all()
    return [_zone_out(db, z) for z in zones]


@router.post("/", response_model=ZoneOut)
def create_zone(
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    if payload.radius_km <= 0:
        raise HTTPException(status_code=400, detail="Radius must be greater than 0 km.")

    zone = ZoneDB(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        name=payload.name.strip(),
        description=payload.description,
        center_latitude=payload.center_latitude,
        center_longitude=payload.center_longitude,
        radius_km=payload.radius_km,
        created_at=datetime.utcnow(),
    )
    db.add(zone)
    db.commit()
    return _zone_out(db, zone)


@router.patch("/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: str,
    payload: ZoneUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    zone = db.query(ZoneDB).filter(ZoneDB.id == zone_id, ZoneDB.org_id == current_user.org_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    if payload.name is not None:
        zone.name = payload.name.strip()
    if payload.description is not None:
        zone.description = payload.description
    if payload.center_latitude is not None:
        zone.center_latitude = payload.center_latitude
    if payload.center_longitude is not None:
        zone.center_longitude = payload.center_longitude
    if payload.radius_km is not None:
        if payload.radius_km <= 0:
            raise HTTPException(status_code=400, detail="Radius must be greater than 0 km.")
        zone.radius_km = payload.radius_km

    db.commit()
    return _zone_out(db, zone)


@router.delete("/{zone_id}")
def delete_zone(
    zone_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    zone = db.query(ZoneDB).filter(ZoneDB.id == zone_id, ZoneDB.org_id == current_user.org_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    db.query(AgentZoneAssignmentDB).filter(AgentZoneAssignmentDB.zone_id == zone_id).delete()
    db.delete(zone)
    db.commit()
    return {"message": "Zone deleted."}


@router.post("/{zone_id}/agents/{agent_id}", response_model=ZoneOut)
def assign_agent_to_zone(
    zone_id: str,
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    zone = db.query(ZoneDB).filter(ZoneDB.id == zone_id, ZoneDB.org_id == current_user.org_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    agent = db.query(UserDB).filter(
        UserDB.id == agent_id, UserDB.org_id == current_user.org_id, UserDB.role == UserRole.agent
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found in your organization.")

    existing = db.query(AgentZoneAssignmentDB).filter(
        AgentZoneAssignmentDB.zone_id == zone_id, AgentZoneAssignmentDB.agent_id == agent_id
    ).first()
    if not existing:
        db.add(AgentZoneAssignmentDB(zone_id=zone_id, agent_id=agent_id, org_id=current_user.org_id))
        db.commit()

    return _zone_out(db, zone)


@router.delete("/{zone_id}/agents/{agent_id}", response_model=ZoneOut)
def unassign_agent_from_zone(
    zone_id: str,
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    zone = db.query(ZoneDB).filter(ZoneDB.id == zone_id, ZoneDB.org_id == current_user.org_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    db.query(AgentZoneAssignmentDB).filter(
        AgentZoneAssignmentDB.zone_id == zone_id, AgentZoneAssignmentDB.agent_id == agent_id
    ).delete()
    db.commit()

    return _zone_out(db, zone)
