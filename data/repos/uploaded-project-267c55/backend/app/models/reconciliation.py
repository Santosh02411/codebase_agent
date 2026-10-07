"""
COD & Payment Reconciliation (Phase 5).

Three tables, all additive alongside the existing OrderDB/refund flow
(services/refund.py, routes/checkout.py) — nothing here changes how a
payment or refund is actually processed; this module adds the
auditable record-keeping ON TOP of those existing flows.

  PaymentLedgerDB   — an APPEND-ONLY log of every financial event this
                      org's orders go through: a charge, a refund, a
                      COD collection, a COD discrepancy, or a COD
                      settlement. "Every financial operation must be
                      auditable" is satisfied by this one rule: every
                      function in services/reconciliation.py that
                      changes money-related state writes exactly one
                      row here, and nothing here is ever updated or
                      deleted — corrections are new rows, not edits.

  CodCollectionDB   — one row per COD order, tracking what was
                      EXPECTED (the order's total) against what an
                      agent actually COLLECTED in cash, with a
                      discrepancy flag when they don't match. Created
                      lazily the first time an agent records a
                      collection for a COD delivery (see
                      services/reconciliation.py) — nothing needs to
                      change in checkout.py's order-creation path.

  AgentSettlementDB — a batch of an agent's collected-but-unsettled
                      CodCollectionDB rows, created by a dispatcher/
                      admin and marked settled once the agent has
                      physically handed over the cash. A settlement is
                      immutable once settled, same "paid statement"
                      pattern services/earnings.py already uses for
                      workforce pay statements.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class PaymentLedgerDB(Base):
    __tablename__ = "payment_ledger"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    order_id = Column(String, index=True, nullable=True)
    delivery_id = Column(String, index=True, nullable=True)

    # "charge" | "refund" | "cod_collected" | "cod_discrepancy" | "cod_settled"
    event_type = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

    # A Razorpay payment/refund ID for charge/refund rows, or a
    # CodCollectionDB/AgentSettlementDB id for the COD event types —
    # whatever ties this ledger row back to the record that caused it.
    reference = Column(String, nullable=True)
    note = Column(String, nullable=True)

    created_by_user_id = Column(String, nullable=True)  # null for system-generated entries (e.g. an automatic charge on payment verification)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CodCollectionDB(Base):
    __tablename__ = "cod_collections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    delivery_id = Column(String, index=True, nullable=False, unique=True)
    order_id = Column(String, nullable=True)
    agent_id = Column(String, index=True, nullable=True)

    expected_amount = Column(Float, nullable=False)
    collected_amount = Column(Float, nullable=True)
    discrepancy_notes = Column(String, nullable=True)

    # "pending" (not yet collected) | "collected" (matches expected) |
    # "discrepancy" (collected but doesn't match expected)
    status = Column(String, nullable=False, default="pending")

    settlement_id = Column(String, nullable=True)  # set once folded into an AgentSettlementDB batch

    collected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentSettlementDB(Base):
    __tablename__ = "agent_settlements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, index=True, nullable=False)

    total_expected = Column(Float, nullable=False, default=0.0)
    total_collected = Column(Float, nullable=False, default=0.0)
    total_discrepancy = Column(Float, nullable=False, default=0.0)  # collected - expected: negative = short, positive = over
    collection_count = Column(Float, nullable=False, default=0)  # Float only for column-type consistency with the totals above; always a whole number

    status = Column(String, nullable=False, default="open")  # "open" | "settled"
    notes = Column(String, nullable=True)
    created_by_user_id = Column(String, nullable=True)
    settled_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)


# ---------- Pydantic Schemas ----------

class CodCollectIn(BaseModel):
    collected_amount: float
    notes: Optional[str] = None


class CodCollectionOut(BaseModel):
    id: str
    delivery_id: str
    order_id: Optional[str] = None
    agent_id: Optional[str] = None
    expected_amount: float
    collected_amount: Optional[float] = None
    discrepancy_notes: Optional[str] = None
    status: str
    settlement_id: Optional[str] = None
    collected_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SettlementCreateIn(BaseModel):
    agent_id: str
    notes: Optional[str] = None


class SettlementOut(BaseModel):
    id: str
    agent_id: str
    total_expected: float
    total_collected: float
    total_discrepancy: float
    collection_count: float
    status: str
    notes: Optional[str] = None
    created_at: datetime
    settled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LedgerEntryOut(BaseModel):
    id: str
    order_id: Optional[str] = None
    delivery_id: Optional[str] = None
    event_type: str
    amount: float
    reference: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
