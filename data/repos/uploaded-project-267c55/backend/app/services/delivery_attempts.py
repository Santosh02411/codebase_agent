"""
Shared helper for logging a delivery ATTEMPT row (see
models/delivery_attempt.py for what distinguishes an attempt from a
plain history entry). Called from every place a real
delivered/failed_attempt/partial_delivery outcome gets recorded:
update_delivery() and bulk_update_status() (routes/deliveries.py), and
resolve_and_apply() (services/conflict_resolver.py, the offline sync
path) — centralizing it here keeps attempt_number/attempt_count
bookkeeping consistent no matter which path caused the change.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB
from app.models.delivery_attempt import DeliveryAttemptDB

# Only these three outcomes represent a real completed attempt at the
# door — every other status (pending, picked_up, out_for_delivery,
# cancelled) is a lifecycle/logistics state, not an attempt outcome.
ATTEMPT_OUTCOMES = {"delivered", "failed_attempt", "partial_delivery"}


def record_delivery_attempt(
    db: Session,
    db_record: DeliveryRecordDB,
    agent_id: Optional[str],
    outcome: str,
    reason_code_id: Optional[str] = None,
    reason_label: Optional[str] = None,
    notes: Optional[str] = None,
    attempted_at: Optional[datetime] = None,
) -> DeliveryAttemptDB:
    db_record.attempt_count = (db_record.attempt_count or 0) + 1
    entry = DeliveryAttemptDB(
        delivery_id=db_record.id,
        org_id=db_record.org_id,
        agent_id=agent_id,
        attempt_number=db_record.attempt_count,
        outcome=outcome,
        reason_code_id=reason_code_id,
        reason_label=reason_label,
        notes=notes,
        attempted_at=attempted_at or datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(db_record)

    # RTO (Phase 7): the ONE place every failed-attempt path in this
    # project already funnels through (update_delivery, bulk_update_status,
    # and the offline-sync conflict resolver all call this function) —
    # so this is also the one place RTO eligibility needs to be checked,
    # rather than duplicating the check at each call site.
    if outcome == "failed_attempt":
        from app.models.failed_delivery_reason import FailedDeliveryReasonDB
        from app.services.rto import check_rto_eligibility
        reason = db.query(FailedDeliveryReasonDB).filter(FailedDeliveryReasonDB.id == reason_code_id).first() if reason_code_id else None
        check_rto_eligibility(db, db_record, reason)

    return entry
