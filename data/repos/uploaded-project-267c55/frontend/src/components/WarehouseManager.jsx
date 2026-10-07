import React, { useEffect, useState } from "react";
import {
  fetchWarehouses, createWarehouse, deleteWarehouse,
  fetchWarehouseInventory, fetchLowStock,
  stockIn, stockOut, adjustWarehouseStock, transferWarehouseStock, reportWarehouseDamage,
  fetchStockMovements,
  fetchSuppliers, createSupplier,
  fetchPurchaseOrders, createPurchaseOrder, receivePurchaseOrderItem,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const TABS = ["Warehouses", "Inventory", "Suppliers", "Purchase Orders", "Low Stock"];

/**
 * Warehouse management (Phase 3). Everything here calls
 * inventory.view / inventory.manage permission-gated endpoints (see
 * routes/warehouse.py) — a dispatcher without the permission (e.g.
 * narrowed by a custom role) simply gets a 403 shown as a toast, same
 * as any other permission-aware action in this app.
 */
export default function WarehouseManager() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState("Warehouses");
  const [warehouses, setWarehouses] = useState([]);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [movements, setMovements] = useState([]);
  const [lowStock, setLowStock] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);

  const [newWhName, setNewWhName] = useState("");
  const [newWhAddress, setNewWhAddress] = useState("");

  const [movementForm, setMovementForm] = useState({ product_id: "", quantity: "", reference: "" });
  const [transferTarget, setTransferTarget] = useState("");
  const [adjustNewTotal, setAdjustNewTotal] = useState("");
  const [adjustReason, setAdjustReason] = useState("");

  const [newSupplierName, setNewSupplierName] = useState("");
  const [newSupplierEmail, setNewSupplierEmail] = useState("");

  const [poSupplierId, setPoSupplierId] = useState("");
  const [poWarehouseId, setPoWarehouseId] = useState("");
  const [poItems, setPoItems] = useState([{ product_id: "", ordered_quantity: "" }]);

  useEffect(() => {
    loadWarehouses();
    loadSuppliers();
    loadPurchaseOrders();
    loadLowStock();
  }, []);

  useEffect(() => {
    if (selectedWarehouseId) {
      loadInventory(selectedWarehouseId);
      loadMovements(selectedWarehouseId);
    }
  }, [selectedWarehouseId]);

  async function loadWarehouses() {
    try {
      const data = await fetchWarehouses(token);
      setWarehouses(data);
      if (data.length > 0 && !selectedWarehouseId) setSelectedWarehouseId(data[0].id);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadInventory(warehouseId) {
    try {
      setInventory(await fetchWarehouseInventory(token, warehouseId));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadMovements(warehouseId) {
    try {
      setMovements(await fetchStockMovements(token, warehouseId));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadLowStock() {
    try {
      setLowStock(await fetchLowStock(token));
    } catch (err) {
      // permission-gated — fail silently on the summary tab, the Low Stock tab itself will surface the real error
    }
  }

  async function loadSuppliers() {
    try {
      setSuppliers(await fetchSuppliers(token));
    } catch (err) {
      // ditto
    }
  }

  async function loadPurchaseOrders() {
    try {
      setPurchaseOrders(await fetchPurchaseOrders(token));
    } catch (err) {
      // ditto
    }
  }

  async function handleCreateWarehouse(e) {
    e.preventDefault();
    try {
      await createWarehouse(token, { name: newWhName.trim(), address: newWhAddress.trim() || undefined });
      setNewWhName("");
      setNewWhAddress("");
      showToast("Warehouse created.", "success");
      await loadWarehouses();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleDeleteWarehouse(id) {
    try {
      await deleteWarehouse(token, id);
      showToast("Warehouse deleted.", "success");
      if (selectedWarehouseId === id) setSelectedWarehouseId(null);
      await loadWarehouses();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleMovement(kind) {
    if (!selectedWarehouseId || !movementForm.product_id || !movementForm.quantity) {
      showToast("Product ID and quantity are required.", "error");
      return;
    }
    const payload = { product_id: movementForm.product_id, quantity: Number(movementForm.quantity), reference: movementForm.reference || undefined };
    try {
      if (kind === "in") await stockIn(token, selectedWarehouseId, payload);
      else if (kind === "out") await stockOut(token, selectedWarehouseId, payload);
      else if (kind === "damage") await reportWarehouseDamage(token, selectedWarehouseId, payload);
      else if (kind === "transfer") {
        if (!transferTarget) { showToast("Choose a destination warehouse.", "error"); return; }
        await transferWarehouseStock(token, selectedWarehouseId, { ...payload, to_warehouse_id: transferTarget });
      }
      showToast("Stock updated.", "success");
      setMovementForm({ product_id: "", quantity: "", reference: "" });
      await loadInventory(selectedWarehouseId);
      await loadMovements(selectedWarehouseId);
      await loadLowStock();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAdjust(productId) {
    if (adjustNewTotal === "" || !adjustReason.trim()) {
      showToast("New total and a reason are required.", "error");
      return;
    }
    try {
      await adjustWarehouseStock(token, selectedWarehouseId, {
        product_id: productId, new_available_stock: Number(adjustNewTotal), reason: adjustReason.trim(),
      });
      showToast("Stock adjusted.", "success");
      setAdjustNewTotal("");
      setAdjustReason("");
      await loadInventory(selectedWarehouseId);
      await loadMovements(selectedWarehouseId);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCreateSupplier(e) {
    e.preventDefault();
    try {
      await createSupplier(token, { name: newSupplierName.trim(), contact_email: newSupplierEmail.trim() || undefined });
      setNewSupplierName("");
      setNewSupplierEmail("");
      showToast("Supplier added.", "success");
      await loadSuppliers();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function updatePoItem(index, field, value) {
    setPoItems((prev) => prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }

  async function handleCreatePurchaseOrder(e) {
    e.preventDefault();
    if (!poSupplierId || !poWarehouseId) {
      showToast("Choose a supplier and a warehouse.", "error");
      return;
    }
    const items = poItems
      .filter((i) => i.product_id && i.ordered_quantity)
      .map((i) => ({ product_id: i.product_id, ordered_quantity: Number(i.ordered_quantity) }));
    if (items.length === 0) {
      showToast("Add at least one item.", "error");
      return;
    }
    try {
      await createPurchaseOrder(token, { supplier_id: poSupplierId, warehouse_id: poWarehouseId, items });
      setPoItems([{ product_id: "", ordered_quantity: "" }]);
      showToast("Purchase order created.", "success");
      await loadPurchaseOrders();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleReceive(poId, itemId, orderedQty, alreadyReceived) {
    const remaining = orderedQty - alreadyReceived;
    const qtyStr = window.prompt(`How many units received? (up to ${remaining} remaining)`, String(remaining));
    if (!qtyStr) return;
    const qty = Number(qtyStr);
    if (!qty || qty <= 0) return;
    try {
      await receivePurchaseOrderItem(token, poId, itemId, qty);
      showToast("Goods received.", "success");
      await loadPurchaseOrders();
      await loadInventory(selectedWarehouseId);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">Warehouse Management</h2>

      <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t} className={tab === t ? "btn btn-primary" : "btn"} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "Warehouses" && (
        <div>
          <form onSubmit={handleCreateWarehouse} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", flexWrap: "wrap", marginBottom: "16px" }}>
            <div>
              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Name</label>
              <input className="input" required value={newWhName} onChange={(e) => setNewWhName(e.target.value)} />
            </div>
            <div>
              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Address (optional)</label>
              <input className="input" value={newWhAddress} onChange={(e) => setNewWhAddress(e.target.value)} />
            </div>
            <button type="submit" className="btn btn-primary">Add Warehouse</button>
          </form>

          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Name</th><th>Address</th><th>Active</th><th>Actions</th></tr></thead>
              <tbody>
                {warehouses.map((w) => (
                  <tr key={w.id}>
                    <td>{w.name}</td>
                    <td>{w.address || "—"}</td>
                    <td>{w.active ? "Yes" : "No"}</td>
                    <td>
                      <div style={{ display: "flex", gap: "6px" }}>
                        <button className="btn-info-outline" onClick={() => { setSelectedWarehouseId(w.id); setTab("Inventory"); }}>View Inventory</button>
                        <button className="btn-danger-outline" onClick={() => handleDeleteWarehouse(w.id)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "Inventory" && (
        <div>
          <div style={{ marginBottom: "12px" }}>
            <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Warehouse</label>
            <select className="input" value={selectedWarehouseId || ""} onChange={(e) => setSelectedWarehouseId(e.target.value)}>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>

          <div className="card" style={{ marginBottom: "16px" }}>
            <h4 style={{ marginBottom: "10px" }}>Record Stock Movement</h4>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "flex-end" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Product ID</label>
                <input className="input" value={movementForm.product_id} onChange={(e) => setMovementForm({ ...movementForm, product_id: e.target.value })} placeholder="From Products" />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Quantity</label>
                <input type="number" className="input" value={movementForm.quantity} onChange={(e) => setMovementForm({ ...movementForm, quantity: e.target.value })} />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Reference (optional)</label>
                <input className="input" value={movementForm.reference} onChange={(e) => setMovementForm({ ...movementForm, reference: e.target.value })} />
              </div>
              <button className="btn btn-primary" onClick={() => handleMovement("in")}>Stock In</button>
              <button className="btn" onClick={() => handleMovement("out")}>Stock Out</button>
              <button className="btn-danger-outline" onClick={() => handleMovement("damage")}>Report Damage</button>
            </div>
            <div style={{ display: "flex", gap: "8px", marginTop: "10px", alignItems: "flex-end", flexWrap: "wrap" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Transfer to</label>
                <select className="input" value={transferTarget} onChange={(e) => setTransferTarget(e.target.value)}>
                  <option value="">Choose warehouse...</option>
                  {warehouses.filter((w) => w.id !== selectedWarehouseId).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
              <button className="btn" onClick={() => handleMovement("transfer")}>Transfer Stock</button>
            </div>
          </div>

          <h4 style={{ marginBottom: "10px" }}>Inventory</h4>
          <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: "16px" }}>
            <table className="data-table">
              <thead><tr><th>Product ID</th><th>SKU</th><th>Available</th><th>Reserved</th><th>Damaged</th><th>Low Stock At</th><th>Adjust</th></tr></thead>
              <tbody>
                {inventory.length === 0 && <tr><td colSpan={7} style={{ color: "var(--text-muted)" }}>No inventory recorded yet for this warehouse.</td></tr>}
                {inventory.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.product_id}</td>
                    <td>{row.sku || "—"}</td>
                    <td>{row.available_stock}</td>
                    <td>{row.reserved_stock}</td>
                    <td>{row.damaged_stock}</td>
                    <td>{row.low_stock_threshold}</td>
                    <td>
                      <div style={{ display: "flex", gap: "4px" }}>
                        <input type="number" className="input" placeholder="New total" style={{ width: "80px" }} value={adjustNewTotal} onChange={(e) => setAdjustNewTotal(e.target.value)} />
                        <input className="input" placeholder="Reason" style={{ width: "90px" }} value={adjustReason} onChange={(e) => setAdjustReason(e.target.value)} />
                        <button className="btn-info-outline" onClick={() => handleAdjust(row.product_id)}>Set</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 style={{ marginBottom: "10px" }}>Movement History</h4>
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Type</th><th>Product</th><th>Qty</th><th>Reference</th><th>When</th></tr></thead>
              <tbody>
                {movements.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>No movements yet.</td></tr>}
                {movements.map((m) => (
                  <tr key={m.id}>
                    <td style={{ textTransform: "capitalize" }}>{m.movement_type.replace("_", " ")}</td>
                    <td className="mono">{m.product_id}</td>
                    <td>{m.quantity}</td>
                    <td>{m.reference || "—"}</td>
                    <td>{new Date(m.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "Suppliers" && (
        <div>
          <form onSubmit={handleCreateSupplier} className="card" style={{ display: "flex", gap: "8px", alignItems: "flex-end", flexWrap: "wrap", marginBottom: "16px" }}>
            <div>
              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Name</label>
              <input className="input" required value={newSupplierName} onChange={(e) => setNewSupplierName(e.target.value)} />
            </div>
            <div>
              <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Contact Email (optional)</label>
              <input className="input" value={newSupplierEmail} onChange={(e) => setNewSupplierEmail(e.target.value)} />
            </div>
            <button type="submit" className="btn btn-primary">Add Supplier</button>
          </form>
          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Name</th><th>Email</th><th>Active</th></tr></thead>
              <tbody>
                {suppliers.map((s) => (
                  <tr key={s.id}><td>{s.name}</td><td>{s.contact_email || "—"}</td><td>{s.active ? "Yes" : "No"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "Purchase Orders" && (
        <div>
          <form onSubmit={handleCreatePurchaseOrder} className="card" style={{ marginBottom: "16px" }}>
            <h4 style={{ marginBottom: "10px" }}>New Purchase Order</h4>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "10px" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Supplier</label>
                <select className="input" value={poSupplierId} onChange={(e) => setPoSupplierId(e.target.value)}>
                  <option value="">Choose...</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Warehouse</label>
                <select className="input" value={poWarehouseId} onChange={(e) => setPoWarehouseId(e.target.value)}>
                  <option value="">Choose...</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
            </div>
            {poItems.map((item, i) => (
              <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "6px" }}>
                <input className="input" placeholder="Product ID" value={item.product_id} onChange={(e) => updatePoItem(i, "product_id", e.target.value)} />
                <input type="number" className="input" placeholder="Ordered qty" style={{ width: "120px" }} value={item.ordered_quantity} onChange={(e) => updatePoItem(i, "ordered_quantity", e.target.value)} />
              </div>
            ))}
            <button type="button" className="btn" onClick={() => setPoItems([...poItems, { product_id: "", ordered_quantity: "" }])} style={{ marginBottom: "10px" }}>+ Add item</button>
            <br />
            <button type="submit" className="btn btn-primary">Create Purchase Order</button>
          </form>

          <div className="card" style={{ padding: 0, overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th>Status</th><th>Items</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {purchaseOrders.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>No purchase orders yet.</td></tr>}
                {purchaseOrders.map((po) => (
                  <tr key={po.id}>
                    <td style={{ textTransform: "capitalize" }}>{po.status.replace("_", " ")}</td>
                    <td>
                      {po.items.map((item) => (
                        <div key={item.id} style={{ fontSize: "12px", marginBottom: "4px" }}>
                          {item.product_id.slice(0, 8)}... — {item.received_quantity}/{item.ordered_quantity}
                          {item.received_quantity < item.ordered_quantity && (
                            <button className="btn-info-outline" style={{ marginLeft: "8px", fontSize: "11px" }} onClick={() => handleReceive(po.id, item.id, item.ordered_quantity, item.received_quantity)}>
                              Receive
                            </button>
                          )}
                        </div>
                      ))}
                    </td>
                    <td>{new Date(po.created_at).toLocaleDateString()}</td>
                    <td>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "Low Stock" && (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data-table">
            <thead><tr><th>Product</th><th>Warehouse</th><th>Available</th><th>Threshold</th></tr></thead>
            <tbody>
              {lowStock.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>Nothing below threshold right now.</td></tr>}
              {lowStock.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.product_id}</td>
                  <td className="mono">{row.warehouse_id.slice(0, 8)}...</td>
                  <td style={{ color: "var(--danger)", fontWeight: 600 }}>{row.available_stock}</td>
                  <td>{row.low_stock_threshold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
