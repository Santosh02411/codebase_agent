"""
Notification template routes (Phase 10). See
models/notification_template.py's module docstring for the design.
Admin-only, same tier as any other org-wide configuration
(settings.* from Phase 4's permission catalog).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.notification_template import (
    NotificationTemplateDB, NotificationTemplateUpsert, NotificationTemplateOut, EVENT_TYPES,
)
from app.models.user import UserDB
from app.services.permissions import require_permission
from app.services.notification_templates import get_effective_template

router = APIRouter(prefix="/admin/notification-templates", tags=["notification-templates"])


@router.get("/", response_model=List[NotificationTemplateOut])
def list_effective_templates(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("settings.view"))):
    """Every recognized event type, each resolved to what would ACTUALLY be sent right now (the org's customization if one exists, otherwise the built-in default) — so the settings UI always shows real, current behavior."""
    return [
        NotificationTemplateOut(event_type=event_type, **get_effective_template(db, current_user.org_id, event_type))
        for event_type in EVENT_TYPES
    ]


@router.put("/{event_type}", response_model=NotificationTemplateOut)
def upsert_template(
    event_type: str,
    payload: NotificationTemplateUpsert,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("settings.manage")),
):
    if event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown event type. Valid types: {', '.join(EVENT_TYPES)}")

    existing = db.query(NotificationTemplateDB).filter(
        NotificationTemplateDB.org_id == current_user.org_id, NotificationTemplateDB.event_type == event_type,
    ).first()
    if existing:
        existing.subject = payload.subject
        existing.body = payload.body
        existing.email_enabled = payload.email_enabled
        existing.sms_enabled = payload.sms_enabled
        existing.whatsapp_enabled = payload.whatsapp_enabled
        existing.updated_at = datetime.utcnow()
    else:
        existing = NotificationTemplateDB(org_id=current_user.org_id, event_type=event_type, **payload.dict())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return NotificationTemplateOut(event_type=event_type, **get_effective_template(db, current_user.org_id, event_type))


@router.delete("/{event_type}")
def reset_template_to_default(
    event_type: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("settings.manage")),
):
    """Removes the org's customization, reverting to the built-in default for this event type."""
    existing = db.query(NotificationTemplateDB).filter(
        NotificationTemplateDB.org_id == current_user.org_id, NotificationTemplateDB.event_type == event_type,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    return {"message": "Reverted to default template."}
