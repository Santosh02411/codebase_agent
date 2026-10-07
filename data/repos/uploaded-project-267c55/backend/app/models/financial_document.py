"""
Invoicing & Finance (Phase 13) — one table, `FinancialDocumentDB`,
covers invoices, payment receipts, refund receipts, credit notes, and
debit notes via a `document_type` field, rather than four/five
near-identical tables (an invoice, a receipt, and a credit note all
share the same shape: a snapshot of amounts, tied to an order, with a
sequential per-org-per-type number). This follows the same
"reuse, don't duplicate the concept" instruction the rest of this
project's schema follows.

Amounts are NEVER recomputed here — every document snapshots the
figures already computed once, authoritatively, at checkout time on
OrderDB (subtotal, discount_amount, tax_amount, delivery_fee, total)
or from the real PaymentLedgerDB event that caused it (a refund
amount). This guarantees an invoice or credit note always matches
what the customer actually paid/was refunded, even if the org's tax
rate or delivery fee configuration changes later.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base

DOCUMENT_TYPES = {"invoice", "receipt", "refund_receipt", "credit_note", "debit_note"}


class FinancialDocumentDB(Base):
    __tablename__ = "financial_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    customer_id = Column(String, index=True, nullable=True)
    order_id = Column(String, index=True, nullable=True)

    document_type = Column(String, nullable=False)  # one of DOCUMENT_TYPES
    # Sequential per org+type, e.g. "INV-000001", "CN-000001" — assigned
    # once at creation and never reused, even if the document is later
    # voided (voiding isn't implemented; these are point-in-time records
    # of money that actually moved, matching how a real invoice/credit
    # note register works).
    document_number = Column(String, index=True, nullable=False)

    subtotal = Column(Float, nullable=True)
    discount_amount = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    delivery_fee = Column(Float, nullable=True)
    amount = Column(Float, nullable=False)  # the document's headline amount — total for an invoice/receipt, refund/adjustment amount for a credit/debit note

    reason = Column(String, nullable=True)  # required for credit/debit notes — why this adjustment exists
    related_ledger_reference = Column(String, nullable=True)  # ties back to the PaymentLedgerDB row (Phase 5) that caused this, if any

    created_by_user_id = Column(String, nullable=True)  # null when system-generated (e.g. an invoice auto-created on payment verification)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class CreditNoteCreate(BaseModel):
    order_id: str
    amount: float
    reason: str


class DebitNoteCreate(BaseModel):
    order_id: Optional[str] = None
    amount: float
    reason: str


class FinancialDocumentOut(BaseModel):
    id: str
    org_id: str
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    document_type: str
    document_number: str
    subtotal: Optional[float] = None
    discount_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    delivery_fee: Optional[float] = None
    amount: float
    reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
