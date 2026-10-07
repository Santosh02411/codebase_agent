"""
Public API v1 (Phase 14) — a minimal external-integration surface,
authenticated by an API key (header `X-API-Key`) rather than the
staff JWT used everywhere else in this project. Versioned under
`/api/v1` so a future incompatible v2 could be added alongside it
without breaking existing integrations — the same reasoning behind
versioning any public API.

This is intentionally a small surface (list/get deliveries and
orders) rather than mirroring the entire internal app: a public API
is a support burden forever once published, so it exposes exactly
the two resources an external integration would plausibly need
first (their own deliveries and orders), each gated by its own scope.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.webhook import ApiKeyDB, hash_api_key
from app.models.delivery import DeliveryRecordDB, DeliveryRecordOut
from app.models.order import OrderDB, OrderOut

router = APIRouter(prefix="/api/v1", tags=["public-api"])


def require_api_key(required_scope: str):
    """
    A dependency FACTORY (not a dependency itself) — called once per
    route with the scope that route needs, returning the actual
    FastAPI dependency. This is what lets one auth mechanism enforce
    different required scopes per endpoint without a separate
    near-identical function for each one.
    """
    def _dependency(db: Session = Depends(get_db), x_api_key: Optional[str] = Header(None)) -> ApiKeyDB:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
        key = db.query(ApiKeyDB).filter(ApiKeyDB.hashed_key == hash_api_key(x_api_key), ApiKeyDB.is_active == True).first()  # noqa: E712
        if not key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
        granted_scopes = set(key.scopes.split(",")) if key.scopes else set()
        if required_scope not in granted_scopes:
            raise HTTPException(status_code=403, detail=f"This API key doesn't have the '{required_scope}' scope.")
        key.last_used_at = datetime.utcnow()
        db.commit()
        return key
    return _dependency


@router.get("/deliveries", response_model=List[DeliveryRecordOut])
def list_deliveries(limit: int = 50, api_key: ApiKeyDB = Depends(require_api_key("deliveries:read")), db: Session = Depends(get_db)):
    limit = min(max(limit, 1), 200)
    return db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == api_key.org_id,
    ).order_by(DeliveryRecordDB.created_at.desc()).limit(limit).all()


@router.get("/deliveries/{delivery_id}", response_model=DeliveryRecordOut)
def get_delivery(delivery_id: str, api_key: ApiKeyDB = Depends(require_api_key("deliveries:read")), db: Session = Depends(get_db)):
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id, DeliveryRecordDB.org_id == api_key.org_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return delivery


@router.get("/orders", response_model=List[OrderOut])
def list_orders(limit: int = 50, api_key: ApiKeyDB = Depends(require_api_key("orders:read")), db: Session = Depends(get_db)):
    limit = min(max(limit, 1), 200)
    return db.query(OrderDB).filter(
        OrderDB.org_id == api_key.org_id,
    ).order_by(OrderDB.created_at.desc()).limit(limit).all()


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str, api_key: ApiKeyDB = Depends(require_api_key("orders:read")), db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id, OrderDB.org_id == api_key.org_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order
