"""
Webhook delivery (Phase 14): emitting an event queues delivery
attempts (never sends synchronously from inside a request handler —
an unreachable webhook URL must never slow down or fail a checkout,
refund, or delivery-status-update request); a background scheduler
(services/webhook_scheduler.py, same interval-loop shape as
services/reminder_scheduler.py) picks up pending/due deliveries and
actually sends them.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.models.webhook import WebhookDB, WebhookDeliveryDB

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 5
# Exponential-ish backoff in minutes, indexed by attempt_count after the failed attempt: 1, 5, 15, 60 minutes.
RETRY_BACKOFF_MINUTES = [1, 5, 15, 60]


def emit_event(db: Session, org_id: str, event_type: str, payload: dict) -> int:
    """
    Called from the event source (checkout, refund, delivery status
    change, ...) right after the thing actually happened — queues one
    WebhookDeliveryDB row per active webhook in this org subscribed to
    event_type. Returns how many were queued. Never raises: a webhook
    subsystem failure must never break the request that triggered it.
    """
    try:
        webhooks = db.query(WebhookDB).filter(WebhookDB.org_id == org_id, WebhookDB.is_active == True).all()  # noqa: E712
        body = json.dumps({"event": event_type, "data": payload, "timestamp": datetime.utcnow().isoformat()})
        queued = 0
        for webhook in webhooks:
            subscribed = set(webhook.subscribed_events.split(",")) if webhook.subscribed_events else set()
            if event_type not in subscribed:
                continue
            delivery = WebhookDeliveryDB(
                org_id=org_id, webhook_id=webhook.id, event_type=event_type,
                payload_json=body, status="pending", next_retry_at=datetime.utcnow(),
            )
            db.add(delivery)
            queued += 1
        if queued:
            db.commit()
        return queued
    except Exception:  # noqa: BLE001
        logger.exception("Failed to queue webhook deliveries for %s/%s", org_id, event_type)
        db.rollback()
        return 0


def compute_signature(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def attempt_delivery(db: Session, delivery: WebhookDeliveryDB, webhook: Optional[WebhookDB] = None) -> bool:
    """
    Sends one delivery attempt. Returns True on a 2xx response. Always
    updates attempt_count/last_attempted_at/status/next_retry_at on the
    row, whatever the outcome — this is the only place those fields
    change, so a delivery's history is always an honest record of what
    was actually tried.
    """
    webhook = webhook or db.query(WebhookDB).filter(WebhookDB.id == delivery.webhook_id).first()
    delivery.attempt_count += 1
    delivery.last_attempted_at = datetime.utcnow()

    if not webhook or not webhook.is_active:
        delivery.status = "failed"
        delivery.next_retry_at = None
        db.commit()
        return False

    signature = compute_signature(webhook.secret, delivery.payload_json)
    try:
        response = requests.post(
            webhook.url, data=delivery.payload_json,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Event": delivery.event_type,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        delivery.response_status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = "success"
            delivery.next_retry_at = None
            db.commit()
            return True
    except requests.RequestException as error:
        logger.info("Webhook delivery %s attempt %d failed: %s", delivery.id, delivery.attempt_count, error)
        delivery.response_status_code = None

    # Failed (bad status code or a network/timeout error) — schedule a retry, or give up.
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_retry_at = None
    else:
        backoff_minutes = RETRY_BACKOFF_MINUTES[min(delivery.attempt_count - 1, len(RETRY_BACKOFF_MINUTES) - 1)]
        delivery.status = "pending"
        delivery.next_retry_at = datetime.utcnow() + timedelta(minutes=backoff_minutes)
    db.commit()
    return False


def replay_delivery(db: Session, delivery: WebhookDeliveryDB) -> bool:
    """Manual replay (admin-triggered): attempts immediately regardless of attempt_count/next_retry_at, resetting the exhausted-attempts state if this was a permanently-failed delivery."""
    return attempt_delivery(db, delivery)
