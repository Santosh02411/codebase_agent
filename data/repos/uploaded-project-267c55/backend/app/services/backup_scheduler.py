"""
Automated database backup scheduler — same interval-loop shape as
services/reminder_scheduler.py / services/webhook_scheduler.py /
services/sla_monitor.py. Turns services/backup.py's admin "back up
now" button into a real, unattended, on-a-schedule habit: a fresh
backup every BACKUP_INTERVAL_HOURS, with services/backup.py's
apply_retention_policy() pruning old ones down to BACKUP_RETENTION_COUNT
right after, so disk usage stays bounded instead of growing forever.

Deliberately NOT started during the test suite (see main.py's
_launch_backup_scheduler — gated on TESTING) — unlike the other
schedulers here, a real backup tick does actual file I/O (a full
SQLite file copy, or a subprocess pg_dump), and every one of this
project's 300+ tests spins up a fresh app instance via TestClient's
lifespan handling, which would otherwise mean hundreds of real backup
files written to disk per test run for no reason.
"""

import asyncio
import logging
import os
import time

from app.services import backup as backup_svc
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "24")) * 3600
BACKUP_RETENTION_COUNT = int(os.environ.get("BACKUP_RETENTION_COUNT", str(backup_svc.DEFAULT_BACKUP_RETENTION_COUNT)))


def run_scheduled_backup() -> dict:
    """
    One backup-and-prune cycle. Returns create_backup()'s own result
    dict, with a "deleted_by_retention" key added so a caller (or a
    test) can see both halves of what happened in one place.
    """
    result = backup_svc.create_backup()
    if result.get("status") == "success":
        deleted = backup_svc.apply_retention_policy(BACKUP_RETENTION_COUNT)
        result["deleted_by_retention"] = deleted
    return result


async def _backup_loop(session_factory):
    while True:
        start = time.monotonic()
        try:
            result = run_scheduled_backup()
            db = session_factory()
            try:
                if result.get("status") == "success":
                    pruned = result.get("deleted_by_retention") or []
                    logger.info(
                        "Scheduled backup succeeded: %s (%d byte(s)); pruned %d old backup(s).",
                        result.get("filename"), result.get("size_bytes", 0), len(pruned),
                    )
                    monitoring_svc.record_job_heartbeat(db, "backup_scheduler", "success", int((time.monotonic() - start) * 1000))
                else:
                    logger.error("Scheduled backup failed: %s", result.get("message"))
                    monitoring_svc.record_job_heartbeat(db, "backup_scheduler", "error", int((time.monotonic() - start) * 1000), str(result.get("message"))[:500])
            finally:
                db.close()
        except Exception as error:
            logger.exception("Backup scheduler tick failed")
            try:
                db = session_factory()
                monitoring_svc.record_job_heartbeat(db, "backup_scheduler", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
                db.close()
            except Exception:
                pass
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)


def start_backup_scheduler(session_factory) -> asyncio.Task:
    return asyncio.create_task(_backup_loop(session_factory))
