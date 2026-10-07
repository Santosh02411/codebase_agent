"""
Shared helper for writing to the general admin action log
(ActionLogDB — see models/action_log.py). Used from admin.py (user
management), products.py (product CRUD + store settings), and
coupons.py (coupon CRUD) so every admin write action is recorded the
same way, with the same shape, regardless of which route triggered it.
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.action_log import ActionLogDB


def diff_fields(before: dict, after: dict) -> dict:
    """
    Compares two flat dicts of the same record (pre- and post-update)
    and returns only the fields that actually changed, as
    {field: {"from": old, "to": new}}. Fields only present in one side,
    or whose value is unchanged, are skipped — this keeps the stored
    diff to just what an admin reviewing the log actually needs to see.
    """
    changed = {}
    for key, new_value in after.items():
        if key not in before:
            continue
        old_value = before[key]
        if old_value != new_value:
            changed[key] = {"from": old_value, "to": new_value}
    return changed


def record_action(
    db: Session,
    org_id: str,
    actor_user_id: str,
    actor_display_name: str,
    action: str,
    entity_type: str,
    summary: str,
    entity_id: str = None,
    entity_label: str = None,
    before: dict = None,
    after: dict = None,
):
    """
    Writes one action-log entry. Pass `before`/`after` (flat dicts of
    the relevant fields) for update actions to have a diff computed and
    stored automatically; leave both None for create/delete actions,
    where the summary line already says what happened.
    """
    changes_json = None
    if before is not None and after is not None:
        diff = diff_fields(before, after)
        if diff:
            changes_json = json.dumps(diff, default=str)

    entry = ActionLogDB(
        org_id=org_id,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary,
        changes=changes_json,
        created_at=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
