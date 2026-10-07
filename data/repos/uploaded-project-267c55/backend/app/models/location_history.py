"""
AgentLocationHistoryDB (Phase 9) — a location PING LOG, additive
alongside the existing AgentLocationDB (models/agent_location.py),
which deliberately stays a single-row-per-agent "latest position only"
table (see that file's docstring, which explicitly calls out that
history "belongs in its own dedicated table" if ever needed — this is
that table). Everything reading "where is this agent right now"
(customer tracking, dispatcher live map) keeps using AgentLocationDB,
completely unchanged; everything in this phase needing a TRAIL of
positions over time (route replay, heatmaps, distance traveled, time
spent per delivery, deviation detection) reads this one instead.

Written from the exact same place AgentLocationDB is updated —
routes/users.py's PUT /users/me/location — with one additional insert
alongside the existing upsert, not a separate write path.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float
from pydantic import BaseModel

from app.db.session import Base


class AgentLocationHistoryDB(Base):
    __tablename__ = "agent_location_history"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, index=True, nullable=False)

    # Best-effort: whichever delivery this agent had active
    # (picked_up/out_for_delivery) at the moment of this ping, if any —
    # null for a ping with no active delivery. Lets per-delivery
    # analytics (route replay, distance traveled, time spent) filter
    # directly without having to reconstruct "what was this agent doing
    # at time T" after the fact.
    delivery_id = Column(String, index=True, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class LocationHistoryPointOut(BaseModel):
    latitude: float
    longitude: float
    recorded_at: datetime

    class Config:
        from_attributes = True
