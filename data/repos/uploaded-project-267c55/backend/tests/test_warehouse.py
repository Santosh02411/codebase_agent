"""
Tests for Phase 3 — Warehouse Management:
- Warehouse CRUD (admin-only) + tenant isolation
- Stock-in/out/adjust/damage/transfer, with movement log entries for each
- Low-stock listing
- Suppliers + purchase orders + goods-received workflow, including
  partial receipt and the PO status lifecycle
- The opt-in bridge back to ProductDB.stock_quantity
- Permission gating (dispatcher can manage inventory by default; agent cannot)
"""

from app.models.product import ProductDB


def _create_product(client, auth_headers, name="Widget"):
    resp = client.post(
        "/admin/products/",
        json={"name": name, "description": "test", "price": 9.99, "category": "misc", "is_active": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_warehouse(client, auth_headers, name="Main WH"):
    resp = client.post("/warehouses/", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
            "role": "agent", "display_name": username, "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


# ---------- Warehouse CRUD ----------

def test_admin_can_create_list_update_delete_warehouse(client, auth_headers):
    wh = _create_warehouse(client, auth_headers, "WH1")
    resp = client.get("/warehouses/", headers=auth_headers)
    assert any(w["id"] == wh["id"] for w in resp.json())

    resp = client.patch(f"/warehouses/{wh['id']}", json={"name": "WH1 renamed"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "WH1 renamed"

    resp = client.delete(f"/warehouses/{wh['id']}", headers=auth_headers)
    assert resp.status_code == 200


def test_warehouse_manager_must_be_dispatcher_or_admin(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "wh_manager_agent")
    resp = client.post("/warehouses/", json={"name": "Bad WH", "manager_user_id": agent_id}, headers=auth_headers)
    assert resp.status_code == 400


def test_cannot_delete_warehouse_with_stock(client, auth_headers):
    wh = _create_warehouse(client, auth_headers, "WH Stocked")
    product_id = _create_product(client, auth_headers)
    client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 10}, headers=auth_headers)

    resp = client.delete(f"/warehouses/{wh['id']}", headers=auth_headers)
    assert resp.status_code == 400


def test_warehouses_isolated_between_organizations(client, auth_headers, signed_up_admin):
    wh = _create_warehouse(client, auth_headers)
    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "wh_other_org_admin", "email": "wh_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org WH",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/warehouses/{wh['id']}/inventory", headers=other_headers)
    assert resp.status_code == 404


# ---------- Stock movements ----------

def test_stock_in_out_adjust_and_damage_flow(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)

    resp = client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 50, "sku": "SKU-1"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 50
    assert resp.json()["sku"] == "SKU-1"

    resp = client.post(f"/warehouses/{wh['id']}/stock-out", json={"product_id": product_id, "quantity": 10}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 40

    resp = client.post(f"/warehouses/{wh['id']}/damage", json={"product_id": product_id, "quantity": 5}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 35
    assert resp.json()["damaged_stock"] == 5

    resp = client.post(f"/warehouses/{wh['id']}/adjust", json={"product_id": product_id, "new_available_stock": 100, "reason": "physical count"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 100

    resp = client.get(f"/warehouses/{wh['id']}/movements", headers=auth_headers)
    assert resp.status_code == 200
    types = [m["movement_type"] for m in resp.json()]
    assert set(types) == {"stock_in", "stock_out", "damage", "adjustment"}


def test_stock_out_rejected_when_insufficient(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)
    client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 5}, headers=auth_headers)

    resp = client.post(f"/warehouses/{wh['id']}/stock-out", json={"product_id": product_id, "quantity": 10}, headers=auth_headers)
    assert resp.status_code == 400


def test_transfer_stock_between_warehouses(client, auth_headers):
    wh_a = _create_warehouse(client, auth_headers, "WH A")
    wh_b = _create_warehouse(client, auth_headers, "WH B")
    product_id = _create_product(client, auth_headers)
    client.post(f"/warehouses/{wh_a['id']}/stock-in", json={"product_id": product_id, "quantity": 20}, headers=auth_headers)

    resp = client.post(
        f"/warehouses/{wh_a['id']}/transfer",
        json={"product_id": product_id, "to_warehouse_id": wh_b["id"], "quantity": 8},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 12

    resp = client.get(f"/warehouses/{wh_b['id']}/inventory", headers=auth_headers)
    dest_row = next(r for r in resp.json() if r["product_id"] == product_id)
    assert dest_row["available_stock"] == 8

    resp_a = client.get(f"/warehouses/{wh_a['id']}/movements", headers=auth_headers)
    resp_b = client.get(f"/warehouses/{wh_b['id']}/movements", headers=auth_headers)
    assert any(m["movement_type"] == "transfer_out" for m in resp_a.json())
    assert any(m["movement_type"] == "transfer_in" for m in resp_b.json())


def test_transfer_to_same_warehouse_rejected(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)
    resp = client.post(
        f"/warehouses/{wh['id']}/transfer",
        json={"product_id": product_id, "to_warehouse_id": wh["id"], "quantity": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_low_stock_listing(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers, "Low Stock Item")
    client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 3}, headers=auth_headers)
    client.post(f"/warehouses/{wh['id']}/adjust", json={"product_id": product_id, "new_available_stock": 2, "reason": "count"}, headers=auth_headers)

    resp = client.get("/warehouses/low-stock", headers=auth_headers)
    assert resp.status_code == 200
    assert any(r["product_id"] == product_id for r in resp.json())


# ---------- Suppliers + Purchase Orders ----------

def test_supplier_and_purchase_order_goods_received_flow(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers, "PO Item")

    resp = client.post("/warehouses/suppliers/", json={"name": "Acme Supplies", "contact_email": "acme@example.com"}, headers=auth_headers)
    assert resp.status_code == 200
    supplier_id = resp.json()["id"]

    resp = client.post(
        "/warehouses/purchase-orders/",
        json={"supplier_id": supplier_id, "warehouse_id": wh["id"], "items": [{"product_id": product_id, "ordered_quantity": 20, "unit_cost": 5.0}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    po = resp.json()
    assert po["status"] == "ordered"
    item_id = po["items"][0]["id"]

    # partial receive
    resp = client.post(f"/warehouses/purchase-orders/{po['id']}/items/{item_id}/receive", json={"received_quantity": 12}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 12

    resp = client.get("/warehouses/purchase-orders/", headers=auth_headers)
    matching = next(p for p in resp.json() if p["id"] == po["id"])
    assert matching["status"] == "partially_received"

    # receive the rest
    resp = client.post(f"/warehouses/purchase-orders/{po['id']}/items/{item_id}/receive", json={"received_quantity": 8}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available_stock"] == 20

    resp = client.get("/warehouses/purchase-orders/", headers=auth_headers)
    matching = next(p for p in resp.json() if p["id"] == po["id"])
    assert matching["status"] == "received"


def test_cannot_receive_more_than_ordered(client, auth_headers):
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)
    resp = client.post("/warehouses/suppliers/", json={"name": "Supplier X"}, headers=auth_headers)
    supplier_id = resp.json()["id"]
    resp = client.post(
        "/warehouses/purchase-orders/",
        json={"supplier_id": supplier_id, "warehouse_id": wh["id"], "items": [{"product_id": product_id, "ordered_quantity": 5}]},
        headers=auth_headers,
    )
    po = resp.json()
    item_id = po["items"][0]["id"]
    resp = client.post(f"/warehouses/purchase-orders/{po['id']}/items/{item_id}/receive", json={"received_quantity": 10}, headers=auth_headers)
    assert resp.status_code == 400


# ---------- Bridge to existing inventory system ----------

def test_sync_product_stock_from_warehouses_is_opt_in(client, auth_headers, db_engine):
    from sqlalchemy.orm import sessionmaker
    wh_a = _create_warehouse(client, auth_headers, "Bridge WH A")
    wh_b = _create_warehouse(client, auth_headers, "Bridge WH B")
    product_id = _create_product(client, auth_headers, "Bridged Item")

    client.post(f"/warehouses/{wh_a['id']}/stock-in", json={"product_id": product_id, "quantity": 7}, headers=auth_headers)
    client.post(f"/warehouses/{wh_b['id']}/stock-in", json={"product_id": product_id, "quantity": 3}, headers=auth_headers)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
        original_stock = product.stock_quantity
    finally:
        db.close()

    resp = client.post(f"/warehouses/products/{product_id}/sync-stock", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["stock_quantity"] == 10

    db = Session()
    try:
        product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
        assert product.stock_quantity == 10
        assert original_stock != 10  # confirms the sync call is what actually changed it, not product creation
    finally:
        db.close()


# ---------- Permission gating (Phase 4 integration) ----------

def test_dispatcher_can_manage_inventory_by_default(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "wh_dispatcher", "email": "wh_dispatcher@example.com", "password": "correct-horse-battery",
            "role": "dispatcher", "display_name": "WH Dispatcher", "invite_code": invite_code,
        },
    )
    dispatcher_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)

    resp = client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 5}, headers=dispatcher_headers)
    assert resp.status_code == 200


def test_agent_cannot_manage_inventory_by_default(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "wh_perm_agent")
    wh = _create_warehouse(client, auth_headers)
    product_id = _create_product(client, auth_headers)

    resp = client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product_id, "quantity": 5}, headers=agent_headers)
    assert resp.status_code == 403
