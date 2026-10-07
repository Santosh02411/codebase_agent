"""
Warehouse management (Phase 3) — added ADDITIVELY alongside the
existing single-number ProductDB.stock_quantity system, not as a
replacement for it.

Why additive rather than a rewrite: routes/checkout.py, services/inventory.py,
and the whole cart/checkout/refund/return flow already depend on
`ProductDB.stock_quantity` as a single authoritative number, and that
flow is covered by a large slice of the existing 168 passing tests.
Rebuilding checkout to decrement a specific warehouse's stock instead
would touch a wide, high-risk surface for a phase whose stated goal is
"without breaking the existing inventory system". So: `stock_quantity`
stays exactly as-is and keeps driving checkout math unchanged. This
module adds a genuinely new capability on top — WHERE stock physically
lives, across one or more warehouses, with real stock-in/out/adjust/
transfer movements, batch/expiry tracking, and purchase orders — that a
dispatcher/admin can use for real warehouse operations. See
services/warehouse.py's `sync_product_stock_from_warehouses()` for the
one explicit, opt-in bridge between the two systems.

Five tables:
  WarehouseDB            — a physical location an org stocks from.
  WarehouseInventoryDB    — one row per (warehouse, product): available/
                            reserved/damaged counts, SKU/barcode/QR,
                            batch + expiry, and a low-stock threshold.
  StockMovementDB         — an immutable log of every stock-in/out/
                            adjustment/transfer — the audit trail.
  SupplierDB              — who a purchase order is placed with.
  PurchaseOrderDB / PurchaseOrderItemDB — ordered vs received quantities,
                            with a goods-received workflow that credits
                            WarehouseInventoryDB via the same stock-in
                            path a manual stock-in uses.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean, Float
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class WarehouseDB(Base):
    __tablename__ = "warehouses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    manager_user_id = Column(String, nullable=True)  # a UserDB.id, must be dispatcher/admin in the same org (checked in routes/warehouse.py)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WarehouseInventoryDB(Base):
    __tablename__ = "warehouse_inventory"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    warehouse_id = Column(String, index=True, nullable=False)
    product_id = Column(String, index=True, nullable=False)

    sku = Column(String, nullable=True)
    barcode = Column(String, nullable=True)  # scanned/encoded the same way order QR codes already are (routes/products.py's existing QR pattern) — no new library needed
    batch_number = Column(String, nullable=True)
    expiry_date = Column(DateTime, nullable=True)

    available_stock = Column(Integer, nullable=False, default=0)
    reserved_stock = Column(Integer, nullable=False, default=0)  # set aside for an in-progress internal process (e.g. an open transfer) — not decremented by storefront checkout, which is untouched by this module
    damaged_stock = Column(Integer, nullable=False, default=0)

    low_stock_threshold = Column(Integer, nullable=False, default=5)

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class StockMovementDB(Base):
    __tablename__ = "stock_movements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    warehouse_id = Column(String, index=True, nullable=False)
    product_id = Column(String, index=True, nullable=False)

    # "stock_in" | "stock_out" | "adjustment" | "transfer_out" | "transfer_in" | "damage" | "goods_received"
    movement_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)  # always positive; movement_type carries the direction

    related_warehouse_id = Column(String, nullable=True)  # the OTHER side of a transfer
    reference = Column(String, nullable=True)  # free-text note, or a PO number for goods_received
    performed_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SupplierDB(Base):
    __tablename__ = "suppliers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PurchaseOrderDB(Base):
    __tablename__ = "purchase_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    supplier_id = Column(String, nullable=False)
    warehouse_id = Column(String, nullable=False)
    # "draft" | "ordered" | "partially_received" | "received" | "cancelled"
    status = Column(String, nullable=False, default="draft")
    created_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expected_date = Column(DateTime, nullable=True)


class PurchaseOrderItemDB(Base):
    __tablename__ = "purchase_order_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    purchase_order_id = Column(String, index=True, nullable=False)
    product_id = Column(String, nullable=False)
    ordered_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Float, nullable=True)


# ---------- Pydantic Schemas ----------

class WarehouseCreate(BaseModel):
    name: str
    address: Optional[str] = None
    manager_user_id: Optional[str] = None


class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    manager_user_id: Optional[str] = None
    active: Optional[bool] = None


class WarehouseOut(BaseModel):
    id: str
    org_id: str
    name: str
    address: Optional[str] = None
    manager_user_id: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WarehouseInventoryOut(BaseModel):
    id: str
    warehouse_id: str
    product_id: str
    sku: Optional[str] = None
    barcode: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None
    available_stock: int
    reserved_stock: int
    damaged_stock: int
    low_stock_threshold: int
    updated_at: datetime

    class Config:
        from_attributes = True


class StockMovementIn(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    sku: Optional[str] = None
    barcode: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None
    reference: Optional[str] = None


class StockAdjustmentIn(BaseModel):
    product_id: str
    new_available_stock: int = Field(ge=0)
    reason: str


class StockTransferIn(BaseModel):
    product_id: str
    to_warehouse_id: str
    quantity: int = Field(gt=0)
    reference: Optional[str] = None


class DamageReportIn(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    reference: Optional[str] = None


class StockMovementOut(BaseModel):
    id: str
    warehouse_id: str
    product_id: str
    movement_type: str
    quantity: int
    related_warehouse_id: Optional[str] = None
    reference: Optional[str] = None
    performed_by_user_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SupplierCreate(BaseModel):
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    active: Optional[bool] = None


class SupplierOut(BaseModel):
    id: str
    org_id: str
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PurchaseOrderItemIn(BaseModel):
    product_id: str
    ordered_quantity: int = Field(gt=0)
    unit_cost: Optional[float] = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    warehouse_id: str
    expected_date: Optional[datetime] = None
    items: list[PurchaseOrderItemIn]


class PurchaseOrderItemOut(BaseModel):
    id: str
    product_id: str
    ordered_quantity: int
    received_quantity: int
    unit_cost: Optional[float] = None

    class Config:
        from_attributes = True


class PurchaseOrderOut(BaseModel):
    id: str
    org_id: str
    supplier_id: str
    warehouse_id: str
    status: str
    created_by_user_id: Optional[str] = None
    created_at: datetime
    expected_date: Optional[datetime] = None
    items: list[PurchaseOrderItemOut] = []

    class Config:
        from_attributes = True


class GoodsReceivedIn(BaseModel):
    received_quantity: int = Field(gt=0)
