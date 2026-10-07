"""
Tests for routes/stores.py — the public, no-login marketplace directory
of every org that opted into is_public_store, plus browsing one store's
products. Covers the opt-in visibility rule itself, search/category
filtering, and that only active products from public stores are ever
listed.
"""


def _make_public_store(client, auth_headers, category=None):
    resp = client.patch("/admin/store/visibility", json={"is_public_store": True}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    if category:
        resp = client.patch("/admin/store/profile", json={"category": category}, headers=auth_headers)
        assert resp.status_code == 200, resp.text


def test_private_store_is_not_listed(client, auth_headers, signed_up_admin):
    resp = client.patch("/admin/store/visibility", json={"is_public_store": False}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    org_id = signed_up_admin["user"]["org_id"]
    resp = client.get("/stores/")
    assert resp.status_code == 200
    assert not any(s["id"] == org_id for s in resp.json())


def test_opted_in_store_appears_in_marketplace(client, auth_headers, signed_up_admin):
    _make_public_store(client, auth_headers)
    org_id = signed_up_admin["user"]["org_id"]

    resp = client.get("/stores/")
    assert resp.status_code == 200
    assert any(s["id"] == org_id for s in resp.json())


def test_marketplace_search_matches_store_name_case_insensitively(client, auth_headers, signed_up_admin):
    _make_public_store(client, auth_headers)
    org_name = signed_up_admin["payload"]["org_name"]

    resp = client.get("/stores/", params={"search": org_name.upper()[:6]})
    assert resp.status_code == 200
    assert any(s["name"] == org_name for s in resp.json())

    resp = client.get("/stores/", params={"search": "definitely-not-a-real-store-name-xyz"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_marketplace_category_filter_and_listing(client, auth_headers, signed_up_admin):
    _make_public_store(client, auth_headers, category="Bakery")
    org_id = signed_up_admin["user"]["org_id"]

    resp = client.get("/stores/categories")
    assert resp.status_code == 200
    assert "Bakery" in resp.json()

    resp = client.get("/stores/", params={"category": "bakery"})  # case-insensitive exact match
    assert resp.status_code == 200
    assert any(s["id"] == org_id for s in resp.json())

    resp = client.get("/stores/", params={"category": "Butchery"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_store_products_only_lists_active_products_from_public_stores(client, auth_headers, signed_up_admin):
    _make_public_store(client, auth_headers)
    org_id = signed_up_admin["user"]["org_id"]

    active = client.post(
        "/admin/products/",
        json={"name": "Visible Item", "price": 10.0, "is_active": True},
        headers=auth_headers,
    ).json()
    inactive = client.post(
        "/admin/products/",
        json={"name": "Hidden Item", "price": 10.0, "is_active": False},
        headers=auth_headers,
    ).json()

    resp = client.get(f"/stores/{org_id}/products")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert active["id"] in ids
    assert inactive["id"] not in ids


def test_store_products_404_for_private_store(client, auth_headers, signed_up_admin):
    resp = client.patch("/admin/store/visibility", json={"is_public_store": False}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    org_id = signed_up_admin["user"]["org_id"]
    resp = client.get(f"/stores/{org_id}/products")
    assert resp.status_code == 404


def test_store_products_404_for_unknown_org(client):
    resp = client.get("/stores/not-a-real-org-id/products")
    assert resp.status_code == 404
