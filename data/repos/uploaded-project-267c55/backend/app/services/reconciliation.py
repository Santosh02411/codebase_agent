"""
Reconciliation business logic (Phase 5). Every function that changes
money-related state writes exactly one PaymentLedgerDB row — see
models/reconciliation.py's module docstring.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.reconciliation import PaymentLedgerDB, CodCollectionDB, AgentSettlementDB
from app.models.order import OrderDB
from app.models.delivery import DeliveryRecordDB


def log_ledger_entry(db: Session, org_id: str, event_type: str, amount: float,
                      order_id: Optional[str] = None, delivery_id: Optional[str] = None,
                      reference: Optional[str] = None, note: Optional[str] = None,
                      user_id: Optional[str] = None) -> PaymentLedgerDB:
    """The one and only way a PaymentLedgerDB row gets created — called from here, from routes/checkout.py right after a successful charge, and from services/refund.py right after a successful refund."""
    entry = PaymentLedgerDB(
        org_id=org_id, order_id=order_id, delivery_id=delivery_id,
        event_type=event_type, amount=amount, reference=reference, note=note, created_by_user_id=user_id,
    )
    db.add(entry)
    db.commit()
    return entry


class CodError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def get_or_create_cod_collection(db: Session, org_id: str, delivery: DeliveryRecordDB) -> CodCollectionDB:
    """
    Lazily creates the CodCollectionDB row for a COD delivery the first
    time it's needed (either an agent collecting cash, or a dispatcher
    just looking at the reconciliation dashboard) — nothing needs to
    change in routes/checkout.py's order-creation path for this to work.
    Raises CodError if the delivery isn't actually a COD order at all.
    """
    existing = db.query(CodCollectionDB).filter(CodCollectionDB.delivery_id == delivery.id).first()
    if existing:
        return existing

    order = db.query(OrderDB).filter(OrderDB.delivery_id == delivery.id).first()
    if not order or order.payment_method != "cod":
        raise CodError("This delivery isn't a cash-on-delivery order.")

    row = CodCollectionDB(
        org_id=org_id, delivery_id=delivery.id, order_id=order.id, agent_id=delivery.agent_id,
        expected_amount=order.total if order.total else order.subtotal,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_cod_collection(db: Session, org_id: str, delivery: DeliveryRecordDB, collected_amount: float,
                           notes: Optional[str], user_id: str) -> CodCollectionDB:
    """Records what an agent actually collected in cash against the expected amount, flags a discrepancy if they don't match, and logs a ledger entry either way."""
    row = get_or_create_cod_collection(db, org_id, delivery)
    if row.status == "collected" or (row.status == "discrepancy" and row.settlement_id):
        raise CodError("This COD collection has already been recorded.")

    row.collected_amount = collected_amount
    row.discrepancy_notes = notes
    row.collected_at = datetime.utcnow()
    row.agent_id = row.agent_id or delivery.agent_id

    is_match = abs(collected_amount - row.expected_amount) < 0.01
    row.status = "collected" if is_match else "discrepancy"
    db.commit()
    db.refresh(row)

    log_ledger_entry(
        db, org_id, "cod_collected" if is_match else "cod_discrepancy", collected_amount,
        order_id=row.order_id, delivery_id=delivery.id, reference=row.id,
        note=notes or (f"Expected {row.expected_amount}, collected {collected_amount}" if not is_match else None),
        user_id=user_id,
    )
    return row


def create_settlement(db: Session, org_id: str, agent_id: str, notes: Optional[str], user_id: str) -> AgentSettlementDB:
    """Batches every collected-or-discrepancy, not-yet-settled CodCollectionDB row for this agent into a new settlement."""
    unsettled = db.query(CodCollectionDB).filter(
        CodCollectionDB.org_id == org_id,
        CodCollectionDB.agent_id == agent_id,
        CodCollectionDB.status.in_(["collected", "discrepancy"]),
        CodCollectionDB.settlement_id.is_(None),
    ).all()
    if not unsettled:
        raise CodError("This agent has no unsettled COD collections.")

    settlement = AgentSettlementDB(
        org_id=org_id, agent_id=agent_id, notes=notes, created_by_user_id=user_id,
        total_expected=sum(r.expected_amount for r in unsettled),
        total_collected=sum(r.collected_amount or 0 for r in unsettled),
        collection_count=len(unsettled),
    )
    settlement.total_discrepancy = settlement.total_collected - settlement.total_expected
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    for row in unsettled:
        row.settlement_id = settlement.id
    db.commit()
    return settlement


def mark_settlement_settled(db: Session, settlement: AgentSettlementDB, user_id: str) -> AgentSettlementDB:
    if settlement.status == "settled":
        raise CodError("This settlement has already been marked settled.")
    settlement.status = "settled"
    settlement.settled_by_user_id = user_id
    settlement.settled_at = datetime.utcnow()
    db.commit()
    db.refresh(settlement)

    log_ledger_entry(
        db, settlement.org_id, "cod_settled", settlement.total_collected,
        reference=settlement.id, note=f"Settled {settlement.collection_count:.0f} collection(s) for agent {settlement.agent_id}",
        user_id=user_id,
    )
    return settlement


def compute_financial_dashboard(db: Session, org_id: str) -> dict:
    """Live-computed aggregate for the admin financial dashboard — same 'just query it' approach as services/sla.py's analytics."""
    ledger = db.query(PaymentLedgerDB).filter(PaymentLedgerDB.org_id == org_id).all()

    total_charged = sum(e.amount for e in ledger if e.event_type == "charge")
    total_refunded = sum(e.amount for e in ledger if e.event_type == "refund")
    total_cod_collected = sum(e.amount for e in ledger if e.event_type == "cod_collected")
    total_cod_discrepancy_amount = sum(e.amount for e in ledger if e.event_type == "cod_discrepancy")
    discrepancy_count = sum(1 for e in ledger if e.event_type == "cod_discrepancy")

    open_settlements = db.query(AgentSettlementDB).filter(
        AgentSettlementDB.org_id == org_id, AgentSettlementDB.status == "open"
    ).all()
    pending_cod = db.query(CodCollectionDB).filter(
        CodCollectionDB.org_id == org_id, CodCollectionDB.status == "pending"
    ).count()

    return {
        "total_charged": round(total_charged, 2),
        "total_refunded": round(total_refunded, 2),
        "net_revenue": round(total_charged - total_refunded, 2),
        "total_cod_collected": round(total_cod_collected, 2),
        "cod_discrepancy_count": discrepancy_count,
        "cod_discrepancy_amount": round(total_cod_discrepancy_amount, 2),
        "cod_pending_count": pending_cod,
        "open_settlements_count": len(open_settlements),
        "open_settlements_total": round(sum(s.total_collected for s in open_settlements), 2),
    }
