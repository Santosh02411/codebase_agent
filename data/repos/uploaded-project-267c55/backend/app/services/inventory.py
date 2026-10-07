"""
Stock/inventory helpers shared by the cart, checkout, and cancellation
flows. A product's `stock_quantity` is None by default — meaning stock
isn't tracked for it at all (unlimited, exactly the old behavior) —
and only becomes a real limit once a dispatcher sets a number for it.

Two moments matter:
  - Decrementing: happens once, at payment verification (an order
    becoming `paid`), not at cart-add or at initial checkout-creation —
    an unpaid/abandoned order should never have permanently reserved
    stock. See routes/checkout.py's verify_payment().
  - Restoring: happens when a PAID order is cancelled — the items never
    shipped, so they go back on the shelf. See both cancellation paths
    (routes/customer_dashboard.py, routes/deliveries.py).
"""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.product import ProductDB
from app.models.order import OrderDB, OrderItemDB


class InsufficientStockError(Exception):
    """Raised with a customer-facing message naming the specific product that's short."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def check_stock_available(db: Session, product_id: str, requested_quantity: int) -> None:
    """
    Raises InsufficientStockError if a product is stock-tracked and
    doesn't have enough on hand for the requested quantity. A no-op for
    untracked products (stock_quantity is None) or ones that don't exist
    (checkout's existing "product no longer available" handling covers
    that case separately).
    """
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product or product.stock_quantity is None:
        return
    if requested_quantity > product.stock_quantity:
        remaining = max(product.stock_quantity, 0)
        raise InsufficientStockError(
            f"Only {remaining} left of \"{product.name}\" — reduce the quantity and try again."
        )


def decrement_stock_for_order(db: Session, order: OrderDB) -> None:
    """
    Called once, when an order's payment is verified as `paid`. Walks
    every line item and decrements stock for any product that tracks
    it. Safe to call even if an item's product has since been deleted —
    that line is just skipped, same as elsewhere in checkout.

    Deliberately does NOT commit — this runs as one step inside
    verify_payment()'s larger atomic sequence (mark paid, decrement
    stock, create delivery), which commits once at the end so a failure
    partway through never leaves stock decremented without an order
    actually being marked paid.
    """
    items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
    for item in items:
        product = db.query(ProductDB).filter(ProductDB.id == item.product_id).first()
        if not product or product.stock_quantity is None:
            continue
        product.stock_quantity = max(product.stock_quantity - item.quantity, 0)


def restock_order_if_needed(db: Session, order: OrderDB) -> None:
    """
    Called when a paid order is cancelled. Idempotent via
    `order.stock_restored` — safe to call from both cancellation paths
    (customer self-serve + dispatcher/admin) without double-crediting
    stock if something ever calls this twice for the same order.
    """
    if order.stock_restored:
        return
    items = db.query(OrderItemDB).filter(OrderItemDB.order_id == order.id).all()
    for item in items:
        product = db.query(ProductDB).filter(ProductDB.id == item.product_id).first()
        if not product or product.stock_quantity is None:
            continue
        product.stock_quantity = product.stock_quantity + item.quantity
    order.stock_restored = 1
    db.commit()
