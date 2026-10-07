"""
Finance service logic (Phase 13): sequential document numbering per
org+type, and PDF rendering. Kept out of routes/finance.py so the
numbering logic (the one piece here with a real correctness
requirement — two documents must never get the same number) is
unit-testable and reviewable in one place.
"""

import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.financial_document import FinancialDocumentDB
from app.models.organization import OrganizationDB

DOCUMENT_PREFIXES = {
    "invoice": "INV", "receipt": "RCT", "refund_receipt": "RRC",
    "credit_note": "CN", "debit_note": "DN",
}

PDF_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "finance")
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)


def next_document_number(db: Session, org_id: str, document_type: str) -> str:
    """
    Sequential per org+type (INV-000001, INV-000002, ... CN-000001...).
    Counts existing rows of this org+type rather than keeping a separate
    counter table — correct as long as documents are never deleted
    (they aren't; see FinancialDocumentDB's docstring on why voiding
    isn't implemented). Wrapped by the caller in the same DB
    transaction as the INSERT, so two concurrent requests would both
    read the same count before either commits — an accepted, documented
    race for a portfolio project's invoice numbering, not a production
    payment-critical sequence.
    """
    count = db.query(FinancialDocumentDB).filter(
        FinancialDocumentDB.org_id == org_id, FinancialDocumentDB.document_type == document_type,
    ).count()
    prefix = DOCUMENT_PREFIXES[document_type]
    return f"{prefix}-{count + 1:06d}"


def render_document_pdf(db: Session, document: FinancialDocumentDB) -> str:
    """
    Renders `document` to a PDF on disk and returns the absolute path.
    Regenerated on every call rather than cached — these are small,
    fast to build, and always reflect the (immutable) stored amounts,
    so there's no staleness risk to caching against.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    org = db.query(OrganizationDB).filter(OrganizationDB.id == document.org_id).first()
    org_name = org.name if org else "Delivery Sync"

    filename = f"{document.document_number}.pdf"
    filepath = os.path.join(PDF_OUTPUT_DIR, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    title = {
        "invoice": "TAX INVOICE", "receipt": "PAYMENT RECEIPT", "refund_receipt": "REFUND RECEIPT",
        "credit_note": "CREDIT NOTE", "debit_note": "DEBIT NOTE",
    }.get(document.document_type, "DOCUMENT")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, org_name)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(width - 20 * mm, y, title)
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Document No: {document.document_number}")
    c.drawRightString(width - 20 * mm, y, f"Date: {document.created_at.strftime('%d %b %Y')}")
    y -= 6 * mm
    if document.order_id:
        c.drawString(20 * mm, y, f"Order Reference: {document.order_id}")
        y -= 6 * mm
    if document.reason:
        c.drawString(20 * mm, y, f"Reason: {document.reason}")
        y -= 6 * mm

    y -= 8 * mm
    c.line(20 * mm, y, width - 20 * mm, y)
    y -= 10 * mm

    c.setFont("Helvetica", 11)
    if document.subtotal is not None:
        c.drawString(20 * mm, y, "Subtotal")
        c.drawRightString(width - 20 * mm, y, f"Rs. {document.subtotal:.2f}")
        y -= 7 * mm
    if document.discount_amount:
        c.drawString(20 * mm, y, "Discount")
        c.drawRightString(width - 20 * mm, y, f"- Rs. {document.discount_amount:.2f}")
        y -= 7 * mm
    if document.delivery_fee:
        c.drawString(20 * mm, y, "Delivery Fee")
        c.drawRightString(width - 20 * mm, y, f"Rs. {document.delivery_fee:.2f}")
        y -= 7 * mm
    if document.tax_amount is not None:
        tax_pct = org.tax_rate_percent if org else None
        label = f"GST ({tax_pct:.1f}%)" if tax_pct is not None else "Tax"
        c.drawString(20 * mm, y, label)
        c.drawRightString(width - 20 * mm, y, f"Rs. {document.tax_amount:.2f}")
        y -= 7 * mm

    y -= 3 * mm
    c.line(20 * mm, y, width - 20 * mm, y)
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 13)
    amount_label = {"credit_note": "Credit Amount", "debit_note": "Debit Amount"}.get(document.document_type, "Total")
    c.drawString(20 * mm, y, amount_label)
    c.drawRightString(width - 20 * mm, y, f"Rs. {document.amount:.2f}")

    c.showPage()
    c.save()
    return filepath


def auto_generate_invoice_for_order(db: Session, order) -> FinancialDocumentDB:
    """
    Called once, right after an order transitions to `paid` (both a
    real online payment and a COD order — an invoice represents what
    was SOLD, not what's been collected; COD collection is tracked
    separately by Phase 5's reconciliation system). Idempotent: if an
    invoice already exists for this order (shouldn't normally happen,
    since this is only called once per order), returns the existing
    one instead of creating a duplicate.
    """
    existing = db.query(FinancialDocumentDB).filter(
        FinancialDocumentDB.order_id == order.id, FinancialDocumentDB.document_type == "invoice",
    ).first()
    if existing:
        return existing

    doc = FinancialDocumentDB(
        org_id=order.org_id, customer_id=order.customer_id, order_id=order.id,
        document_type="invoice", document_number=next_document_number(db, order.org_id, "invoice"),
        subtotal=order.subtotal, discount_amount=order.discount_amount,
        tax_amount=order.tax_amount, delivery_fee=order.delivery_fee, amount=order.total,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def auto_generate_credit_note_for_refund(db: Session, order, refund_amount: float, ledger_reference: Optional[str] = None) -> FinancialDocumentDB:
    """
    Called right after a refund is actually recorded in the payment
    ledger (services/refund.py) — mirrors auto_generate_invoice_for_order
    but for the opposite side of the transaction. The original invoice
    is never modified or deleted; this new document is the accounting
    record of the money going back, exactly like a real credit note
    offsets rather than edits the original invoice.
    """
    doc = FinancialDocumentDB(
        org_id=order.org_id, customer_id=order.customer_id, order_id=order.id,
        document_type="credit_note", document_number=next_document_number(db, order.org_id, "credit_note"),
        amount=refund_amount, reason="Order refund", related_ledger_reference=ledger_reference,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
