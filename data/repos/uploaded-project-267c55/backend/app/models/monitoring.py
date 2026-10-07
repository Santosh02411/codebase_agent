"""
Monitoring & Reliability (Phase 18) — production observability for
this project's existing background schedulers, error paths, and
external-dependency health, layered on top of what already exists
rather than replacing it: Phase 5's PaymentLedgerDB already IS payment
monitoring's data source, and the WebSocket connection manager
(services/websocket_manager.py) already tracks its own rooms/
connections — this phase adds a `connection_count()` read on that
existing state rather than a second parallel counter.

Two persisted tables here; everything else (API request timing,
notification send success/failure) is intentionally in-memory
(services/monitoring.py) rather than a third and fourth table — those
are operational metrics meant to answer "is something wrong RIGHT
NOW", not a permanent audit trail, and resetting on restart is the
correct behavior for that, not a shortcut.

  ErrorLogDB      — every unhandled exception, caught by main.py's
                    global exception handler.
  JobHeartbeatDB  — one row per background scheduler (reminder, SLA
                    monitor, subscription, webhook), updated on every
                    tick with the outcome of that tick.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class ErrorLogDB(Base):
    __tablename__ = "error_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=True)  # null when the error happened before org context was resolvable (e.g. auth failure, malformed request)

    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    error_type = Column(String, nullable=False)  # the exception class name
    error_message = Column(String, nullable=True)
    traceback_snippet = Column(String, nullable=True)  # last ~2000 chars — enough to locate the fault without storing unbounded text

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class JobHeartbeatDB(Base):
    __tablename__ = "job_heartbeats"

    job_name = Column(String, primary_key=True)  # "reminder_scheduler" | "sla_monitor" | "subscription_scheduler" | "webhook_scheduler"

    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)  # "success" | "error"
    last_duration_ms = Column(Integer, nullable=True)
    last_error_message = Column(String, nullable=True)

    run_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)


# ---------- Pydantic Schemas ----------

class ErrorLogOut(BaseModel):
    id: str
    method: str
    path: str
    error_type: str
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class JobHeartbeatOut(BaseModel):
    job_name: str
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_duration_ms: Optional[int] = None
    last_error_message: Optional[str] = None
    run_count: int
    error_count: int
    is_healthy: bool  # computed — see services/monitoring.py's heartbeat_is_healthy()

    class Config:
        from_attributes = True
