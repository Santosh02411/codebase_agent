"""
AgentLocationDB: one row per agent, holding only their MOST RECENT GPS
position. This is deliberately a single-row-per-agent "latest location"
table, not a location history log — a customer's live tracking map only
ever needs to know "where is my agent right now", and keeping history
here would grow unbounded for no product benefit (route history, if
ever wanted, belongs in its own dedicated table with a retention policy).

Updated by the agent's own device via a lightweight PATCH the frontend
calls periodically (see AgentDeliveryList.jsx's location-sharing toggle),
using the browser's navigator.geolocation.watchPosition. Read by
customers/dispatchers polling a delivery's tracking view.
"""

from sqlalchemy import Column, String, DateTime, Float

from app.db.session import Base
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AgentLocationDB(Base):
    __tablename__ = "agent_locations"

    agent_id = Column(String, primary_key=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class AgentLocationUpdate(BaseModel):
    latitude: float
    longitude: float


class AgentLocationOut(BaseModel):
    agent_id: str
    latitude: float
    longitude: float
    updated_at: datetime

    class Config:
        from_attributes = True
