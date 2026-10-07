"""
Conflict resolution logic for syncing offline delivery records.

Strategy: last-write-wins based on `updated_at` timestamp.
See docs/TECHNICAL_ARCHITECTURE.md for the full reasoning and known
limitations of this approach.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.delivery_history import DeliveryHistoryDB
from app.models.failed_delivery_reason import FailedDeliveryReasonDB
from app.models.user import UserDB
from app.services.history import record_history_entry
from app.services.delivery_attempts import record_delivery_attempt, ATTEMPT_OUTCOMES
from app.services.notifications import notify_customer_of_status_change
from app.services.returns_workflow import handle_return_pickup_completion
from app.services.websocket_manager import broadcast_sync, tracking_room
from app.models.organization import OrganizationDB
from app.services.pod import org_requires_any_pod, pod_exists_for_delivery
from app.services.sla import assign_sla, classify_on_completion


def _log_synced_attempt(db: Session, db_record: DeliveryRecordDB, agent_id: str, status, is_partial: bool, reason_code_id: str | None, notes: str | None, attempted_at: datetime) -> None:
    """
    Shared by both branches of resolve_and_apply() below (new record,
    and an incoming-wins update) — logs a delivery_attempts row for a
    real attempt outcome synced from offline, mirroring what
    update_delivery() does for the online path. See
    routes/sync.py's SyncRecordIn docstring for why reason_code_id
    isn't hard-enforced here the way it is online.
    """
    status_value = status.value if hasattr(status, "value") else status
    outcome = "partial_delivery" if (status_value == "delivered" and is_partial) else status_value
    if outcome not in ATTEMPT_OUTCOMES:
        return

    reason = None
    if reason_code_id:
        reason = db.query(FailedDeliveryReasonDB).filter(
            FailedDeliveryReasonDB.id == reason_code_id,
            FailedDeliveryReasonDB.org_id == db_record.org_id,
        ).first()

    record_delivery_attempt(
        db, db_record, agent_id=agent_id, outcome=outcome,
        reason_code_id=reason.id if reason else None,
        reason_label=reason.label if reason else None,
        notes=notes, attempted_at=attempted_at,
    )


def _normalize_to_naive_utc(dt: datetime) -> datetime:
    """
    Browsers send timestamps like '2026-07-22T19:10:46.276Z', which Python
    parses as timezone-AWARE (they carry a 'this is UTC' marker). But
    SQLite/SQLAlchemy stores and returns timezone-NAIVE datetimes (no
    marker at all). Python refuses to compare aware and naive datetimes
    directly, which is exactly the bug this caused.

    Fix: always convert to UTC first (in case it wasn't already), then
    strip the timezone marker, so every datetime we compare or store is
    naive UTC consistently.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_and_apply(record_data: dict, db: Session) -> tuple[DeliveryRecordDB, dict | None]:
    """
    Given an incoming record from a client's offline sync batch, decide
    whether to insert it, update the existing one, or discard it (because
    the server's existing version is newer).

    Returns a (record, conflict) tuple. `record` is the FINAL resolved
    record as stored in the database — the client should overwrite its
    local copy with this, in case the server's version won the conflict.
    `conflict` is None unless the incoming change was actually discarded
    in favor of a newer server-side change, in which case it's a dict
    describing what was overridden and by whom — see routes/sync.py,
    which surfaces this to the client so a discarded change is never
    silent (previously: the caller had no way to tell "my change was
    applied" apart from "my change was silently dropped").

    Raises ValueError if the record's agent_id doesn't match a real user —
    the caller (routes/sync.py) catches this per-record so one bad record
    in a batch can't take down the whole sync request.
    """
    # Normalize incoming timestamps immediately so everything downstream
    # (comparisons AND storage) is consistently naive UTC.
    record_data["created_at"] = _normalize_to_naive_utc(record_data["created_at"])
    record_data["updated_at"] = _normalize_to_naive_utc(record_data["updated_at"])

    existing = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == record_data["id"]
    ).first()

    # /sync is intentionally left unauthenticated (see docs/SECURITY_AND_ACCESS.md),
    # so history entries from this path are attributed to the record's
    # assigned agent (looked up by ID) rather than a logged-in request user.
    agent = db.query(UserDB).filter(UserDB.id == record_data["agent_id"]).first()
    if not agent:
        raise ValueError(f"No user found matching agent_id '{record_data['agent_id']}'.")
    agent_name = agent.display_name

    # SECURITY: org_id is NEVER trusted from the client — since /sync has
    # no authentication, a client payload could otherwise claim any org_id
    # it wants. It's always overwritten here with the agent's own real
    # organization, derived server-side from the trusted DB lookup above.
    # This makes it impossible for a delivery to end up tagged to a
    # different organization than the agent it's assigned to, regardless
    # of what a sync payload claims.
    record_data["org_id"] = agent.org_id

    # SECURITY (cross-tenant write protection): if a record with this ID
    # already exists, it must belong to the SAME organization as the
    # agent making this sync request. Without this check, since /sync has
    # no authentication, a client could send an existing delivery ID from
    # a DIFFERENT organization paired with one of its own agent_ids, and
    # this code would otherwise happily overwrite another company's
    # delivery data. Treating this as a failed record (not a silent
    # skip, and not a crash) makes the rejection visible in the sync
    # response's `errors` list rather than disappearing quietly.
    if existing and existing.org_id != agent.org_id:
        raise ValueError(
            "This delivery ID belongs to a different organization and cannot be modified."
        )

    # reason_code_id isn't a column on DeliveryRecordDB (it lives on the
    # delivery_attempts log instead) — pull it out before constructing/
    # updating the record with the rest of record_data.
    reason_code_id = record_data.pop("reason_code_id", None)

    # ENFORCEMENT (Phase 1 — Proof of Delivery): this is the OTHER place
    # (besides routes/deliveries.py's online PATCH) a delivery can end
    # up "delivered" — an agent completing a delivery while offline,
    # synced here later. Same rule, same org opt-in: if the org requires
    # POD and none has been captured for this delivery yet, the record
    # is rejected (ValueError -> routes/sync.py's per-record `errors`
    # list) rather than silently marked delivered. It stays "pending" on
    # the client and retries on the next sync — which succeeds once the
    # agent's queued POD capture (see frontend services/podOfflineQueue.js)
    # has synced first. This never blocks orgs that haven't opted into
    # any pod_require_* setting.
    if record_data.get("status") == DeliveryStatus.delivered:
        org = db.query(OrganizationDB).filter(OrganizationDB.id == agent.org_id).first()
        if org and org_requires_any_pod(org) and not pod_exists_for_delivery(db, record_data["id"], agent.org_id):
            raise ValueError(
                "Proof of delivery is required before this delivery can be marked as delivered. "
                "It will sync automatically once proof of delivery has been captured."
            )

    if not existing:
        # No conflict — this is a new record, just insert it
        new_record = DeliveryRecordDB(**record_data)
        assign_sla(db, new_record)  # SLA (Phase 2): compute a deadline for this newly-synced delivery too
        if new_record.status == DeliveryStatus.delivered:
            classify_on_completion(new_record, new_record.updated_at)
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        record_history_entry(
            db,
            delivery_id=new_record.id,
            changed_by_user_id=record_data["agent_id"],
            changed_by_display_name=agent_name,
            old_status=None,
            new_status=new_record.status,
            changed_at=new_record.created_at,
            note="Created via offline sync",
        )
        _log_synced_attempt(
            db, new_record, agent_id=record_data["agent_id"], status=new_record.status,
            is_partial=record_data.get("is_partial", False), reason_code_id=reason_code_id,
            notes=record_data.get("notes") or record_data.get("partial_notes"),
            attempted_at=new_record.created_at,
        )
        return new_record, None

    # Conflict case: record already exists on the server.
    # Compare timestamps — whichever is later wins. Both sides are now
    # guaranteed naive UTC, so this comparison is safe.
    incoming_updated_at = record_data["updated_at"]
    if incoming_updated_at > existing.updated_at:
        # Incoming (client) change is newer — apply it
        old_status = existing.status
        existing.status = record_data["status"]
        existing.notes = record_data.get("notes")
        existing.location_note = record_data.get("location_note")
        existing.updated_at = incoming_updated_at
        if record_data.get("proof_of_delivery") is not None:
            existing.proof_of_delivery = record_data.get("proof_of_delivery")
        if existing.status == DeliveryStatus.delivered:
            existing.is_partial = record_data.get("is_partial", False)
            existing.partial_notes = record_data.get("partial_notes") if existing.is_partial else None
            classify_on_completion(existing, incoming_updated_at)
        db.commit()
        db.refresh(existing)

        if old_status != existing.status:
            record_history_entry(
                db,
                delivery_id=existing.id,
                changed_by_user_id=record_data["agent_id"],
                changed_by_display_name=agent_name,
                old_status=old_status,
                new_status=existing.status,
                changed_at=incoming_updated_at,
                note="Updated via offline sync",
            )
            notify_customer_of_status_change(
                db,
                delivery_id=existing.id,
                order_id=existing.order_id,
                new_status=existing.status.value if hasattr(existing.status, "value") else existing.status,
                customer_email=existing.customer_email,
                customer_phone=existing.customer_phone,
                customer_id=existing.customer_id,
            )
            broadcast_sync(tracking_room(existing.id), {
                "event": "status_changed",
                "status": existing.status.value if hasattr(existing.status, "value") else existing.status,
            })
            if existing.status == DeliveryStatus.delivered:
                # Same return/exchange completion hook as the online PATCH
                # path (routes/deliveries.py) — an agent completing a
                # return pickup while offline still needs to trigger the
                # refund/exchange once it syncs back.
                handle_return_pickup_completion(db, existing)
            _log_synced_attempt(
                db, existing, agent_id=record_data["agent_id"], status=existing.status,
                is_partial=record_data.get("is_partial", False), reason_code_id=reason_code_id,
                notes=record_data.get("notes") or record_data.get("partial_notes"),
                attempted_at=incoming_updated_at,
            )
        return existing, None
    else:
        # Server's existing version is newer or equal — keep it, discard
        # incoming. This is the exact case that used to be silent: the
        # client's change is thrown away with no signal anywhere. Now we
        # build a conflict record describing what got overridden and (if
        # we can tell from the history log) who made the winning change,
        # so routes/sync.py can hand this back to the client to surface.
        winning_entry = (
            db.query(DeliveryHistoryDB)
            .filter(DeliveryHistoryDB.delivery_id == existing.id)
            .order_by(DeliveryHistoryDB.changed_at.desc())
            .first()
        )
        conflict = {
            "id": existing.id,
            "order_id": existing.order_id,
            "your_status": record_data["status"].value if hasattr(record_data["status"], "value") else record_data["status"],
            "your_updated_at": incoming_updated_at.isoformat(),
            "kept_status": existing.status.value if hasattr(existing.status, "value") else existing.status,
            "kept_updated_at": existing.updated_at.isoformat(),
            "kept_by": winning_entry.changed_by_display_name if winning_entry else None,
        }
        return existing, conflict

