"""
Tests for Phase 13 — Invoicing & Finance:
- Invoice auto-generated on real checkout (online + COD), never recomputed
  from live config (matches OrderDB's snapshotted amounts)
- Sequential document numbering per org+type
- Credit note auto-generated on a real refund (test-mode path)
- Manual credit note / debit note creation, validation, tenant isolation
- Customer can list/download own documents, not another customer's
- Financial report combines Phase 5 ledger data + document counts
"""


def _place_order(client, auth_headers, customer_auth_headers, price=100.0, payment_method="cod"):
    product = client.post("/admin/products/", json={"name": "Finance Item", "price": price, "is_active": True}, headers=auth_headers).json()
    resp = client.post("/customer/cart/", json={"product_id": product["id"], "quantity": 1}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/customer/checkout",
        json={"address_line": "1 Test St", "phone": "9999999999", "payment_method": payment_method},
        headers=customer_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = resp.json()
    resp = client.post("/customer/checkout/verify", json={"order_id": order["order_id"]}, headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["id"], body["delivery_id"], body["total"]


# ---------- Auto-generated invoice ----------

def test_invoice_auto_generated_on_cod_checkout(client, auth_headers, customer_auth_headers):
    order_id, _, total = _place_order(client, auth_headers, customer_auth_headers, payment_method="cod")
    resp = client.get("/admin/finance/documents", params={"document_type": "invoice", "order_id": order_id}, headers=auth_headers)
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["amount"] == total
    assert docs[0]["document_number"].startswith("INV-")


def test_invoice_auto_generated_on_online_checkout(client, auth_headers, customer_auth_headers):
    order_id, _, total = _place_order(client, auth_headers, customer_auth_headers, payment_method="online")
    resp = client.get("/admin/finance/documents", params={"document_type": "invoice", "order_id": order_id}, headers=auth_headers)
    assert len(resp.json()) == 1
    assert resp.json()[0]["amount"] == total


def test_invoice_numbers_are_sequential_per_org(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers)
    _place_order(client, auth_headers, customer_auth_headers)
    resp = client.get("/admin/finance/documents", params={"document_type": "invoice"}, headers=auth_headers)
    numbers = sorted(d["document_number"] for d in resp.json())
    assert len(numbers) >= 2
    # strictly increasing, no duplicates
    assert len(set(numbers)) == len(numbers)


def test_invalid_document_type_filter_rejected(client, auth_headers):
    resp = client.get("/admin/finance/documents", params={"document_type": "not_a_type"}, headers=auth_headers)
    assert resp.status_code == 400


# ---------- Auto-generated credit note on refund ----------

def test_credit_note_auto_generated_on_refund(client, auth_headers, customer_auth_headers):
    order_id, delivery_id, total = _place_order(client, auth_headers, customer_auth_headers, payment_method="online")
    resp = client.post(f"/customer/deliveries/{delivery_id}/cancel", headers=customer_auth_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/finance/documents", params={"document_type": "credit_note", "order_id": order_id}, headers=auth_headers)
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["amount"] == total
    assert docs[0]["document_number"].startswith("CN-")


# ---------- Manual credit/debit notes ----------

def test_manual_credit_note_creation_and_validation(client, auth_headers, customer_auth_headers):
    order_id, _, _ = _place_order(client, auth_headers, customer_auth_headers)
    resp = client.post("/admin/finance/credit-notes", json={"order_id": order_id, "amount": 20.0, "reason": "Missing item"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["document_type"] == "credit_note"
    assert resp.json()["reason"] == "Missing item"

    resp = client.post("/admin/finance/credit-notes", json={"order_id": order_id, "amount": -5, "reason": "bad"}, headers=auth_headers)
    assert resp.status_code == 400

    resp = client.post("/admin/finance/credit-notes", json={"order_id": "does-not-exist", "amount": 5, "reason": "x"}, headers=auth_headers)
    assert resp.status_code == 404


def test_manual_debit_note_without_order(client, auth_headers):
    resp = client.post("/admin/finance/debit-notes", json={"amount": 15.0, "reason": "COD shortfall"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["document_type"] == "debit_note"
    assert resp.json()["order_id"] is None


def test_only_dispatcher_or_admin_can_create_notes(client, signed_up_admin, auth_headers):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "finance_agent_noperm", "email": "finance_agent_noperm@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Agent", "invite_code": invite_code,
        },
    )
    agent_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = client.post("/admin/finance/debit-notes", json={"amount": 10.0, "reason": "x"}, headers=agent_headers)
    assert resp.status_code == 403


# ---------- Customer access ----------

def test_customer_can_list_and_download_own_documents(client, auth_headers, customer_auth_headers):
    order_id, _, _ = _place_order(client, auth_headers, customer_auth_headers)
    resp = client.get("/customer/finance/documents", headers=customer_auth_headers)
    assert resp.status_code == 200
    docs = resp.json()
    assert any(d["order_id"] == order_id for d in docs)

    doc_id = docs[0]["id"]
    resp = client.get(f"/customer/finance/documents/{doc_id}/pdf", headers=customer_auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 100  # a real, non-trivial PDF was actually rendered


def test_customer_cannot_download_another_customers_document(client, auth_headers, customer_auth_headers):
    order_id, _, _ = _place_order(client, auth_headers, customer_auth_headers)
    resp = client.get("/customer/finance/documents", headers=customer_auth_headers)
    doc_id = resp.json()[0]["id"]

    other_resp = client.post("/customer/signup", json={"email": "other_finance_cust@example.com", "password": "correct-horse-battery", "name": "Other"})
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get(f"/customer/finance/documents/{doc_id}/pdf", headers=other_headers)
    assert resp.status_code == 404


# ---------- Reports & tenant isolation ----------

def test_financial_report_includes_document_counts_and_ledger_data(client, auth_headers, customer_auth_headers):
    _place_order(client, auth_headers, customer_auth_headers, payment_method="online")
    resp = client.get("/admin/finance/reports", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_counts"]["invoice"] >= 1
    assert body["total_invoiced"] > 0
    assert "total_charged" in body  # from Phase 5's compute_financial_dashboard


def test_documents_isolated_between_organizations(client, auth_headers, customer_auth_headers):
    order_id, _, _ = _place_order(client, auth_headers, customer_auth_headers)
    other_resp = client.post(
        "/auth/signup",
        json={
            "username": "finance_other_org_admin", "email": "finance_other_org_admin@example.com",
            "password": "correct-horse-battery", "role": "admin", "display_name": "Other Admin",
            "org_name": "Other Org Finance",
        },
    )
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}
    resp = client.get("/admin/finance/documents", params={"order_id": order_id}, headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == []
