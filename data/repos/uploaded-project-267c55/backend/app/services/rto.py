"""
RTO business logic (Phase 7).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.rto import RtoRequestDB, RtoStatus
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_attempt import DeliveryAttemptDB
from app.models.failed_delivery_reason import FailedDeliveryReasonDB
from app.models.organization import OrganizationDB
from app.models.order import OrderDB
from app.services.refund import refund_order_for_delivery
from app.services.notifications import notify_customer_of_status_change
from app.services.websocket_manager import broadcast_sync, dispatcher_queue_room


class RtoError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def check_rto_eligibility(db: Session, db_record: DeliveryRecordDB, reason: Optional[FailedDeliveryReasonDB]) -> Optional[RtoRequestDB]:
    """
    Called right after a failed_attempt is logged (see
    services/delivery_attempts.py) — creates an RtoRequestDB row the
    moment this delivery qualifies, either because:
      (a) the reason code used is flagged eligible_for_rto, or
      (b) the delivery's total failed-attempt count has reached the
          org's rto_max_attempts threshold.
    A no-op if an RTO request already exists for this delivery
    (idempotent — a delivery can rack up further failed attempts after
    already qualifying without creating duplicate RTO rows) or if
    neither condition is met.
    """
    existing = db.query(RtoRequestDB).filter(RtoRequestDB.delivery_id == db_record.id).first()
    if existing:
        return None

    reason_triggers = bool(reason and reason.eligible_for_rto)

    org = db.query(OrganizationDB).filter(OrganizationDB.id == db_record.org_id).first()
    max_attempts = org.rto_max_attempts if org else 3
    failed_count = db.query(DeliveryAttemptDB).filter(
        DeliveryAttemptDB.delivery_id == db_record.id,
        DeliveryAttemptDB.outcome == "failed_attempt",
    ).count()
    attempts_trigger = failed_count >= max_attempts

    if not (reason_triggers or attempts_trigger):
        return None

    order = db.query(OrderDB).filter(OrderDB.delivery_id == db_record.id).first()
    rto = RtoRequestDB(
        org_id=db_record.org_id,
        delivery_id=db_record.id,
        order_id=order.id if order else None,
        customer_id=db_record.customer_id,
        agent_id=db_record.agent_id,
        reason_code_id=reason.id if reason else None,
        reason_label=reason.label if reason else f"Exceeded {max_attempts} delivery attempts",
    )
    db.add(rto)
    db.commit()
    db.refresh(rto)

    broadcast_sync(dispatcher_queue_room(db_record.org_id), {"event": "queue_changed", "reason": "rto_eligible"})
    if db_record.customer_id:
        try:
            notify_customer_of_status_change(
                db, delivery_id=db_record.id, order_id=db_record.order_id, new_status="rto_initiated",
                customer_email=db_record.customer_email, customer_phone=db_record.customer_phone,
                customer_id=db_record.customer_id,
            )
        except Exception:
            pass  # best-effort, same tolerance as every other notification send in this project
    return rto


def approve_rto(db: Session, rto: RtoRequestDB, note: Optional[str]) -> RtoRequestDB:
    if rto.status != RtoStatus.eligible:
        raise RtoError(f"Can't approve an RTO request that's already {rto.status.value}.")
    rto.status = RtoStatus.approved
    rto.approved_at = datetime.utcnow()
    rto.resolution_note = note
    db.commit()
    db.refresh(rto)
    return rto


def mark_rto_in_transit(db: Session, rto: RtoRequestDB) -> RtoRequestDB:
    if rto.status != RtoStatus.approved:
        raise RtoError("This RTO request must be approved before it can be marked in transit.")
    rto.status = RtoStatus.in_transit
    rto.in_transit_at = datetime.utcnow()
    db.commit()
    db.refresh(rto)
    return rto


def mark_rto_received(db: Session, rto: RtoRequestDB) -> RtoRequestDB:
    """
    The package is physically back — this is where the actual
    consequences happen. Reuses refund_order_for_delivery() exactly as
    cancellation does: for a prepaid order it issues a real refund AND
    restocks; for a COD order (never actually charged) it just
    restocks and marks refund_status "not_applicable" — that function
    already handles both cases correctly, so RTO doesn't duplicate the
    branching, just calls it and reads back what happened. Via Phase
    5's hook, an actual refund here also writes a ledger entry
    automatically. If this delivery has no linked Order at all (a
    manually-created delivery, never went through checkout), there's
    nothing to refund or restock — that's fine, RTO still completes.
    """
    if rto.status != RtoStatus.in_transit:
        raise RtoError("This RTO request must be in transit before it can be marked received.")

    order = refund_order_for_delivery(db, rto.delivery_id)
    if order and order.refund_status == "refunded":
        rto.refund_issued = True

    rto.status = RtoStatus.received_at_origin
    rto.received_at = datetime.utcnow()
    db.commit()
    db.refresh(rto)
    return rto


def cancel_rto(db: Session, rto: RtoRequestDB, note: Optional[str]) -> RtoRequestDB:
    """A dispatcher decides to give the delivery another shot instead of sending it back — e.g. the customer called and gave a corrected address."""
    if rto.status in (RtoStatus.received_at_origin, RtoStatus.cancelled):
        raise RtoError(f"Can't cancel an RTO request that's already {rto.status.value}.")
    rto.status = RtoStatus.cancelled
    rto.cancelled_at = datetime.utcnow()
    rto.resolution_note = note
    db.commit()
    db.refresh(rto)
    return rto


def compute_rto_analytics(db: Session, org_id: str) -> dict:
    requests = db.query(RtoRequestDB).filter(RtoRequestDB.org_id == org_id).all()
    resolved = [r for r in requests if r.status == RtoStatus.received_at_origin]

    durations = [
        (r.received_at - r.created_at).total_seconds() / 3600.0
        for r in resolved if r.received_at
    ]
    avg_resolution_hours = round(sum(durations) / len(durations), 1) if durations else None

    by_reason: dict = {}
    for r in requests:
        key = r.reason_label or "Unspecified"
        by_reason[key] = by_reason.get(key, 0) + 1

    return {
        "total_rto_requests": len(requests),
        "eligible": sum(1 for r in requests if r.status == RtoStatus.eligible),
        "approved": sum(1 for r in requests if r.status == RtoStatus.approved),
        "in_transit": sum(1 for r in requests if r.status == RtoStatus.in_transit),
        "received_at_origin": len(resolved),
        "cancelled": sum(1 for r in requests if r.status == RtoStatus.cancelled),
        "refunds_issued": sum(1 for r in requests if r.refund_issued),
        "avg_resolution_hours": avg_resolution_hours,
        "by_reason": [{"reason": k, "count": v} for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1])],
    }
