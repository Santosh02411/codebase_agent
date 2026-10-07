"""
Customer data privacy: GDPR-style "right to access" (data export) and
"right to erasure" (account deletion), for the customer-facing account
system (CustomerDB — see models/customer.py's docstring on why customers
are a separate identity system from staff).

Deliberately separate from routes/export.py, which is a completely
different feature — a dispatcher/admin's CSV export of their
organization's delivery operations data. This file is about a customer
exporting or deleting THEIR OWN personal data.

Design decision on deletion, worth stating plainly (and shown in the
API's response message, not just here): deleting a customer's account
does NOT delete their past orders/deliveries outright. Organizations
using this platform have a legitimate business need to retain
transaction records (for accounting, dispute handling, and refund
history) even after a customer walks away — this mirrors how real
e-commerce platforms (Amazon, Shopify) handle "delete my account":
personally-identifying fields are scrubbed/anonymized, but the
underlying order ledger survives under an anonymized reference. Data
that's purely personal and has no such retention justification (cart,
saved addresses, in-app notifications, push subscriptions) is deleted
outright, not just anonymized.
"""

import json
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.models.customer import CustomerDB
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_history import DeliveryHistoryDB
from app.models.order import OrderDB, OrderItemDB
from app.models.cart import CartItemDB
from app.models.customer_address import CustomerAddressDB
from app.models.customer_notification import CustomerNotificationDB
from app.models.feedback import DeliveryFeedbackDB
from app.models.product_review import ProductReviewDB
from app.models.push_subscription import PushSubscriptionDB
from app.services.auth import verify_password
from app.routes.customer_auth import get_current_customer

router = APIRouter(prefix="/customer", tags=["customer-privacy"])


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {value!r}")


