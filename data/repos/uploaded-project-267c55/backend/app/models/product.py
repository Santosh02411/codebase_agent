"""
ProductDB: an item a store (organization) sells. Org-scoped — each
organization manages its own catalog, and customers browse one store's
catalog at a time (see routes/stores.py for the public browsing side).
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, Boolean, Integer
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class ProductDB(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)  # in rupees (or your currency's major unit)
    image_url = Column(String, nullable=True)
    category = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)  # inactive products stay in history but stop showing in the storefront
    created_at = Column(DateTime, nullable=False)

    # None = stock isn't tracked for this product (unlimited — the old,
    # only behavior). Once set to a number, it's decremented on paid
    # checkout and restored on cancellation — see services/inventory.py.
    stock_quantity = Column(Integer, nullable=True, default=None)

    # Phase 15: what this product costs the org to acquire/produce —
    # used ONLY by admin-side profit/margin analytics
    # (routes/advanced_analytics.py). Deliberately absent from ProductOut
    # (models/product.py) — that schema is also what the public storefront
    # (routes/stores.py) returns to customers, and margin data must never
    # leak there. None means "not set" — margin analytics simply excludes
    # that product from the profit calculation rather than assuming zero cost.
    cost_price = Column(Float, nullable=True, default=None)


class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    cost_price: Optional[float] = Field(default=None, ge=0)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    cost_price: Optional[float] = Field(default=None, ge=0)


class ProductOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    category: Optional[str] = None
    is_active: bool
    created_at: datetime
    stock_quantity: Optional[int] = None
    # Aggregated from ProductReviewDB at read time — not real columns on
    # the product row itself. See _attach_review_stats() in routes/products.py.
    average_rating: Optional[float] = None
    review_count: int = 0

    class Config:
        from_attributes = True


class ProductImageUploadOut(BaseModel):
    image_url: str
