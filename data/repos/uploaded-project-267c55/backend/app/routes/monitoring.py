"""
Monitoring & reliability routes (Phase 18):
  GET  /health                  — public, unauthenticated liveness probe
  GET  /health/db               — public, database connectivity check
  GET  /admin/monitoring/*      — admin-only, detailed observability
  POST /admin/monitoring/backups (+ list/verify)

Health checks are deliberately public and unauthenticated — a load
balancer or uptime monitor polling this every few seconds shouldn't
need credentials, and nothing here reveals anything sensitive (just
"is the process up" / "can it reach its database"). Everything with
actual operational detail (error logs, job heartbeats, per-endpoint
metrics, backups) is admin-only, same tier as every other
organization-operational surface in this project.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import UserDB
from app.models.monitoring import ErrorLogDB, JobHeartbeatDB, ErrorLogOut, JobHeartbeatOut
from app.routes.admin import require_admin
from app.services import monitoring as monitoring_svc
from app.services import backup as backup_svc
from app.services.websocket_manager import manager as ws_manager

router = APIRouter(tags=["monitoring"])


# ---------- Public health checks ----------

@router.get("/health")
def health():
    """Liveness only — if this responds at all, the process is up. Doesn't touch the database, so it can't report 'unhealthy' just because the DB is briefly slow (that's what /health/db is for)."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    result = monitoring_svc.check_database_health(db)
    if result["status"] != "ok":
        raise HTTPException(status_code=503, detail=result)
    return result


# ---------- Admin observability ----------

@router.get("/admin/monitoring/status")
def monitoring_status(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """One-shot overview: DB health, every background job's heartbeat/health, and live WebSocket connection counts — the "is everything OK right now" dashboard."""
    db_health = monitoring_svc.check_database_health(db)
    heartbeats = db.query(JobHeartbeatDB).all()
    jobs = []
    for h in heartbeats:
        jobs.append(JobHeartbeatOut(
            job_name=h.job_name, last_run_at=h.last_run_at, last_status=h.last_status,
            last_duration_ms=h.last_duration_ms, last_error_message=h.last_error_message,
            run_count=h.run_count, error_count=h.error_count,
            is_healthy=monitoring_svc.heartbeat_is_healthy(h),
        ))
    return {
        "database": db_health,
        "background_jobs": jobs,
        "websocket": ws_manager.connection_count(),
        "all_jobs_healthy": all(j.is_healthy for j in jobs) if jobs else None,
    }


@router.get("/admin/monitoring/api-metrics")
def api_metrics(current_user: UserDB = Depends(require_admin)):
    """
    In-memory, process-lifetime metrics — see services/monitoring.py's
    module docstring for why these aren't persisted. NOT org-scoped:
    request timing/error-rate data describes the SERVER's operational
    health, not any one org's business data, so there's nothing here
    to isolate per tenant.
    """
    return monitoring_svc.get_api_metrics_summary()


@router.get("/admin/monitoring/notification-metrics")
def notification_metrics(current_user: UserDB = Depends(require_admin)):
    return monitoring_svc.get_notification_metrics_summary()


@router.get("/admin/monitoring/errors", response_model=List[ErrorLogOut])
def list_errors(limit: int = 50, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    """
    Deliberately NOT org-filtered — an unhandled exception can happen
    before org context is even resolvable (e.g. a malformed request
    that fails before auth runs), so error_logs.org_id is nullable and
    this list is server-wide, same reasoning as the metrics endpoints
    above. Any admin account on this single-tenant-per-deployment demo
    can see it; a real multi-tenant SaaS would restrict this to a
    platform-operator role this project doesn't have (see Phase 16's
    docstring on that same limitation for organization suspension).
    """
    limit = min(max(limit, 1), 200)
    return db.query(ErrorLogDB).order_by(ErrorLogDB.created_at.desc()).limit(limit).all()


# ---------- Backups ----------

@router.post("/admin/monitoring/backups")
def trigger_backup(current_user: UserDB = Depends(require_admin)):
    result = backup_svc.create_backup()
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.get("/admin/monitoring/backups")
def list_backups(current_user: UserDB = Depends(require_admin)):
    return backup_svc.list_backups()


@router.get("/admin/monitoring/backups/{filename}/verify")
def verify_backup(filename: str, current_user: UserDB = Depends(require_admin)):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    result = backup_svc.verify_backup(filename)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result
