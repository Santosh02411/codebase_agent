"""
The /sync endpoint — this is what the client calls when connectivity
returns, sending a batch of records that were saved offline in IndexedDB.

For each record, conflict resolution is applied (see services/conflict_resolver.py).
The response tells the client the FINAL state of each record, so the client
can update its local IndexedDB copy if the server's version won a conflict.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.db.session import get_db
from app.models.delivery import DeliveryRecordOut, DeliveryStatus
from app.services.conflict_resolver import resolve_and_apply
from app.services.rate_limiter import limiter
from datetime import datetime

router = APIRouter(tags=["sync"])


class SyncRecordIn(BaseModel):
    """Shape of each record sent in a sync batch from the client."""
    id: str
    agent_id: str
    order_id: str
    status: DeliveryStatus
    notes: str | None = None
    location_note: str | None = None
    created_at: datetime
    updated_at: datetime
    zone: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    expected_by: datetime | None = None
    slot_start: datetime | None = None
    slot_end: datetime | None = None
    org_id: str | None = None
    proof_of_delivery: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None

    # Failed-delivery reason (see models/failed_delivery_reason.py).
    # NOT hard-enforced here the way update_delivery() enforces it —
    # /sync is unauthenticated, best-effort, and processes a whole
    # offline batch; rejecting a record over a missing reason code
    # would strand it retrying forever with no way for the agent to
    # fix it until they're back online anyway. If present, it's
    # recorded on the attempt log; if absent, the attempt is still
    # logged, just without a reason (visible as a gap for a dispatcher
    # to follow up on, rather than lost data).
    reason_code_id: str | None = None
    is_partial: bool = False
    partial_notes: str | None = None


class SyncRequest(BaseModel):
    records: List[SyncRecordIn]


class SyncResponse(BaseModel):
    resolved_records: List[DeliveryRecordOut]
    errors: List[dict] = []
    conflicts: List[dict] = []


@router.post("/sync", response_model=SyncResponse)
@limiter.limit("30/minute")
def sync_records(request: Request, payload: SyncRequest, db: Session = Depends(get_db)):
    """
    Accepts a batch of offline records and resolves each one against the
    server's current state. Returns the final resolved version of every
    record so the client can reconcile its local IndexedDB copy.

    Each record is processed independently — same "one bad row shouldn't
    sink the whole batch" principle as bulk import. A record that fails
    (e.g. its agent_id doesn't match any real user) is reported in
    `errors` rather than aborting the request; it simply stays "pending"
    on the client and gets retried on the next sync attempt, so no data is
    lost, just delayed.

    A record whose incoming (client-side, offline) change was discarded
    because the server already had a newer one — last-write-wins actually
    throwing away real data — is reported in `conflicts` rather than
    disappearing silently. See services/conflict_resolver.py.

    Rate limited to 30 requests/minute per IP — generous enough for normal
    usage (the frontend auto-syncs at most every 15 seconds, i.e. 4/minute,
    plus occasional manual "Sync Now" clicks) while still capping abuse of
    this endpoint, which has no authentication.
    """
    resolved = []
    errors = []
    conflicts = []
    for record in payload.records:
        try:
            final_record, conflict = resolve_and_apply(record.model_dump(), db)
            resolved.append(final_record)
            if conflict:
                conflicts.append(conflict)
        except ValueError as e:
            errors.append({"id": record.id, "error": str(e)})

    return {"resolved_records": resolved, "errors": errors, "conflicts": conflicts}
