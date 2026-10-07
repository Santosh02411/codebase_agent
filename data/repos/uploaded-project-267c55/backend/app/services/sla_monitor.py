"""
Background SLA scanner — periodically walks every in-progress delivery
that has an SLA deadline and flips it to "at_risk" or "breached" as
thresholds are crossed, firing a dispatcher push notification on each
transition. Same shape as services/subscription_scheduler.py
(interval loop, started once from main.py's startup event, task kept
on app.state so it isn't garbage collected).
"""

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB
from app.models.sla import SLAPolicyDB
from app.services.sla import evaluate_active_delivery, ACTIVE_STATUSES
from app.services.notifications import notify_dispatchers_of_sla_event
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

SLA_SCAN_INTERVAL_SECONDS = 60


def run_sla_scan(db: Session) -> int:
    """One scan pass. Returns how many deliveries changed state. Exposed
    directly (not just via the loop) so it's callable synchronously
    from tests and from a "check now" admin action if ever needed."""
    deliveries = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.sla_target_at.isnot(None),
        DeliveryRecordDB.status.in_(ACTIVE_STATUSES),
    ).all()
    if not deliveries:
        return 0

    policy_ids = {d.sla_policy_id for d in deliveries if d.sla_policy_id}
    policies = db.query(SLAPolicyDB).filter(SLAPolicyDB.id.in_(policy_ids)).all() if policy_ids else []
    policy_by_id = {p.id: p for p in policies}

    now = datetime.utcnow()
    changed = 0
    for delivery in deliveries:
        event = evaluate_active_delivery(db, delivery, policy_by_id, now)
        if event:
            changed += 1
            already_notified = delivery.sla_breach_notified and event == "breached"
            if not already_notified:
                try:
                    notify_dispatchers_of_sla_event(db, delivery.org_id, delivery.order_id, event)
                except Exception:
                    logger.exception("Failed to send SLA %s notification for delivery %s", event, delivery.id)
                if event == "breached":
                    delivery.sla_breach_notified = True
    if changed:
        db.commit()
    return changed


async def _scan_loop(session_factory):
    while True:
        start = time.monotonic()
        try:
            db = session_factory()
            try:
                count = run_sla_scan(db)
                if count:
                    logger.info("SLA scan updated %d delivery/deliveries.", count)
                monitoring_svc.record_job_heartbeat(db, "sla_monitor", "success", int((time.monotonic() - start) * 1000))
            finally:
                db.close()
        except Exception as error:
            logger.exception("SLA scan tick failed")
            try:
                db = session_factory()
                monitoring_svc.record_job_heartbeat(db, "sla_monitor", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
                db.close()
            except Exception:
                pass
        await asyncio.sleep(SLA_SCAN_INTERVAL_SECONDS)


def start_sla_monitor(session_factory) -> asyncio.Task:
    return asyncio.create_task(_scan_loop(session_factory))
