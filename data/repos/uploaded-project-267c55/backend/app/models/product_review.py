"""
ProductReviewDB: a star rating + optional comment for a specific
PRODUCT, submitted by a customer who actually bought it.

Deliberately separate from DeliveryFeedbackDB (models/feedback.py),
which rates the delivery *experience* (was it on time, was the agent
good, etc.) — this rates the *item itself* ("is this product any
good"), the same distinction Amazon/Flipkart draw between "rate your
delivery" and "rate this product". A single order can produce one
delivery-experience rating but several product reviews (one per line
item).

Eligibility is enforced server-side, not just hidden in the UI: a
review must reference a real order that (a) belongs to the reviewing
customer, (b) actually contains that product, and (c) has reached
`delivered` — you can't review something you haven't received yet.
One review per (order_id, product_id) pair, enforced at the database
level via a unique constraint, so re-submitting is an update path, not
a way to stack up multiple reviews for the same purchase.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, UniqueConstraint
from pydantic import BaseModel, Field
from typing import Optional, List

from app.db.session import Base


class ProductReviewDB(Base):
    __tablename__ = "product_reviews"
    __table_args__ = (UniqueConstraint("order_id", "product_id", name="uq_review_per_order_product"),)

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String, index=True, nullable=False)
    order_id = Column(String, index=True, nullable=False)
    customer_id = Column(String, index=True, nullable=False)
    customer_name = Column(String, nullable=False)  # snapshotted for display, same pattern as OrderItemDB's product_name
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProductReviewSubmit(BaseModel):
    order_id: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class ProductReviewOut(BaseModel):
    id: str
    product_id: str
    order_id: str
    customer_name: str
    rating: int
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProductReviewListOut(BaseModel):
    average_rating: Optional[float] = None
    review_count: int
    reviews: List[ProductReviewOut]


class ReviewableItemOut(BaseModel):
    """One product line from a delivered order, for the 'rate your products' UI."""
    order_id: str
    product_id: str
    product_name: str
    quantity: int
    already_reviewed: bool
    my_review: Optional[ProductReviewOut] = None