@router.get("/data-export")
def export_my_data(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Streams a single JSON file containing every piece of personal data
    this platform holds about the logged-in customer: profile, saved
    addresses, orders (with line items), linked deliveries and their
    status history, cart contents, in-app notifications, product
    reviews, and delivery feedback they've submitted. Push subscription
    endpoints are listed too (so the customer can see which
    devices/browsers are registered) but their private keys are
    withheld, since those are security credentials rather than personal
    data, and including them in a downloadable file would be a needless
    way to leak them.
    """
    customer_id = current_customer.id

    orders = db.query(OrderDB).filter(OrderDB.customer_id == customer_id).all()
    order_ids = [o.id for o in orders]
    items_by_order = {}
    if order_ids:
        for item in db.query(OrderItemDB).filter(OrderItemDB.order_id.in_(order_ids)).all():
            items_by_order.setdefault(item.order_id, []).append({
                "product_id": item.product_id,
                "product_name": item.product_name,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
            })

    deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.customer_id == customer_id).all()
    delivery_ids = [d.id for d in deliveries]
    history_by_delivery = {}
    feedback_by_delivery = {}
    if delivery_ids:
        for h in db.query(DeliveryHistoryDB).filter(DeliveryHistoryDB.delivery_id.in_(delivery_ids)).all():
            history_by_delivery.setdefault(h.delivery_id, []).append({
                "old_status": h.old_status,
                "new_status": h.new_status,
                "changed_at": h.changed_at,
                "note": h.note,
            })
        for f in db.query(DeliveryFeedbackDB).filter(DeliveryFeedbackDB.delivery_id.in_(delivery_ids)).all():
            feedback_by_delivery[f.delivery_id] = {
                "rating": f.rating,
                "comment": f.comment,
                "created_at": f.created_at,
            }

    addresses = db.query(CustomerAddressDB).filter(CustomerAddressDB.customer_id == customer_id).all()
    cart_items = db.query(CartItemDB).filter(CartItemDB.customer_id == customer_id).all()
    notifications = db.query(CustomerNotificationDB).filter(CustomerNotificationDB.customer_id == customer_id).all()
    reviews = db.query(ProductReviewDB).filter(ProductReviewDB.customer_id == customer_id).all()
    push_subs = db.query(PushSubscriptionDB).filter(PushSubscriptionDB.customer_id == customer_id).all()

    export = {
        "exported_at": datetime.utcnow(),
        "profile": {
            "id": current_customer.id,
            "email": current_customer.email,
            "name": current_customer.name,
            "created_at": current_customer.created_at,
        },
        "saved_addresses": [
            {
                "label": a.label,
                "address_line": a.address_line,
                "city": a.city,
                "phone": a.phone,
                "is_default": a.is_default,
                "created_at": a.created_at,
            }
            for a in addresses
        ],
        "orders": [
            {
                "id": o.id,
                "status": o.status.value,
                "address_line": o.address_line,
                "city": o.city,
                "phone": o.phone,
                "subtotal": o.subtotal,
                "coupon_code": o.coupon_code,
                "discount_amount": o.discount_amount,
                "delivery_fee": o.delivery_fee,
                "tax_amount": o.tax_amount,
                "total": o.total,
                "created_at": o.created_at,
                "items": items_by_order.get(o.id, []),
            }
            for o in orders
        ],
        "deliveries": [
            {
                "id": d.id,
                "order_id": d.order_id,
                "status": d.status.value,
                "customer_email": d.customer_email,
                "customer_phone": d.customer_phone,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
                "status_history": history_by_delivery.get(d.id, []),
                "feedback_given": feedback_by_delivery.get(d.id),
            }
            for d in deliveries
        ],
        "cart_items": [
            {"product_id": c.product_id, "quantity": c.quantity, "added_at": c.added_at}
            for c in cart_items
        ],
        "notifications": [
            {"message": n.message, "is_read": n.is_read, "created_at": n.created_at}
            for n in notifications
        ],
        "product_reviews_submitted": [
            {"product_id": r.product_id, "order_id": r.order_id, "rating": r.rating, "comment": r.comment, "created_at": r.created_at}
            for r in reviews
        ],
        "push_notification_devices": [
            {"endpoint": p.endpoint, "registered_at": p.created_at}
            for p in push_subs
        ],
    }

    body = json.dumps(export, indent=2, default=_json_default)
    filename = f"my_data_export_{date.today().isoformat()}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class DeleteAccountRequest(BaseModel):
    password: str


@router.delete("/account")
def delete_my_account(
    payload: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Deletes the customer's account. Requires re-entering the password
    (an active session token alone isn't enough) so someone who grabs an
    unlocked, already-logged-in device can't silently erase the account
    for them. See this file's module docstring for what "deletion" means
    here — purely personal data is deleted outright; order/delivery/
    review records are anonymized and retained for the store's own
    transaction records, not deleted.
    """
    if not verify_password(payload.password, current_customer.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    customer_id = current_customer.id
    anonymized_email = f"deleted-user-{customer_id[:8]}@deleted.local"

    # Purely personal data, no business/legal reason to retain it — delete outright.
    db.query(CartItemDB).filter(CartItemDB.customer_id == customer_id).delete()
    db.query(CustomerAddressDB).filter(CustomerAddressDB.customer_id == customer_id).delete()
    db.query(CustomerNotificationDB).filter(CustomerNotificationDB.customer_id == customer_id).delete()
    db.query(PushSubscriptionDB).filter(PushSubscriptionDB.customer_id == customer_id).delete()

    # Transaction/financial records: anonymize contact details rather
    # than delete the record itself (see module docstring).
    db.query(DeliveryRecordDB).filter(DeliveryRecordDB.customer_id == customer_id).update(
        {"customer_email": anonymized_email, "customer_phone": None}
    )
    db.query(OrderDB).filter(OrderDB.customer_id == customer_id).update(
        {"address_line": "[deleted]", "city": None, "phone": "[deleted]"}
    )
    db.query(ProductReviewDB).filter(ProductReviewDB.customer_id == customer_id).update(
        {"customer_name": "Deleted User"}
    )

    db.delete(current_customer)
    db.commit()

    return {
        "success": True,
        "message": (
            "Your account and personal data have been deleted. Your past "
            "orders are retained by the relevant store(s) in anonymized "
            "form, as needed for their own transaction and refund records."
        ),
    }
