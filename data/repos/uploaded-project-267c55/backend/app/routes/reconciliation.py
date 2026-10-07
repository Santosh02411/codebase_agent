"""
Reconciliation routes (Phase 5), gated on the payments.* permissions
from Phase 4's granular RBAC — a second real demonstration of that
system beyond warehouse routes, and arguably a MORE natural fit:
payments.refund existed in the Phase 4 permission catalog specifically
because financial actions are exactly the kind of thing an org might
want to grant to a trusted dispatcher without making them a full admin,
or withhold from a dispatcher who shouldn't touch money at all.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.user import UserDB, UserRole
from app.models.reconciliation import (
    CodCollectionDB, AgentSettlementDB, PaymentLedgerDB,
    CodCollectIn, CodCollectionOut, SettlementCreateIn, SettlementOut, LedgerEntryOut,
)
from app.routes.auth import get_current_user
from app.services.permissions import require_permission
from app.services import reconciliation as recon_service

router = APIRouter(tags=["reconciliation"])


def _get_delivery_or_404(db: Session, delivery_id: str, org_id: str) -> DeliveryRecordDB:
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id, DeliveryRecordDB.org_id == org_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return delivery


# ---------- COD collection (agent-facing, own delivery only) ----------

@router.post("/deliveries/{delivery_id}/cod/collect", response_model=CodCollectionOut)
def collect_cod(
    delivery_id: str,
    payload: CodCollectIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only record COD collection for your own assigned deliveries.")

    try:
        return recon_service.record_cod_collection(db, current_user.org_id, delivery, payload.collected_amount, payload.notes, current_user.id)
    except recon_service.CodError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/deliveries/{delivery_id}/cod", response_model=CodCollectionOut)
def get_cod_collection(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view COD collection for your own assigned deliveries.")
    try:
        return recon_service.get_or_create_cod_collection(db, current_user.org_id, delivery)
    except recon_service.CodError as e:
        raise HTTPException(status_code=400, detail=e.message)


# ---------- Admin/dispatcher reconciliation views ----------

@router.get("/admin/reconciliation/cod", response_model=List[CodCollectionOut])
def list_cod_collections(
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.view")),
):
    query = db.query(CodCollectionDB).filter(CodCollectionDB.org_id == current_user.org_id)
    if status:
        query = query.filter(CodCollectionDB.status == status)
    if agent_id:
        query = query.filter(CodCollectionDB.agent_id == agent_id)
    return query.order_by(CodCollectionDB.created_at.desc()).all()


@router.post("/admin/reconciliation/settlements", response_model=SettlementOut)
def create_settlement(
    payload: SettlementCreateIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.manage")),
):
    try:
        return recon_service.create_settlement(db, current_user.org_id, payload.agent_id, payload.notes, current_user.id)
    except recon_service.CodError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/admin/reconciliation/settlements", response_model=List[SettlementOut])
def list_settlements(
    agent_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.view")),
):
    query = db.query(AgentSettlementDB).filter(AgentSettlementDB.org_id == current_user.org_id)
    if agent_id:
        query = query.filter(AgentSettlementDB.agent_id == agent_id)
    return query.order_by(AgentSettlementDB.created_at.desc()).all()


@router.patch("/admin/reconciliation/settlements/{settlement_id}/settle", response_model=SettlementOut)
def settle_settlement(
    settlement_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.manage")),
):
    settlement = db.query(AgentSettlementDB).filter(
        AgentSettlementDB.id == settlement_id, AgentSettlementDB.org_id == current_user.org_id
    ).first()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found.")
    try:
        return recon_service.mark_settlement_settled(db, settlement, current_user.id)
    except recon_service.CodError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/admin/reconciliation/ledger", response_model=List[LedgerEntryOut])
def get_ledger(
    order_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.view")),
):
    query = db.query(PaymentLedgerDB).filter(PaymentLedgerDB.org_id == current_user.org_id)
    if order_id:
        query = query.filter(PaymentLedgerDB.order_id == order_id)
    if event_type:
        query = query.filter(PaymentLedgerDB.event_type == event_type)
    if date_from:
        query = query.filter(PaymentLedgerDB.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(PaymentLedgerDB.created_at <= datetime.combine(date_to, datetime.max.time()))
    return query.order_by(PaymentLedgerDB.created_at.desc()).all()


@router.get("/admin/reconciliation/payment-status/{order_id}", response_model=List[LedgerEntryOut])
def payment_status_history(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("payments.view")),
):
    """Every ledger event tied to one order, oldest first — the 'payment status history' requirement, and the same data a Razorpay/refund reconciliation view would read."""
    return db.query(PaymentLedgerDB).filter(
        PaymentLedgerDB.org_id == current_user.org_id, PaymentLedgerDB.order_id == order_id
    ).order_by(PaymentLedgerDB.created_at.asc()).all()


@router.get("/admin/reconciliation/dashboard")
def financial_dashboard(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("payments.view"))):
    return recon_service.compute_financial_dashboard(db, current_user.org_id)
