"""Public, no-login endpoints and app-wide safety behavior: the
no-login tracking page, security headers, and the interactive /docs
explorer being available in dev / hidden in production."""

import importlib
import os


def test_root_health_check(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "running" in resp.json()["message"].lower()


def test_tracking_unknown_delivery_returns_404(client):
    resp = client.get("/track/does-not-exist-12345")
    assert resp.status_code == 404


def test_security_headers_present_on_every_response(client):
    resp = client.get("/")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert "referrer-policy" in resp.headers


def test_docs_available_in_development(client):
    # conftest sets ENVIRONMENT=development by default for the whole suite.
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_docs_hidden_in_production(monkeypatch, tmp_path):
    """Re-imports the app fresh with ENVIRONMENT=production to confirm
    /docs and /redoc are disabled, matching main.py's documented
    behavior. Done as its own isolated import (not the shared `client`
    fixture) since ENVIRONMENT is only read once, at import time."""
    import sys

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-looking-test-secret")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/prod_check.db")

    # Drop every already-imported app module so re-import re-evaluates
    # the ENVIRONMENT-dependent module-level code (docs_url=None, etc.)
    for mod_name in list(sys.modules):
        if mod_name == "main" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    prod_main = importlib.import_module("main")
    from fastapi.testclient import TestClient

    with TestClient(prod_main.app) as prod_client:
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/redoc").status_code == 404

    # Clean up so later tests re-import the normal (dev) app again.
    for mod_name in list(sys.modules):
        if mod_name == "main" or mod_name.startswith("app."):
            del sys.modules[mod_name]
