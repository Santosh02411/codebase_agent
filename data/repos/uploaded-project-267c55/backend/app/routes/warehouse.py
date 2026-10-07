"""
Warehouse routes (Phase 3), authorized via the new granular permission
system (Phase 4) rather than the coarser require_dispatcher/require_admin
checks — see services/permissions.py. Warehouse CRUD itself stays
admin-only (a structural, org-configuration action, same tier as zone
or reason-code management); day-to-day inventory operations (stock
movements, suppliers, purchase orders) are gated on
inventory.view / inventory.manage, which dispatchers get by default
(see ROLE_DEFAULT_PERMISSIONS) and which can be granted or withheld
per-user via a custom role.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.warehouse import (
    WarehouseDB, WarehouseInventoryDB, StockMovementDB, SupplierDB, PurchaseOrderDB, PurchaseOrderItemDB,
    WarehouseCreate, WarehouseUpdate, WarehouseOut,
    WarehouseInventoryOut, StockMovementIn, StockAdjustmentIn, StockTransferIn, DamageReportIn, StockMovementOut,
    SupplierCreate, SupplierUpdate, SupplierOut,
    PurchaseOrderCreate, PurchaseOrderOut, PurchaseOrderItemOut, GoodsReceivedIn,
)
from app.routes.admin import require_admin
from app.services.permissions import require_permission
from app.services import warehouse as warehouse_service
from app.services.action_log import record_action

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


def _get_warehouse_or_404(db: Session, warehouse_id: str, org_id: str) -> WarehouseDB:
    wh = db.query(WarehouseDB).filter(WarehouseDB.id == warehouse_id, WarehouseDB.org_id == org_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    return wh


# ---------- Warehouse CRUD (admin) ----------

@router.get("/", response_model=List[WarehouseOut])
def list_warehouses(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    return db.query(WarehouseDB).filter(WarehouseDB.org_id == current_user.org_id).order_by(WarehouseDB.created_at.asc()).all()


@router.post("/", response_model=WarehouseOut)
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    if payload.manager_user_id:
        manager = db.query(UserDB).filter(UserDB.id == payload.manager_user_id, UserDB.org_id == current_user.org_id).first()
        if not manager or manager.role not in (UserRole.dispatcher, UserRole.admin):
            raise HTTPException(status_code=400, detail="Warehouse manager must be a dispatcher or admin in your organization.")

    wh = WarehouseDB(org_id=current_user.org_id, **payload.dict())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="warehouse", entity_id=wh.id, entity_label=wh.name,
        summary=f"Created warehouse '{wh.name}'.",
    )
    return wh


@router.patch("/{warehouse_id}", response_model=WarehouseOut)
def update_warehouse(warehouse_id: str, payload: WarehouseUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    wh = _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(wh, field, value)
    db.commit()
    db.refresh(wh)
    return wh


@router.delete("/{warehouse_id}")
def delete_warehouse(warehouse_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    wh = _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    has_stock = db.query(WarehouseInventoryDB.id).filter(
        WarehouseInventoryDB.warehouse_id == warehouse_id, WarehouseInventoryDB.available_stock > 0,
    ).first()
    if has_stock:
        raise HTTPException(status_code=400, detail="This warehouse still has stock on hand — transfer or remove it before deleting the warehouse.")
    db.delete(wh)
    db.commit()
    return {"message": "Warehouse deleted."}


# ---------- Inventory (view/manage permission) ----------

@router.get("/{warehouse_id}/inventory", response_model=List[WarehouseInventoryOut])
def list_warehouse_inventory(warehouse_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    return db.query(WarehouseInventoryDB).filter(WarehouseInventoryDB.warehouse_id == warehouse_id).all()


@router.get("/low-stock", response_model=List[WarehouseInventoryOut])
def list_low_stock(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    rows = db.query(WarehouseInventoryDB).filter(WarehouseInventoryDB.org_id == current_user.org_id).all()
    return [r for r in rows if r.available_stock <= r.low_stock_threshold]


@router.post("/{warehouse_id}/stock-in", response_model=WarehouseInventoryOut)
def stock_in(warehouse_id: str, payload: StockMovementIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    return warehouse_service.stock_in(db, current_user.org_id, warehouse_id, payload, current_user.id)


@router.post("/{warehouse_id}/stock-out", response_model=WarehouseInventoryOut)
def stock_out(warehouse_id: str, payload: StockMovementIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    try:
        return warehouse_service.stock_out(db, current_user.org_id, warehouse_id, payload, current_user.id)
    except warehouse_service.InsufficientWarehouseStockError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/{warehouse_id}/adjust", response_model=WarehouseInventoryOut)
def adjust_stock(warehouse_id: str, payload: StockAdjustmentIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    return warehouse_service.adjust_stock(db, current_user.org_id, warehouse_id, payload, current_user.id)


@router.post("/{warehouse_id}/transfer", response_model=WarehouseInventoryOut)
def transfer_stock(warehouse_id: str, payload: StockTransferIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    _get_warehouse_or_404(db, payload.to_warehouse_id, current_user.org_id)
    if payload.to_warehouse_id == warehouse_id:
        raise HTTPException(status_code=400, detail="Source and destination warehouse can't be the same.")
    try:
        source, _dest = warehouse_service.transfer_stock(db, current_user.org_id, warehouse_id, payload, current_user.id)
    except warehouse_service.InsufficientWarehouseStockError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return source


@router.post("/{warehouse_id}/damage", response_model=WarehouseInventoryOut)
def report_damage(warehouse_id: str, payload: DamageReportIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    try:
        return warehouse_service.report_damage(db, current_user.org_id, warehouse_id, payload, current_user.id)
    except warehouse_service.InsufficientWarehouseStockError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/{warehouse_id}/movements", response_model=List[StockMovementOut])
def list_stock_movements(warehouse_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    _get_warehouse_or_404(db, warehouse_id, current_user.org_id)
    return db.query(StockMovementDB).filter(
        StockMovementDB.warehouse_id == warehouse_id
    ).order_by(StockMovementDB.created_at.desc()).all()


@router.post("/products/{product_id}/sync-stock")
def sync_product_stock(product_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    """Opt-in: writes the sum of this product's warehouse stock onto ProductDB.stock_quantity — see services/warehouse.py's sync_product_stock_from_warehouses() docstring."""
    new_total = warehouse_service.sync_product_stock_from_warehouses(db, current_user.org_id, product_id)
    if new_total is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return {"product_id": product_id, "stock_quantity": new_total}


# ---------- Suppliers ----------

@router.get("/suppliers/", response_model=List[SupplierOut])
def list_suppliers(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    return db.query(SupplierDB).filter(SupplierDB.org_id == current_user.org_id).order_by(SupplierDB.created_at.asc()).all()


@router.post("/suppliers/", response_model=SupplierOut)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    supplier = SupplierDB(org_id=current_user.org_id, **payload.dict())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: str, payload: SupplierUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    supplier = db.query(SupplierDB).filter(SupplierDB.id == supplier_id, SupplierDB.org_id == current_user.org_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(supplier, field, value)
    db.commit()
    db.refresh(supplier)
    return supplier


# ---------- Purchase Orders ----------

@router.get("/purchase-orders/", response_model=List[PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.view"))):
    orders = db.query(PurchaseOrderDB).filter(PurchaseOrderDB.org_id == current_user.org_id).order_by(PurchaseOrderDB.created_at.desc()).all()
    result = []
    for po in orders:
        items = db.query(PurchaseOrderItemDB).filter(PurchaseOrderItemDB.purchase_order_id == po.id).all()
        out = PurchaseOrderOut.model_validate(po)
        out.items = [PurchaseOrderItemOut.model_validate(i) for i in items]
        result.append(out)
    return result


@router.post("/purchase-orders/", response_model=PurchaseOrderOut)
def create_purchase_order(payload: PurchaseOrderCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    supplier = db.query(SupplierDB).filter(SupplierDB.id == payload.supplier_id, SupplierDB.org_id == current_user.org_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _get_warehouse_or_404(db, payload.warehouse_id, current_user.org_id)
    if not payload.items:
        raise HTTPException(status_code=400, detail="A purchase order needs at least one item.")

    po = PurchaseOrderDB(
        org_id=current_user.org_id, supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id,
        status="ordered", created_by_user_id=current_user.id, expected_date=payload.expected_date,
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    items = []
    for item in payload.items:
        po_item = PurchaseOrderItemDB(
            purchase_order_id=po.id, product_id=item.product_id,
            ordered_quantity=item.ordered_quantity, unit_cost=item.unit_cost,
        )
        db.add(po_item)
        items.append(po_item)
    db.commit()

    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="create", entity_type="purchase_order", entity_id=po.id,
        summary=f"Created purchase order with {len(items)} item(s) from supplier {supplier.name}.",
    )

    out = PurchaseOrderOut.model_validate(po)
    out.items = [PurchaseOrderItemOut.model_validate(i) for i in items]
    return out


@router.post("/purchase-orders/{po_id}/items/{item_id}/receive", response_model=WarehouseInventoryOut)
def receive_goods(po_id: str, item_id: str, payload: GoodsReceivedIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_permission("inventory.manage"))):
    po = db.query(PurchaseOrderDB).filter(PurchaseOrderDB.id == po_id, PurchaseOrderDB.org_id == current_user.org_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found.")
    item = db.query(PurchaseOrderItemDB).filter(PurchaseOrderItemDB.id == item_id, PurchaseOrderItemDB.purchase_order_id == po_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Purchase order item not found.")
    if item.received_quantity + payload.received_quantity > item.ordered_quantity:
        raise HTTPException(status_code=400, detail="That would receive more than was ordered for this item.")

    row = warehouse_service.receive_purchase_order_item(db, current_user.org_id, po, item, payload.received_quantity, current_user.id)
    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id, actor_display_name=current_user.display_name,
        action="update", entity_type="purchase_order", entity_id=po.id,
        summary=f"Received {payload.received_quantity} unit(s) against purchase order {po.id}.",
    )
    return row
