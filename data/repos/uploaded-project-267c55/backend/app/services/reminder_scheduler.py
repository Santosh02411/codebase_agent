"""
Reminder scheduler (Phase 10) — a periodic scan (same interval-loop
shape as services/sla_monitor.py / services/subscription_scheduler.py)
firing two new proactive notification types:

  delivery_reminder     — a delivery with a customer-picked slot_start
                           coming up soon that hasn't shipped yet.
  subscription_reminder — a subscription whose next_run_date is coming
                           up soon, giving the customer a chance to
                           skip/cancel before it auto-generates.

Each delivery/subscription is only ever reminded ONCE per upcoming
occurrence — tracked via a `reminder_sent_at` marker rather than a
time-window re-scan, so a slow-running or restarted scheduler can never
double-send.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.subscription import SubscriptionDB, SubscriptionStatus
from app.models.customer import CustomerDB
from app.services.notification_templates import send_templated_notification
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

REMINDER_SCAN_INTERVAL_SECONDS = 1800  # 30 minutes — reminders aren't as time-critical as SLA breaches
DELIVERY_REMINDER_WINDOW_HOURS = 24
SUBSCRIPTION_REMINDER_WINDOW_DAYS = 2


def run_delivery_reminder_scan(db: Session) -> int:
    """Reminds customers whose delivery has a slot starting within the next DELIVERY_REMINDER_WINDOW_HOURS and hasn't gone out yet."""
    now = datetime.utcnow()
    window_end = now + timedelta(hours=DELIVERY_REMINDER_WINDOW_HOURS)

    candidates = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.slot_start.isnot(None),
        DeliveryRecordDB.slot_start >= now,
        DeliveryRecordDB.slot_start <= window_end,
        DeliveryRecordDB.status.in_([DeliveryStatus.pending, DeliveryStatus.picked_up]),
        DeliveryRecordDB.reminder_sent_at.is_(None),
        DeliveryRecordDB.customer_id.isnot(None),
    ).all()

    sent = 0
    for delivery in candidates:
        try:
            send_templated_notification(
                db, org_id=delivery.org_id, event_type="delivery_reminder", order_id=delivery.order_id,
                customer_id=delivery.customer_id, customer_email=delivery.customer_email,
                customer_phone=delivery.customer_phone, delivery_id=delivery.id,
            )
            delivery.reminder_sent_at = now
            db.commit()
            sent += 1
        except Exception:
            logger.exception("Failed to send delivery reminder for %s", delivery.id)
            db.rollback()
    return sent


def run_subscription_reminder_scan(db: Session) -> int:
    """Reminds customers whose subscription is about to renew within SUBSCRIPTION_REMINDER_WINDOW_DAYS, giving them a chance to skip/cancel first."""
    now = datetime.utcnow()
    window_end = now + timedelta(days=SUBSCRIPTION_REMINDER_WINDOW_DAYS)

    candidates = db.query(SubscriptionDB).filter(
        SubscriptionDB.status == SubscriptionStatus.active,
        SubscriptionDB.next_run_date >= now,
        SubscriptionDB.next_run_date <= window_end,
        SubscriptionDB.reminder_sent_at.is_(None),
    ).all()

    sent = 0
    for subscription in candidates:
        try:
            customer = db.query(CustomerDB).filter(CustomerDB.id == subscription.customer_id).first()
            send_templated_notification(
                db, org_id=subscription.org_id, event_type="subscription_reminder", order_id=subscription.id,
                customer_id=subscription.customer_id, customer_email=customer.email if customer else None,
                customer_phone=subscription.phone,
            )
            subscription.reminder_sent_at = now
            db.commit()
            sent += 1
        except Exception:
            logger.exception("Failed to send subscription reminder for %s", subscription.id)
            db.rollback()
    return sent


async def _reminder_loop(session_factory):
    while True:
        start = time.monotonic()
        try:
            db = session_factory()
            try:
                delivery_count = run_delivery_reminder_scan(db)
                subscription_count = run_subscription_reminder_scan(db)
                if delivery_count or subscription_count:
                    logger.info("Reminder scan sent %d delivery and %d subscription reminder(s).", delivery_count, subscription_count)
                monitoring_svc.record_job_heartbeat(db, "reminder_scheduler", "success", int((time.monotonic() - start) * 1000))
            finally:
                db.close()
        except Exception as error:
            logger.exception("Reminder scan tick failed")
            try:
                db = session_factory()
                monitoring_svc.record_job_heartbeat(db, "reminder_scheduler", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
                db.close()
            except Exception:
                pass
        await asyncio.sleep(REMINDER_SCAN_INTERVAL_SECONDS)


def start_reminder_scheduler(session_factory) -> asyncio.Task:
    return asyncio.create_task(_reminder_loop(session_factory))
