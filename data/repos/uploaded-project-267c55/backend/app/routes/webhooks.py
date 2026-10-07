"""
API key & webhook admin routes (Phase 14). Dispatcher/admin only —
same tier as every other "org configuration" surface in this project
(warehouse settings, SLA policies, RBAC). Issuing external API access
or wiring up outbound webhooks is an operational/admin decision, not
something every staff member should be able to do.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.webhook import (
    ApiKeyDB, WebhookDB, WebhookDeliveryDB, API_SCOPES, WEBHOOK_EVENTS,
    generate_api_key, generate_webhook_secret,
    ApiKeyCreate, ApiKeyOut, ApiKeyCreatedOut,
    WebhookCreate, WebhookUpdate, WebhookOut, WebhookDeliveryOut,
)
from app.routes.auth import get_current_user
from app.services.webhooks import replay_delivery
from app.services.action_log import record_action

router = APIRouter(prefix="/admin", tags=["api-keys-and-webhooks"])


def require_dispatcher_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


# =========================================================================
# API keys
# =========================================================================

@router.post("/api-keys", response_model=ApiKeyCreatedOut)
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    bad_scopes = set(payload.scopes) - API_SCOPES
    if bad_scopes:
        raise HTTPException(status_code=400, detail=f"Unknown scope(s): {sorted(bad_scopes)}. Valid scopes: {sorted(API_SCOPES)}.")
    if not payload.scopes:
        raise HTTPException(status_code=400, detail="At least one scope is required.")

    raw_key, key_prefix, hashed_key = generate_api_key()
    key = ApiKeyDB(
        org_id=current_user.org_id, name=payload.name, key_prefix=key_prefix, hashed_key=hashed_key,
        scopes=",".join(payload.scopes), created_by_user_id=current_user.id,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="api_key", entity_id=key.id, entity_label=key.name,
        summary=f"Created API key '{key.name}' ({key.key_prefix}...).",
    )
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(key).model_dump(), raw_key=raw_key)


@router.get("/api-keys", response_model=List[ApiKeyOut])
def list_api_keys(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    return db.query(ApiKeyDB).filter(ApiKeyDB.org_id == current_user.org_id).order_by(ApiKeyDB.created_at.desc()).all()


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreatedOut)
def rotate_api_key(key_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    """
    Revokes the existing key and issues a brand-new one with the same
    name/scopes — the old raw key stops working the instant this
    returns (revoked_at is set on the SAME row before the new one is
    created), so there's never a window where both the old and new key
    work simultaneously.
    """
    old_key = db.query(ApiKeyDB).filter(ApiKeyDB.id == key_id, ApiKeyDB.org_id == current_user.org_id).first()
    if not old_key:
        raise HTTPException(status_code=404, detail="API key not found.")

    old_key.is_active = False
    old_key.revoked_at = datetime.utcnow()

    raw_key, key_prefix, hashed_key = generate_api_key()
    new_key = ApiKeyDB(
        org_id=current_user.org_id, name=old_key.name, key_prefix=key_prefix, hashed_key=hashed_key,
        scopes=old_key.scopes, created_by_user_id=current_user.id,
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="api_key", entity_id=new_key.id, entity_label=new_key.name,
        summary=f"Rotated API key '{new_key.name}'.",
    )
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(new_key).model_dump(), raw_key=raw_key)


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    key = db.query(ApiKeyDB).filter(ApiKeyDB.id == key_id, ApiKeyDB.org_id == current_user.org_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found.")
    key.is_active = False
    key.revoked_at = datetime.utcnow()
    db.commit()
    return {"message": "API key revoked."}


# =========================================================================
# Webhooks
# =========================================================================

@router.post("/webhooks", response_model=WebhookOut)
def create_webhook(payload: WebhookCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    bad_events = set(payload.subscribed_events) - WEBHOOK_EVENTS
    if bad_events:
        raise HTTPException(status_code=400, detail=f"Unknown event(s): {sorted(bad_events)}. Valid events: {sorted(WEBHOOK_EVENTS)}.")
    if not payload.subscribed_events:
        raise HTTPException(status_code=400, detail="Subscribe to at least one event.")
    if not (payload.url.startswith("http://") or payload.url.startswith("https://")):
        raise HTTPException(status_code=400, detail="url must be a valid http(s) URL.")

    webhook = WebhookDB(
        org_id=current_user.org_id, url=payload.url, secret=generate_webhook_secret(),
        subscribed_events=",".join(payload.subscribed_events), created_by_user_id=current_user.id,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook


@router.get("/webhooks", response_model=List[WebhookOut])
def list_webhooks(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    return db.query(WebhookDB).filter(WebhookDB.org_id == current_user.org_id).order_by(WebhookDB.created_at.desc()).all()


def _get_webhook_or_404(db: Session, webhook_id: str, org_id: str) -> WebhookDB:
    webhook = db.query(WebhookDB).filter(WebhookDB.id == webhook_id, WebhookDB.org_id == org_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return webhook


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
def update_webhook(webhook_id: str, payload: WebhookUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    webhook = _get_webhook_or_404(db, webhook_id, current_user.org_id)
    if payload.subscribed_events is not None:
        bad_events = set(payload.subscribed_events) - WEBHOOK_EVENTS
        if bad_events:
            raise HTTPException(status_code=400, detail=f"Unknown event(s): {sorted(bad_events)}.")
        webhook.subscribed_events = ",".join(payload.subscribed_events)
    if payload.url is not None:
        if not (payload.url.startswith("http://") or payload.url.startswith("https://")):
            raise HTTPException(status_code=400, detail="url must be a valid http(s) URL.")
        webhook.url = payload.url
    if payload.is_active is not None:
        webhook.is_active = payload.is_active
    db.commit()
    db.refresh(webhook)
    return webhook


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    webhook = _get_webhook_or_404(db, webhook_id, current_user.org_id)
    webhook.is_active = False
    db.commit()
    return {"message": "Webhook deactivated."}


@router.get("/webhooks/{webhook_id}/deliveries", response_model=List[WebhookDeliveryOut])
def list_webhook_deliveries(webhook_id: str, status: Optional[str] = None, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    _get_webhook_or_404(db, webhook_id, current_user.org_id)
    q = db.query(WebhookDeliveryDB).filter(WebhookDeliveryDB.webhook_id == webhook_id)
    if status:
        q = q.filter(WebhookDeliveryDB.status == status)
    return q.order_by(WebhookDeliveryDB.created_at.desc()).all()


@router.post("/webhooks/deliveries/{delivery_id}/replay", response_model=WebhookDeliveryOut)
def replay_webhook_delivery(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    delivery = db.query(WebhookDeliveryDB).filter(
        WebhookDeliveryDB.id == delivery_id, WebhookDeliveryDB.org_id == current_user.org_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Webhook delivery not found.")
    replay_delivery(db, delivery)
    db.refresh(delivery)
    return delivery
