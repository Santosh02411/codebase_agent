"""
CartItemDB: a customer's in-progress shopping cart, persisted server-side
(not just localStorage) so it survives across devices/sessions like a
real e-commerce cart.

Deliberately scoped to ONE store (org_id) at a time per customer — same
behavior as Swiggy/Zomato/Amazon-marketplace carts, where adding an item
from a different seller/restaurant clears the current cart first. This
keeps checkout simple: one cart always produces exactly one order to one
store, which is what becomes one deliverable shipment.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer
from pydantic import BaseModel

from app.db.session import Base


class CartItemDB(Base):
    __tablename__ = "cart_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)
    product_id = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    added_at = Column(DateTime, nullable=False)


class CartItemAdd(BaseModel):
    product_id: str
    quantity: int = 1


class CartItemUpdate(BaseModel):
    quantity: int
