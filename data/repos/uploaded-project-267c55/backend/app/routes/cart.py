"""
Customer shopping cart — persisted server-side per customer (see
cart.py's module docstring for why). A customer's cart is scoped to ONE
store at a time; adding a product from a different store clears
whatever was in the cart first, same behavior as Swiggy/Zomato/Amazon-
marketplace carts.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.db.session import get_db
from app.models.cart import CartItemDB, CartItemAdd, CartItemUpdate
from app.models.product import ProductDB, ProductOut
from app.models.customer import CustomerDB
from app.routes.customer_auth import get_current_customer
from app.services.inventory import check_stock_available, InsufficientStockError

router = APIRouter(prefix="/customer/cart", tags=["cart"])


class CartLineOut(BaseModel):
    id: str
    product: ProductOut
    quantity: int
    line_total: float


class CartOut(BaseModel):
    org_id: str | None = None
    items: List[CartLineOut]
    subtotal: float


def _build_cart_response(db: Session, customer_id: str) -> CartOut:
    rows = db.query(CartItemDB).filter(CartItemDB.customer_id == customer_id).all()
    lines = []
    subtotal = 0.0
    org_id = None
    for row in rows:
        product = db.query(ProductDB).filter(ProductDB.id == row.product_id).first()
        if not product:
            continue  # product was deleted since being added — just skip it, don't error the whole cart
        org_id = row.org_id
        line_total = product.price * row.quantity
        subtotal += line_total
        lines.append(CartLineOut(id=row.id, product=product, quantity=row.quantity, line_total=line_total))
    return CartOut(org_id=org_id, items=lines, subtotal=round(subtotal, 2))


@router.get("/", response_model=CartOut)
def get_my_cart(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    return _build_cart_response(db, current_customer.id)


@router.post("/", response_model=CartOut)
def add_to_cart(
    payload: CartItemAdd,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    product = db.query(ProductDB).filter(ProductDB.id == payload.product_id, ProductDB.is_active == True).first()  # noqa: E712
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    existing_items = db.query(CartItemDB).filter(CartItemDB.customer_id == current_customer.id).all()
    if existing_items and existing_items[0].org_id != product.org_id:
        # Switching stores — clear the old cart first, same as any real food/delivery app does.
        for item in existing_items:
            db.delete(item)
        db.commit()
        existing_items = []

    existing_line = next((i for i in existing_items if i.product_id == payload.product_id), None)
    new_quantity = (existing_line.quantity if existing_line else 0) + payload.quantity
    try:
        check_stock_available(db, product.id, new_quantity)
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=e.message)

    if existing_line:
        existing_line.quantity = new_quantity
    else:
        db.add(CartItemDB(
            id=str(uuid.uuid4()),
            customer_id=current_customer.id,
            org_id=product.org_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            added_at=datetime.utcnow(),
        ))
    db.commit()
    return _build_cart_response(db, current_customer.id)


@router.patch("/{item_id}", response_model=CartOut)
def update_cart_item(
    item_id: str,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    item = db.query(CartItemDB).filter(
        CartItemDB.id == item_id,
        CartItemDB.customer_id == current_customer.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found.")

    if payload.quantity <= 0:
        db.delete(item)
    else:
        try:
            check_stock_available(db, item.product_id, payload.quantity)
        except InsufficientStockError as e:
            raise HTTPException(status_code=400, detail=e.message)
        item.quantity = payload.quantity
    db.commit()
    return _build_cart_response(db, current_customer.id)


@router.delete("/{item_id}", response_model=CartOut)
def remove_cart_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    item = db.query(CartItemDB).filter(
        CartItemDB.id == item_id,
        CartItemDB.customer_id == current_customer.id,
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return _build_cart_response(db, current_customer.id)


@router.delete("/", response_model=CartOut)
def clear_cart(
    db: Session = Depends(get_db),
    current_customer: CustomerDB = Depends(get_current_customer),
):
    db.query(CartItemDB).filter(CartItemDB.customer_id == current_customer.id).delete()
    db.commit()
    return _build_cart_response(db, current_customer.id)
