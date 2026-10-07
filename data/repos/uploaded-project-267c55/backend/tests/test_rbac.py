"""
Tests for Phase 4 — Granular RBAC:
- Permission catalog + my-permissions resolution for each base role
- Custom role CRUD (admin-only) + tenant isolation
- Assigning a custom role to a user changes their EFFECTIVE permissions
  (both narrowing and, implicitly, differing from the base role default)
- Deleting a role in use resets affected users to their base-role defaults
- Admins always pass every permission check, custom role or not
- Backend enforcement is real (403, not just a UI hint) — demonstrated
  against the actual Phase 3 warehouse endpoints
"""


def _signup(client, role, username, invite_code=None, org_name=None):
    payload = {
        "username": username, "email": f"{username}@example.com", "password": "correct-horse-battery",
        "role": role, "display_name": username,
    }
    if invite_code:
        payload["invite_code"] = invite_code
    if org_name:
        payload["org_name"] = org_name
    resp = client.post("/auth/signup", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def test_permissions_catalog_is_admin_only_but_lists_everything(client, auth_headers, signed_up_admin):
    resp = client.get("/admin/rbac/permissions-catalog", headers=auth_headers)
    assert resp.status_code == 200
    perms = resp.json()["permissions"]
    for expected in ("deliveries.view", "inventory.manage", "payments.refund", "workforce.manage"):
        assert expected in perms

    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup(client, "agent", "rbac_catalog_agent", invite_code=invite_code)
    resp = client.get("/admin/rbac/permissions-catalog", headers=agent_headers)
    assert resp.status_code == 403


def test_my_permissions_reflects_base_role_defaults(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup(client, "agent", "rbac_my_perms_agent", invite_code=invite_code)
    _, dispatcher_headers = _signup(client, "dispatcher", "rbac_my_perms_dispatcher", invite_code=invite_code)

    agent_perms = client.get("/admin/rbac/my-permissions", headers=agent_headers).json()["permissions"]
    assert "deliveries.update" in agent_perms
    assert "inventory.manage" not in agent_perms

    dispatcher_perms = client.get("/admin/rbac/my-permissions", headers=dispatcher_headers).json()["permissions"]
    assert "inventory.manage" in dispatcher_perms
    assert "payments.refund" not in dispatcher_perms  # not in the dispatcher default set

    admin_perms = client.get("/admin/rbac/my-permissions", headers=auth_headers).json()["permissions"]
    assert "payments.refund" in admin_perms  # admins get everything


def test_admin_can_create_update_delete_custom_role(client, auth_headers):
    resp = client.post(
        "/admin/rbac/roles",
        json={"name": "Inventory Clerk", "description": "Can manage stock only", "permissions": ["inventory.view", "inventory.manage"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    role = resp.json()
    assert set(role["permissions"]) == {"inventory.view", "inventory.manage"}

    resp = client.patch(f"/admin/rbac/roles/{role['id']}", json={"permissions": ["inventory.view"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["permissions"] == ["inventory.view"]

    resp = client.get("/admin/rbac/roles", headers=auth_headers)
    assert any(r["id"] == role["id"] for r in resp.json())

    resp = client.delete(f"/admin/rbac/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 200


def test_creating_role_with_unknown_permission_rejected(client, auth_headers):
    resp = client.post(
        "/admin/rbac/roles",
        json={"name": "Bad Role", "permissions": ["not.a.real.permission"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_non_admin_cannot_manage_custom_roles(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, dispatcher_headers = _signup(client, "dispatcher", "rbac_non_admin_dispatcher", invite_code=invite_code)
    resp = client.post("/admin/rbac/roles", json={"name": "X", "permissions": []}, headers=dispatcher_headers)
    assert resp.status_code == 403


def test_assigning_custom_role_narrows_agent_permissions(client, signed_up_admin, auth_headers):
    """A custom role's explicit grants are authoritative — even narrower than the base role would normally allow."""
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup(client, "agent", "rbac_narrow_agent", invite_code=invite_code)

    # base agent default includes deliveries.update — confirm first
    perms_before = client.get("/admin/rbac/my-permissions", headers=agent_headers).json()["permissions"]
    assert "deliveries.update" in perms_before

    role = client.post("/admin/rbac/roles", json={"name": "Read Only Agent", "permissions": ["deliveries.view"]}, headers=auth_headers).json()
    resp = client.post(f"/admin/rbac/users/{agent_id}/role", json={"custom_role_id": role["id"]}, headers=auth_headers)
    assert resp.status_code == 200

    perms_after = client.get("/admin/rbac/my-permissions", headers=agent_headers).json()["permissions"]
    assert perms_after == ["deliveries.view"]
    assert "deliveries.update" not in perms_after


def test_assigning_custom_role_can_widen_agent_permissions(client, signed_up_admin, auth_headers):
    """An agent given a custom role with inventory.manage can now do something their base role couldn't."""
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup(client, "agent", "rbac_widen_agent", invite_code=invite_code)

    wh = client.post("/warehouses/", json={"name": "RBAC WH"}, headers=auth_headers).json()
    product = client.post("/admin/products/", json={"name": "RBAC Product", "price": 1.0}, headers=auth_headers).json()

    # base agent cannot manage inventory
    resp = client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product["id"], "quantity": 5}, headers=agent_headers)
    assert resp.status_code == 403

    role = client.post("/admin/rbac/roles", json={"name": "Stock Agent", "permissions": ["inventory.view", "inventory.manage"]}, headers=auth_headers).json()
    client.post(f"/admin/rbac/users/{agent_id}/role", json={"custom_role_id": role["id"]}, headers=auth_headers)

    resp = client.post(f"/warehouses/{wh['id']}/stock-in", json={"product_id": product["id"], "quantity": 5}, headers=agent_headers)
    assert resp.status_code == 200


def test_deleting_role_in_use_resets_users_to_default(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup(client, "agent", "rbac_reset_agent", invite_code=invite_code)
    role = client.post("/admin/rbac/roles", json={"name": "Temp Role", "permissions": ["deliveries.view"]}, headers=auth_headers).json()
    client.post(f"/admin/rbac/users/{agent_id}/role", json={"custom_role_id": role["id"]}, headers=auth_headers)

    perms_with_role = client.get("/admin/rbac/my-permissions", headers=agent_headers).json()["permissions"]
    assert perms_with_role == ["deliveries.view"]

    resp = client.delete(f"/admin/rbac/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["users_reset_to_default"] == 1

    perms_after_delete = client.get("/admin/rbac/my-permissions", headers=agent_headers).json()["permissions"]
    assert "deliveries.update" in perms_after_delete  # back to normal agent defaults


def test_custom_roles_isolated_between_organizations(client, auth_headers, signed_up_admin):
    role = client.post("/admin/rbac/roles", json={"name": "Org A Role", "permissions": ["deliveries.view"]}, headers=auth_headers).json()

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "rbac_other_org_admin", "email": "rbac_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org RBAC",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.patch(f"/admin/rbac/roles/{role['id']}", json={"name": "Hijacked"}, headers=other_headers)
    assert resp.status_code == 404


def test_cannot_assign_role_or_target_user_from_another_org(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup(client, "agent", "rbac_assign_own_org_agent", invite_code=invite_code)
    role = client.post("/admin/rbac/roles", json={"name": "Local Role", "permissions": ["deliveries.view"]}, headers=auth_headers).json()

    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "rbac_other_org_admin2", "email": "rbac_other_org_admin2@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin 2",
            "org_name": "Other Org RBAC 2",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}

    # other org's admin cannot assign OUR agent a role
    resp = client.post(f"/admin/rbac/users/{agent_id}/role", json={"custom_role_id": role["id"]}, headers=other_headers)
    assert resp.status_code == 404
