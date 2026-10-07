"""
Webhook delivery scheduler (Phase 14) — same interval-loop shape as
services/reminder_scheduler.py / services/sla_monitor.py. Picks up
every WebhookDeliveryDB row that's "pending" and due (next_retry_at is
None — i.e. never attempted yet — or in the past) and attempts it.
"""

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.webhook import WebhookDeliveryDB
from app.services.webhooks import attempt_delivery
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

WEBHOOK_SCAN_INTERVAL_SECONDS = 60


def run_webhook_delivery_scan(db: Session) -> int:
    now = datetime.utcnow()
    due = db.query(WebhookDeliveryDB).filter(
        WebhookDeliveryDB.status == "pending",
        or_(WebhookDeliveryDB.next_retry_at.is_(None), WebhookDeliveryDB.next_retry_at <= now),
    ).all()

    attempted = 0
    for delivery in due:
        try:
            attempt_delivery(db, delivery)
            attempted += 1
        except Exception:
            logger.exception("Webhook delivery attempt crashed for %s", delivery.id)
            db.rollback()
    return attempted


async def _webhook_loop(session_factory):
    while True:
        start = time.monotonic()
        try:
            db = session_factory()
            try:
                count = run_webhook_delivery_scan(db)
                if count:
                    logger.info("Webhook scan attempted %d delivery(ies).", count)
                monitoring_svc.record_job_heartbeat(db, "webhook_scheduler", "success", int((time.monotonic() - start) * 1000))
            finally:
                db.close()
        except Exception as error:
            logger.exception("Webhook scan tick failed")
            try:
                db = session_factory()
                monitoring_svc.record_job_heartbeat(db, "webhook_scheduler", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
                db.close()
            except Exception:
                pass
        await asyncio.sleep(WEBHOOK_SCAN_INTERVAL_SECONDS)


def start_webhook_scheduler(session_factory) -> asyncio.Task:
    return asyncio.create_task(_webhook_loop(session_factory))
