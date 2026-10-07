"""
Finance routes (Phase 13). Invoices and refund credit notes are
auto-generated (see services/finance.py's hooks in routes/checkout.py
and services/refund.py) — this router exposes listing/viewing/PDF
download for those, plus manual debit-note creation (dispatcher/admin
only, e.g. for a COD shortfall) and an organization financial report
that reuses Phase 5's existing ledger/settlement data rather than
recomputing a second, possibly-inconsistent set of numbers.
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.models.order import OrderDB
from app.models.financial_document import (
    FinancialDocumentDB, DOCUMENT_TYPES,
    CreditNoteCreate, DebitNoteCreate, FinancialDocumentOut,
)
from app.routes.auth import get_current_user
from app.routes.customer_auth import get_current_customer
from app.services.finance import next_document_number, render_document_pdf
from app.services.reconciliation import compute_financial_dashboard
from app.services.action_log import record_action

customer_router = APIRouter(prefix="/customer/finance", tags=["finance"])
admin_router = APIRouter(prefix="/admin/finance", tags=["finance"])


def require_dispatcher_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in (UserRole.dispatcher, UserRole.admin):
        raise HTTPException(status_code=403, detail="Only dispatchers or admins can do this.")
    return current_user


# =========================================================================
# Customer-facing
# =========================================================================

@customer_router.get("/documents", response_model=List[FinancialDocumentOut])
def list_my_documents(db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    return db.query(FinancialDocumentDB).filter(
        FinancialDocumentDB.customer_id == current_customer.id,
    ).order_by(FinancialDocumentDB.created_at.desc()).all()


@customer_router.get("/documents/{document_id}/pdf")
def download_my_document_pdf(document_id: str, db: Session = Depends(get_db), current_customer: CustomerDB = Depends(get_current_customer)):
    doc = db.query(FinancialDocumentDB).filter(
        FinancialDocumentDB.id == document_id, FinancialDocumentDB.customer_id == current_customer.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    filepath = render_document_pdf(db, doc)
    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))


# =========================================================================
# Staff-facing
# =========================================================================

@admin_router.get("/documents", response_model=List[FinancialDocumentOut])
def list_documents(
    document_type: Optional[str] = None, order_id: Optional[str] = None, customer_id: Optional[str] = None,
    db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin),
):
    if document_type and document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"document_type must be one of {sorted(DOCUMENT_TYPES)}.")
    q = db.query(FinancialDocumentDB).filter(FinancialDocumentDB.org_id == current_user.org_id)
    if document_type:
        q = q.filter(FinancialDocumentDB.document_type == document_type)
    if order_id:
        q = q.filter(FinancialDocumentDB.order_id == order_id)
    if customer_id:
        q = q.filter(FinancialDocumentDB.customer_id == customer_id)
    return q.order_by(FinancialDocumentDB.created_at.desc()).all()


@admin_router.get("/documents/{document_id}/pdf")
def download_document_pdf(document_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    doc = db.query(FinancialDocumentDB).filter(
        FinancialDocumentDB.id == document_id, FinancialDocumentDB.org_id == current_user.org_id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    filepath = render_document_pdf(db, doc)
    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))


@admin_router.post("/credit-notes", response_model=FinancialDocumentOut)
def create_credit_note(payload: CreditNoteCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    """
    Manual credit note — for a goodwill adjustment or partial credit
    NOT already covered by the automatic one generated on a real refund
    (services/refund.py). Amount is never validated against the order
    total: a partial credit note for less than the full order is a
    normal, legitimate use (e.g. one missing item out of an order).
    """
    order = db.query(OrderDB).filter(OrderDB.id == payload.order_id, OrderDB.org_id == current_user.org_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive.")

    doc = FinancialDocumentDB(
        org_id=current_user.org_id, customer_id=order.customer_id, order_id=order.id,
        document_type="credit_note", document_number=next_document_number(db, current_user.org_id, "credit_note"),
        amount=payload.amount, reason=payload.reason, created_by_user_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="credit_note", entity_id=doc.id, entity_label=doc.document_number,
        summary=f"Issued credit note {doc.document_number} for order {order.id}: {payload.reason}",
    )
    return doc


@admin_router.post("/debit-notes", response_model=FinancialDocumentOut)
def create_debit_note(payload: DebitNoteCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    """
    E.g. a COD shortfall the agent under-collected, or an additional
    charge owed. order_id is optional — a debit note doesn't always
    tie back to one specific order.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive.")

    customer_id = None
    if payload.order_id:
        order = db.query(OrderDB).filter(OrderDB.id == payload.order_id, OrderDB.org_id == current_user.org_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found.")
        customer_id = order.customer_id

    doc = FinancialDocumentDB(
        org_id=current_user.org_id, customer_id=customer_id, order_id=payload.order_id,
        document_type="debit_note", document_number=next_document_number(db, current_user.org_id, "debit_note"),
        amount=payload.amount, reason=payload.reason, created_by_user_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="debit_note", entity_id=doc.id, entity_label=doc.document_number,
        summary=f"Issued debit note {doc.document_number}: {payload.reason}",
    )
    return doc


@admin_router.get("/reports")
def financial_report(db: Session = Depends(get_db), current_user: UserDB = Depends(require_dispatcher_or_admin)):
    """
    Reuses Phase 5's compute_financial_dashboard() for the real
    money-movement figures (charges, refunds, COD, settlements) rather
    than recomputing a second, potentially-divergent set of numbers,
    and adds document counts on top — what this phase actually owns.
    """
    dashboard = compute_financial_dashboard(db, current_user.org_id)

    docs = db.query(FinancialDocumentDB).filter(FinancialDocumentDB.org_id == current_user.org_id).all()
    counts_by_type = {t: 0 for t in DOCUMENT_TYPES}
    total_invoiced = 0.0
    total_credited = 0.0
    total_debited = 0.0
    for d in docs:
        counts_by_type[d.document_type] = counts_by_type.get(d.document_type, 0) + 1
        if d.document_type == "invoice":
            total_invoiced += d.amount
        elif d.document_type == "credit_note":
            total_credited += d.amount
        elif d.document_type == "debit_note":
            total_debited += d.amount

    return {
        **dashboard,
        "document_counts": counts_by_type,
        "total_invoiced": round(total_invoiced, 2),
        "total_credited": round(total_credited, 2),
        "total_debited": round(total_debited, 2),
    }
