"""
SLA business logic (Phase 2): matching a delivery to the right policy,
computing/re-computing its deadline, and classifying on-time/at-risk/
breached/met/missed. The periodic breach scan itself lives in
services/sla_monitor.py (background loop, same shape as
services/subscription_scheduler.py) — this module is the pure logic
both that loop and the HTTP routes call into.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.sla import SLAPolicyDB

ACTIVE_STATUSES = (DeliveryStatus.pending, DeliveryStatus.picked_up, DeliveryStatus.out_for_delivery)


def select_policy_for_delivery(db: Session, org_id: str, delivery: DeliveryRecordDB) -> Optional[SLAPolicyDB]:
    """
    Best-matching active policy for this delivery, most specific first:
    (zone+type+priority) > (zone+type) > (zone+priority) > (zone only)
    > (type+priority) > (type only) > (priority only) > org-wide default.
    A dimension on the policy that's null always matches; a dimension
    that's SET on the policy must equal the delivery's value exactly.
    Returns None if the org has no active policy at all (not even a
    default) — SLA tracking is then simply inactive for that org.
    """
    policies = db.query(SLAPolicyDB).filter(
        SLAPolicyDB.org_id == org_id,
        SLAPolicyDB.active == True,  # noqa: E712
    ).all()
    if not policies:
        return None

    def matches(p: SLAPolicyDB) -> bool:
        if p.zone and p.zone != delivery.zone:
            return False
        if p.delivery_type and p.delivery_type != delivery.delivery_type:
            return False
        if p.priority and p.priority != delivery.priority:
            return False
        return True

    def specificity(p: SLAPolicyDB) -> int:
        return sum(1 for f in (p.zone, p.delivery_type, p.priority) if f)

    candidates = [p for p in policies if matches(p)]
    if not candidates:
        return None
    return max(candidates, key=specificity)


def assign_sla(db: Session, delivery: DeliveryRecordDB) -> None:
    """
    (Re)computes and stores the SLA deadline for a delivery, based on
    the best-matching active policy at THIS moment. Called when a
    delivery is created/assigned and whenever its zone/type/priority
    changes (those are exactly the fields matching depends on). Does
    NOT commit — caller is expected to already be inside a commit (this
    mirrors record_history_entry's sibling helpers, which DO commit
    themselves; here it's left to the caller since assign_sla is always
    invoked alongside other field changes on the same row in this
    project's existing routes, so a single commit covers both).
    """
    policy = select_policy_for_delivery(db, delivery.org_id, delivery)
    if not policy:
        delivery.sla_policy_id = None
        delivery.sla_target_at = None
        delivery.sla_status = "not_applicable"
        return

    delivery.sla_policy_id = policy.id
    delivery.sla_target_at = delivery.created_at + timedelta(minutes=policy.target_minutes)
    if delivery.status in (DeliveryStatus.delivered, DeliveryStatus.cancelled):
        return  # terminal deliveries keep whatever final classification they already have
    delivery.sla_status = "on_track"
    delivery.sla_breach_notified = False


def classify_on_completion(delivery: DeliveryRecordDB, completed_at: datetime) -> None:
    """Call when a delivery is marked `delivered` — freezes its final met/missed classification."""
    if not delivery.sla_target_at:
        delivery.sla_status = "not_applicable"
        return
    delivery.sla_status = "met" if completed_at <= delivery.sla_target_at else "missed"


def evaluate_active_delivery(db: Session, delivery: DeliveryRecordDB, policy_by_id: dict, now: datetime) -> str | None:
    """
    Called by the periodic scan for one still-in-progress delivery.
    Returns "breached", "at_risk", or None (no change / not applicable)
    — mutates delivery.sla_status in place when it changes, but does
    NOT commit (caller commits once per batch).
    """
    if not delivery.sla_target_at or delivery.status not in ACTIVE_STATUSES:
        return None

    if now >= delivery.sla_target_at:
        if delivery.sla_status != "breached":
            delivery.sla_status = "breached"
            return "breached"
        return None

    policy = policy_by_id.get(delivery.sla_policy_id)
    warning_pct = policy.warning_threshold_percent if policy else 80
    total_seconds = (delivery.sla_target_at - delivery.created_at).total_seconds()
    elapsed_seconds = (now - delivery.created_at).total_seconds()
    if total_seconds > 0 and (elapsed_seconds / total_seconds) * 100 >= warning_pct:
        if delivery.sla_status == "on_track":
            delivery.sla_status = "at_risk"
            return "at_risk"
    return None


# ---------- Analytics ----------

def compute_sla_analytics(db: Session, org_id: str) -> dict:
    """
    Live-computed SLA analytics for an org — no stored aggregates, same
    "just query it" approach as routes/analytics.py's admin dashboard.
    """
    deliveries = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == org_id,
        DeliveryRecordDB.sla_target_at.isnot(None),
    ).all()

    completed = [d for d in deliveries if d.sla_status in ("met", "missed")]
    met = [d for d in completed if d.sla_status == "met"]
    missed = [d for d in completed if d.sla_status == "missed"]
    in_progress = [d for d in deliveries if d.sla_status in ("on_track", "at_risk", "breached")]

    sla_percentage = round(len(met) / len(completed) * 100, 1) if completed else None

    delivered_durations = [
        (d.updated_at - d.created_at).total_seconds() / 60.0
        for d in completed if d.updated_at and d.created_at
    ]
    avg_delivery_minutes = round(sum(delivered_durations) / len(delivered_durations), 1) if delivered_durations else None

    delays = [
        max(0.0, (d.updated_at - d.sla_target_at).total_seconds() / 60.0)
        for d in missed if d.updated_at and d.sla_target_at
    ]
    avg_delay_minutes = round(sum(delays) / len(delays), 1) if delays else 0.0

    def _breakdown(key_fn, label: str) -> list[dict]:
        buckets: dict[str, dict] = {}
        for d in completed:
            key = key_fn(d) or "Unassigned"
            b = buckets.setdefault(key, {label: key, "met": 0, "missed": 0})
            b["met" if d.sla_status == "met" else "missed"] += 1
        result = []
        for b in buckets.values():
            total = b["met"] + b["missed"]
            b["sla_percentage"] = round(b["met"] / total * 100, 1) if total else None
            b["total"] = total
            result.append(b)
        return sorted(result, key=lambda r: -r["total"])

    return {
        "sla_percentage": sla_percentage,
        "total_tracked": len(deliveries),
        "completed": len(completed),
        "met": len(met),
        "missed": len(missed),
        "currently_on_track": sum(1 for d in in_progress if d.sla_status == "on_track"),
        "currently_at_risk": sum(1 for d in in_progress if d.sla_status == "at_risk"),
        "currently_breached": sum(1 for d in in_progress if d.sla_status == "breached"),
        "avg_delivery_minutes": avg_delivery_minutes,
        "avg_delay_minutes": avg_delay_minutes,
        "by_agent": _breakdown(lambda d: d.agent_id, "agent_id"),
        "by_zone": _breakdown(lambda d: d.zone, "zone"),
    }
