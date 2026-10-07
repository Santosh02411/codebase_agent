"""
Product reviews & ratings — rating the ITEM you bought, not the
delivery experience (that's models/feedback.py + routes under
/track and /customer/deliveries/{id}/feedback).

Two audiences:
  - Public (no login): browse a product's reviews/average rating,
    same as browsing reviews on any storefront before buying.
  - Logged-in customer: submit a review for something they actually
    bought and received, and see which of their delivered order's
    products still need a review.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.product import ProductDB
from app.models.product_review import (
    ProductReviewDB,
    ProductReviewSubmit,
    ProductReviewOut,
    ProductReviewListOut,
    ReviewableItemOut,
)
from app.models.order import OrderDB, OrderItemDB, OrderStatus
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.customer import CustomerDB
from app.routes.customer_auth import get_current_customer
from app.services.rate_limiter import limiter

router = APIRouter(tags=["reviews"])


def _order_delivered(db: Session, order: OrderDB) -> bool:
    if not order.delivery_id:
        return False
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == order.delivery_id).first()
    return bool(delivery and delivery.status == DeliveryStatus.delivered)


@router.get("/stores/products/{product_id}/reviews", response_model=ProductReviewListOut)
@limiter.limit("60/minute")
def list_product_reviews(request: Request, product_id: str, db: Session = Depends(get_db)):
    """Public — anyone browsing the storefront can see a product's reviews before buying."""
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    reviews = (
        db.query(ProductReviewDB)
        .filter(ProductReviewDB.product_id == product_id)
        .order_by(ProductReviewDB.created_at.desc())
        .all()
    )
    count = len(reviews)
    average = round(sum(r.rating for r in reviews) / count, 1) if count else None
    return ProductReviewListOut(average_rating=average, review_count=count, reviews=reviews)


@router.get("/customer/deliveries/{delivery_id}/reviewable-items", response_model=List[ReviewableItemOut])
def list_reviewable_items(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    For a delivered order linked to this delivery: every product line,
    whether it's already been reviewed, and the existing review if so —
    what the 'Rate your products' section on a delivered order renders.
    Empty list for anything that isn't a paid, delivered, customer-placed
    order (e.g. a dispatcher-created manual delivery with no linked Order).
    """
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.customer_id == current_customer.id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    order = db.query(OrderDB).filter(
        OrderDB.delivery_id == delivery_id,
        OrderDB.customer_id == current_customer.id,
    ).first()
    if not order or order.status != OrderStatus.paid or delivery.status != DeliveryStatus.delivered:
        return []

    items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
    existing_reviews = {
        r.product_id: r
        for r in db.query(ProductReviewDB).filter(
            ProductReviewDB.order_id == order.id,
            ProductReviewDB.customer_id == current_customer.id,
        ).all()
    }

    results = []
    for item in items:
        review = existing_reviews.get(item.product_id)
        results.append(ReviewableItemOut(
            order_id=order.id,
            product_id=item.product_id,
            product_name=item.product_name,
            quantity=item.quantity,
            already_reviewed=review is not None,
            my_review=review,
        ))
    return results


@router.post("/customer/products/{product_id}/reviews", response_model=ProductReviewOut)
def submit_product_review(
    product_id: str,
    payload: ProductReviewSubmit,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    """
    Rate a product you actually bought and received. Rejected unless:
    the order is yours, it's paid, it actually contains this product,
    its delivery has reached 'delivered', and you haven't already
    reviewed this product for this specific order.
    """
    order = db.query(OrderDB).filter(
        OrderDB.id == payload.order_id,
        OrderDB.customer_id == current_customer.id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != OrderStatus.paid:
        raise HTTPException(status_code=400, detail="This order hasn't been paid for.")

    item = db.query(OrderItemDB).filter(
        OrderItemDB.order_id == order.id,
        OrderItemDB.product_id == product_id,
    ).first()
    if not item:
        raise HTTPException(status_code=400, detail="This product wasn't part of that order.")

    if not _order_delivered(db, order):
        raise HTTPException(status_code=400, detail="You can only review a product after it's been delivered.")

    existing = db.query(ProductReviewDB).filter(
        ProductReviewDB.order_id == order.id,
        ProductReviewDB.product_id == product_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You've already reviewed this product for this order.")

    review = ProductReviewDB(
        id=str(uuid.uuid4()),
        product_id=product_id,
        order_id=order.id,
        customer_id=current_customer.id,
        customer_name=current_customer.name,
        rating=payload.rating,
        comment=payload.comment,
        created_at=datetime.utcnow(),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
