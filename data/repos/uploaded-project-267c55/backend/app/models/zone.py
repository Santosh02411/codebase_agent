"""
Delivery zones/territories — a real geographic entity an admin defines
and manages, not just the free-text `zone` string dispatchers have
always been able to type onto a delivery (that field still exists and
still works as a loose label; this is the "real" upgrade on top of it).

A zone is a circle: a center point (latitude/longitude) plus a radius
in kilometers. That's a deliberate simplification over a drawn polygon
— a circle is trivial to test a point against (haversine distance from
center <= radius) and trivial to edit (three numbers), while a polygon
needs real point-in-polygon math and an interactive map-drawing UI to
be usable at all. For the kind of territory a delivery org actually
needs ("agents who cover roughly this neighborhood"), a circle is a
genuine, real boundary — not a placeholder — it's just not
arbitrarily-shaped.

Which agents COVER a zone is a many-to-many relationship (an agent can
cover more than one zone; a zone can have more than one covering
agent), tracked in AgentZoneAssignmentDB.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime
from pydantic import BaseModel
from typing import Optional, List

from app.db.session import Base


class ZoneDB(Base):
    __tablename__ = "zones"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    center_latitude = Column(Float, nullable=False)
    center_longitude = Column(Float, nullable=False)
    radius_km = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentZoneAssignmentDB(Base):
    __tablename__ = "agent_zone_assignments"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    zone_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class ZoneCreate(BaseModel):
    name: str
    description: Optional[str] = None
    center_latitude: float
    center_longitude: float
    radius_km: float


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    center_latitude: Optional[float] = None
    center_longitude: Optional[float] = None
    radius_km: Optional[float] = None


class ZoneOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    center_latitude: float
    center_longitude: float
    radius_km: float
    covering_agent_ids: List[str] = []

    class Config:
        from_attributes = True
