"""
Warehouse business logic (Phase 3): every stock mutation goes through
one of the functions here, and every one of them writes a
StockMovementDB row — there is no code path that changes
WarehouseInventoryDB numbers without leaving an audit trail entry,
mirroring how services/inventory.py already treats ProductDB.stock_quantity
changes as something that must always be traceable to an order.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.warehouse import WarehouseInventoryDB, StockMovementDB
from app.models.product import ProductDB


class InsufficientWarehouseStockError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _get_or_create_inventory_row(db: Session, org_id: str, warehouse_id: str, product_id: str) -> WarehouseInventoryDB:
    row = db.query(WarehouseInventoryDB).filter(
        WarehouseInventoryDB.warehouse_id == warehouse_id,
        WarehouseInventoryDB.product_id == product_id,
    ).first()
    if not row:
        row = WarehouseInventoryDB(org_id=org_id, warehouse_id=warehouse_id, product_id=product_id, available_stock=0)
        db.add(row)
    return row


def _log_movement(db: Session, org_id: str, warehouse_id: str, product_id: str, movement_type: str,
                   quantity: int, user_id: Optional[str], reference: Optional[str] = None,
                   related_warehouse_id: Optional[str] = None) -> StockMovementDB:
    movement = StockMovementDB(
        org_id=org_id, warehouse_id=warehouse_id, product_id=product_id,
        movement_type=movement_type, quantity=quantity, related_warehouse_id=related_warehouse_id,
        reference=reference, performed_by_user_id=user_id,
    )
    db.add(movement)
    return movement


def stock_in(db: Session, org_id: str, warehouse_id: str, payload, user_id: str) -> WarehouseInventoryDB:
    """Receiving new stock into a warehouse — from a manual entry or a purchase order (see receive_purchase_order_item below, which calls this)."""
    row = _get_or_create_inventory_row(db, org_id, warehouse_id, payload.product_id)
    if payload.sku:
        row.sku = payload.sku
    if payload.barcode:
        row.barcode = payload.barcode
    if payload.batch_number:
        row.batch_number = payload.batch_number
    if payload.expiry_date:
        row.expiry_date = payload.expiry_date
    row.available_stock += payload.quantity
    row.updated_at = datetime.utcnow()
    _log_movement(db, org_id, warehouse_id, payload.product_id, "stock_in", payload.quantity, user_id, payload.reference)
    db.commit()
    db.refresh(row)
    return row


def stock_out(db: Session, org_id: str, warehouse_id: str, payload, user_id: str) -> WarehouseInventoryDB:
    """Stock leaving a warehouse for a reason OTHER than the storefront checkout flow (e.g. manual pull, write-off, internal use) — checkout's own decrement_stock_for_order() in services/inventory.py is unrelated and untouched."""
    row = _get_or_create_inventory_row(db, org_id, warehouse_id, payload.product_id)
    if payload.quantity > row.available_stock:
        raise InsufficientWarehouseStockError(
            f"Only {row.available_stock} available in this warehouse — can't remove {payload.quantity}."
        )
    row.available_stock -= payload.quantity
    row.updated_at = datetime.utcnow()
    _log_movement(db, org_id, warehouse_id, payload.product_id, "stock_out", payload.quantity, user_id, payload.reference)
    db.commit()
    db.refresh(row)
    return row


def adjust_stock(db: Session, org_id: str, warehouse_id: str, payload, user_id: str) -> WarehouseInventoryDB:
    """Sets available_stock to an exact number (e.g. after a physical count) — logs the delta, not the new total, so the movement log stays additive/consistent with every other entry type."""
    row = _get_or_create_inventory_row(db, org_id, warehouse_id, payload.product_id)
    delta = payload.new_available_stock - row.available_stock
    row.available_stock = payload.new_available_stock
    row.updated_at = datetime.utcnow()
    if delta != 0:
        _log_movement(
            db, org_id, warehouse_id, payload.product_id, "adjustment", abs(delta), user_id,
            f"{payload.reason} ({'+' if delta > 0 else ''}{delta})",
        )
    db.commit()
    db.refresh(row)
    return row


