"""
Tests for Phase 16 — Enterprise Organization Management:
- Branding update, hex color validation
- Locale update (timezone/currency)
- Usage metrics reflect real counts
- Suspension: blocks new invite-code signups, new checkout, drops from
  public storefront listing; does NOT block existing staff login
- Reactivation
- Data export shape
- Admin-only access, tenant isolation
"""


def _place_order(client, auth_headers, customer_auth_headers):
    product = client.post("/admin/products/", json={"name": "Org Item", "price": 60.0, "is_active": True}, headers=auth_headers).json()
    resp = client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    return client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": "cod"},
        headers=customer_auth_headers,
    )


# ---------- Branding & locale ----------

def test_update_branding(client, auth_headers):
    resp = client.patch("/admin/organization/branding", json={"logo_url": "https://example.com/logo.png", "brand_color": "#2563eb"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_url"] == "https://example.com/logo.png"
    assert resp.json()["brand_color"] == "#2563eb"


def test_invalid_brand_color_rejected(client, auth_headers):
    resp = client.patch("/admin/organization/branding", json={"brand_color": "blue"}, headers=auth_headers)
    assert resp.status_code == 400


def test_update_locale(client, auth_headers):
    resp = client.patch("/admin/organization/locale", json={"timezone": "America/New_York", "currency_code": "usd", "currency_symbol": "$"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["timezone"] == "America/New_York"
    assert resp.json()["currency_code"] == "USD"  # normalized uppercase
    assert resp.json()["currency_symbol"] == "$"


# ---------- Usage metrics ----------

def test_usage_metrics_reflect_real_counts(client, auth_headers, customer_auth_headers):
    resp = client.get("/admin/organization/usage", headers=auth_headers)
    before = resp.json()["total_orders"]

    resp = _place_order(client, auth_headers, customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/organization/usage", headers=auth_headers)
    after = resp.json()
    assert after["total_orders"] == before + 1
    assert after["staff_count"] >= 1


# ---------- Suspension ----------

def test_suspend_blocks_new_signups_and_checkout_but_not_existing_staff(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]

    resp = client.post("/admin/organization/suspend", json={"reason": "Restructuring"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_suspended"] is True
    assert resp.json()["suspended_reason"] == "Restructuring"

    # Existing admin can still operate (not locked out)
    resp = client.get("/admin/organization/usage", headers=auth_headers)
    assert resp.status_code == 200

    # New staff signup via invite code is blocked
    resp = client.post(
        "/auth/signup",
        json={
            "username": "org_suspended_agent", "email": "org_suspended_agent@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Agent", "invite_code": invite_code,
        },
    )
    assert resp.status_code == 403

    # New checkout against this org is blocked
    resp = _place_order(client, auth_headers, customer_auth_headers)
    assert resp.status_code == 403


def test_suspended_org_dropped_from_public_storefront(client, auth_headers):
    resp = client.patch("/admin/store/visibility", json={"is_public_store": True}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/stores/")
    org_ids_before = {o["id"] for o in resp.json()}
    org_id = list(org_ids_before)[0] if org_ids_before else None

    client.post("/admin/organization/suspend", json={"reason": "test"}, headers=auth_headers)
    resp = client.get("/stores/")
    org_ids_after = {o["id"] for o in resp.json()}
    assert org_id not in org_ids_after


def test_cannot_suspend_already_suspended_org(client, auth_headers):
    client.post("/admin/organization/suspend", json={"reason": "first"}, headers=auth_headers)
    resp = client.post("/admin/organization/suspend", json={"reason": "second"}, headers=auth_headers)
    assert resp.status_code == 400


def test_reactivate_restores_normal_operation(client, signed_up_admin, auth_headers, customer_auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    client.post("/admin/organization/suspend", json={"reason": "test"}, headers=auth_headers)

    resp = client.post("/admin/organization/reactivate", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_suspended"] is False
    assert resp.json()["suspended_reason"] is None

    resp = client.post(
        "/auth/signup",
        json={
            "username": "org_reactivated_agent", "email": "org_reactivated_agent@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Agent", "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200

    resp = _place_order(client, auth_headers, customer_auth_headers)
    assert resp.status_code == 200


def test_cannot_reactivate_non_suspended_org(client, auth_headers):
    resp = client.post("/admin/organization/reactivate", headers=auth_headers)
    assert resp.status_code == 400


# ---------- Data export ----------

def test_export_organization_data_shape(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers)
    resp = client.get("/admin/organization/export", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "organization" in body
    assert "staff" in body
    assert "summary" in body
    assert body["summary"]["total_orders"] >= 1
    assert all("hashed_password" not in s for s in body["staff"])


# ---------- Access control ----------

def test_only_admin_can_manage_organization(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "org_dispatcher_noperm", "email": "org_dispatcher_noperm@example.com",
            "password": "correct-horse-battery", "role": "dispatcher", "display_name": "Dispatcher", "invite_code": invite_code,
        },
    )
    dispatcher_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = client.get("/admin/organization/usage", headers=dispatcher_headers)
    assert resp.status_code == 403


def test_usage_metrics_isolated_between_organizations(client, auth_headers, customer_auth_headers):
    resp = _place_order(client, auth_headers, customer_auth_headers)
    assert resp.status_code == 200

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "org_other_org_admin", "email": "org_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org Enterprise",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get("/admin/organization/usage", headers=other_headers)
    assert resp.json()["total_orders"] == 0
