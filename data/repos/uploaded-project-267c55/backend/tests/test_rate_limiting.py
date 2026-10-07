"""
Confirms rate limits actually trigger on abuse-prone public endpoints
(login, signup, the public tracking page).

Every OTHER test file runs with TESTING=1 (set in conftest.py), which
turns slowapi's limiter off entirely — appropriate everywhere else,
since hammering an endpoint in a tight test loop isn't a real abuse
pattern worth tripping over. This file is the deliberate exception: it
flips limiting back on for just these tests, so the limits themselves
are verified somewhere.

Because rate_limiter.py reads TESTING at *import time* (see its
docstring), this file builds its own app import with the flag off,
completely independent of the `client` fixture the rest of the suite
uses.
"""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def rate_limited_client(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-not-for-real-use")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/rate_limit_check.db")

    for mod_name in list(sys.modules):
        if mod_name == "main" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    from app.db.session import Base, get_db

    limited_main = importlib.import_module("main")

    engine = create_engine(
        f"sqlite:///{tmp_path}/rate_limit_check.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    limited_main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(limited_main.app) as test_client:
        yield test_client
    limited_main.app.dependency_overrides.clear()
    engine.dispose()

    monkeypatch.setenv("TESTING", "1")
    for mod_name in list(sys.modules):
        if mod_name == "main" or mod_name.startswith("app."):
            del sys.modules[mod_name]


def test_login_rate_limit_trips_after_repeated_attempts(rate_limited_client):
    # routes/auth.py caps /auth/login at 10/minute.
    last_status = None
    for _ in range(15):
        last_status = rate_limited_client.post(
            "/auth/login", json={"username": "nobody", "password": "wrong"}
        ).status_code
    assert last_status == 429


def test_signup_rate_limit_trips_after_repeated_attempts(rate_limited_client):
    # routes/auth.py caps /auth/signup at 5/minute — the tightest limit
    # in the app, so this is the fastest one to reliably trip.
    last_status = None
    for i in range(8):
        last_status = rate_limited_client.post(
            "/auth/signup",
            json={
                "username": f"spammer{i}",
                "email": f"spammer{i}@example.com",
                "password": "correct-horse-battery",
                "role": "admin",
                "display_name": "Spammer",
                "org_name": f"SpamOrg{i}",
            },
        ).status_code
    assert last_status == 429


def test_public_tracking_rate_limit_trips_after_repeated_attempts(rate_limited_client):
    # routes/tracking.py caps GET /track/{id} at 30/minute.
    last_status = None
    for _ in range(35):
        last_status = rate_limited_client.get("/track/nonexistent-id").status_code
    assert last_status == 429