def transfer_stock(db: Session, org_id: str, from_warehouse_id: str, payload, user_id: str) -> tuple[WarehouseInventoryDB, WarehouseInventoryDB]:
    """Moves stock from one warehouse to another within the same org — two linked movement rows (transfer_out / transfer_in), both referencing each other's warehouse via related_warehouse_id."""
    source = _get_or_create_inventory_row(db, org_id, from_warehouse_id, payload.product_id)
    if payload.quantity > source.available_stock:
        raise InsufficientWarehouseStockError(
            f"Only {source.available_stock} available to transfer — can't move {payload.quantity}."
        )
    dest = _get_or_create_inventory_row(db, org_id, payload.to_warehouse_id, payload.product_id)

    source.available_stock -= payload.quantity
    source.updated_at = datetime.utcnow()
    dest.available_stock += payload.quantity
    dest.updated_at = datetime.utcnow()

    _log_movement(db, org_id, from_warehouse_id, payload.product_id, "transfer_out", payload.quantity, user_id, payload.reference, related_warehouse_id=payload.to_warehouse_id)
    _log_movement(db, org_id, payload.to_warehouse_id, payload.product_id, "transfer_in", payload.quantity, user_id, payload.reference, related_warehouse_id=from_warehouse_id)

    db.commit()
    db.refresh(source)
    db.refresh(dest)
    return source, dest


def report_damage(db: Session, org_id: str, warehouse_id: str, payload, user_id: str) -> WarehouseInventoryDB:
    """Moves units from available to damaged — doesn't leave the warehouse's total, just no longer sellable."""
    row = _get_or_create_inventory_row(db, org_id, warehouse_id, payload.product_id)
    if payload.quantity > row.available_stock:
        raise InsufficientWarehouseStockError(
            f"Only {row.available_stock} available — can't mark {payload.quantity} as damaged."
        )
    row.available_stock -= payload.quantity
    row.damaged_stock += payload.quantity
    row.updated_at = datetime.utcnow()
    _log_movement(db, org_id, warehouse_id, payload.product_id, "damage", payload.quantity, user_id, payload.reference)
    db.commit()
    db.refresh(row)
    return row


def receive_purchase_order_item(db: Session, org_id: str, po, po_item, received_quantity: int, user_id: str) -> WarehouseInventoryDB:
    """
    Goods-received workflow: credits the PO's warehouse via the same
    stock_in path a manual receipt uses (so it shows up identically in
    the movement log and inventory), and updates the item's
    received_quantity + the PO's overall status.
    """
    class _StockInPayload:
        product_id = po_item.product_id
        quantity = received_quantity
        sku = None
        barcode = None
        batch_number = None
        expiry_date = None
        reference = f"PO {po.id}"

    row = stock_in(db, org_id, po.warehouse_id, _StockInPayload(), user_id)

    po_item.received_quantity += received_quantity
    db.commit()

    from app.models.warehouse import PurchaseOrderItemDB
    items = db.query(PurchaseOrderItemDB).filter(PurchaseOrderItemDB.purchase_order_id == po.id).all()
    if all(i.received_quantity >= i.ordered_quantity for i in items):
        po.status = "received"
    elif any(i.received_quantity > 0 for i in items):
        po.status = "partially_received"
    db.commit()
    return row


def sync_product_stock_from_warehouses(db: Session, org_id: str, product_id: str) -> Optional[int]:
    """
    OPT-IN bridge back to the existing checkout system: sums a
    product's available_stock across every warehouse in the org and
    writes that total onto ProductDB.stock_quantity, so checkout's
    existing services/inventory.py logic (completely unmodified) starts
    reflecting real warehouse totals instead of whatever number a
    dispatcher last typed into the product form directly. NOT called
    automatically by any stock movement above — a dispatcher/admin
    calls this explicitly (see routes/warehouse.py's
    POST /warehouses/products/{id}/sync-stock) when they're ready to
    let warehouse totals start driving the storefront. Returns the new
    total, or None if the product doesn't exist.
    """
    product = db.query(ProductDB).filter(ProductDB.id == product_id, ProductDB.org_id == org_id).first()
    if not product:
        return None
    total = db.query(WarehouseInventoryDB).filter(
        WarehouseInventoryDB.org_id == org_id,
        WarehouseInventoryDB.product_id == product_id,
    ).all()
    new_total = sum(row.available_stock for row in total)
    product.stock_quantity = new_total
    db.commit()
    return new_total
