"""
Monitoring & reliability service logic (Phase 18): database health
checks, error recording, background-job heartbeats, and in-memory API
request / notification metrics.

The in-memory metrics (API_METRICS, NOTIFICATION_METRICS below) are
deliberately module-level dicts, not database tables — they answer
"is something wrong right now", reset cleanly on every restart (a
fresh process shouldn't inherit yesterday's slow-request history), and
avoid writing a database row on every single request, which would be
a meaningful, pointless write-amplification cost for data nobody needs
to keep past the current process's lifetime. This is a single-process
deployment (no multi-worker/multi-instance metric aggregation needed);
a real multi-instance production deployment would export these to a
proper metrics backend (Prometheus, etc.) instead.
"""

import time
import traceback as tb_module
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.monitoring import ErrorLogDB, JobHeartbeatDB

# A job that hasn't ticked in this long is considered unhealthy — each
# scheduler's own interval is well under this, so a healthy job always
# reports well inside the window; only a genuinely stuck/crashed
# process ever crosses it.
JOB_STALE_THRESHOLD_MINUTES = 10
SLOW_REQUEST_THRESHOLD_MS = 1000
TRACEBACK_SNIPPET_LENGTH = 2000

_metrics_lock = Lock()
API_METRICS: dict = defaultdict(lambda: {"count": 0, "total_duration_ms": 0.0, "error_count": 0, "slow_count": 0})
NOTIFICATION_METRICS: dict = defaultdict(lambda: {"sent": 0, "failed": 0})


# ---------- Database health ----------

def check_database_health(db: Session) -> dict:
    start = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as error:  # noqa: BLE001
        return {"status": "error", "error": str(error)}


# ---------- Error logging ----------

def record_error(db: Session, org_id: Optional[str], method: str, path: str, error: Exception) -> None:
    """
    Called from main.py's global exception handler. Never raises
    itself — a failure while trying to LOG an error must never mask
    or replace the original error response the client is about to
    receive.
    """
    try:
        snippet = "".join(tb_module.format_exception(type(error), error, error.__traceback__))[-TRACEBACK_SNIPPET_LENGTH:]
        db.add(ErrorLogDB(
            org_id=org_id, method=method, path=path,
            error_type=type(error).__name__, error_message=str(error)[:1000], traceback_snippet=snippet,
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


# ---------- Job heartbeats ----------

def record_job_heartbeat(db: Session, job_name: str, status: str, duration_ms: int, error_message: Optional[str] = None) -> None:
    row = db.query(JobHeartbeatDB).filter(JobHeartbeatDB.job_name == job_name).first()
    if not row:
        row = JobHeartbeatDB(job_name=job_name, run_count=0, error_count=0)
        db.add(row)
    row.last_run_at = datetime.utcnow()
    row.last_status = status
    row.last_duration_ms = duration_ms
    row.last_error_message = error_message
    row.run_count += 1
    if status == "error":
        row.error_count += 1
    db.commit()


def heartbeat_is_healthy(row: JobHeartbeatDB) -> bool:
    if row.last_run_at is None:
        return False
    return row.last_run_at >= datetime.utcnow() - timedelta(minutes=JOB_STALE_THRESHOLD_MINUTES)


# ---------- API request metrics (in-memory) ----------

def record_api_request(method: str, path: str, duration_ms: float, status_code: int) -> None:
    key = f"{method} {path}"
    with _metrics_lock:
        entry = API_METRICS[key]
        entry["count"] += 1
        entry["total_duration_ms"] += duration_ms
        if status_code >= 500:
            entry["error_count"] += 1
        if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
            entry["slow_count"] += 1


def get_api_metrics_summary(top_n: int = 15) -> dict:
    with _metrics_lock:
        snapshot = {k: dict(v) for k, v in API_METRICS.items()}

    endpoints = []
    for key, stats in snapshot.items():
        avg_ms = round(stats["total_duration_ms"] / stats["count"], 1) if stats["count"] else 0.0
        endpoints.append({
            "endpoint": key, "request_count": stats["count"], "avg_duration_ms": avg_ms,
            "error_count": stats["error_count"], "slow_count": stats["slow_count"],
        })
    endpoints.sort(key=lambda e: e["avg_duration_ms"], reverse=True)

    total_requests = sum(e["request_count"] for e in endpoints)
    total_errors = sum(e["error_count"] for e in endpoints)
    return {
        "total_requests": total_requests,
        "total_errors": total_errors,
        "error_rate_percent": round(total_errors / total_requests * 100, 2) if total_requests else 0.0,
        "slowest_endpoints": endpoints[:top_n],
    }


# ---------- Notification metrics (in-memory) ----------

def record_notification_sent(channel: str, success: bool) -> None:
    with _metrics_lock:
        entry = NOTIFICATION_METRICS[channel]
        if success:
            entry["sent"] += 1
        else:
            entry["failed"] += 1


def get_notification_metrics_summary() -> dict:
    with _metrics_lock:
        return {channel: dict(stats) for channel, stats in NOTIFICATION_METRICS.items()}
