"""
Shared pytest fixtures for the whole backend test suite.

Key design decision: every test gets its OWN fresh SQLite database
(a temp file, created and destroyed per test), not the real
backend/database.db used by local dev / the running app. Two reasons:

1. Tests must never touch real data — running the suite locally
   or in CI must not depend on (or corrupt) whatever's already in
   database.db from manual testing.
2. Test isolation — each test starts from a clean, empty schema, so
   tests can't pass or fail depending on what order they ran in or
   what an earlier test left behind.

TESTING=1 is set before any app import happens, because
app/services/rate_limiter.py reads it at *module import time* to
decide whether slowapi's limiter is enabled at all (see that file's
docstring). Importing anything from `app` before this line would
permanently bake rate limiting on for the whole test process.
"""

import os
import uuid

os.environ["TESTING"] = "1"
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-real-use")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, get_db

# Base.metadata only gets populated with a table as each app/models/*.py
# module actually runs its `class FooDB(Base): ...` body — and that only
# happens when something imports that module. `main` (via app/routes/*)
# is what transitively imports every single model module, so it MUST be
# imported at least once before Base.metadata.create_all() is called
# anywhere, or create_all() silently creates zero tables (Base.metadata
# is empty at that point) and every query fails with "no such table".
# Importing it once here, at collection time, guarantees that ordering
# for every test in the suite regardless of which test file runs first.
import main as _main  # noqa: F401  (import is the point, not usage)


@pytest.fixture()
def db_engine(tmp_path):
    """A fresh, file-based SQLite engine per test (in-memory SQLite
    doesn't survive across the multiple connections FastAPI's
    TestClient can open, so a real temp file is used instead)."""
    db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(db_engine):
    """FastAPI TestClient wired to the per-test database via a
    get_db() dependency override, instead of the app's real engine."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Import the app only now (after TESTING=1 is set above) so every
    # module-level config read happens with test settings in place.
    from main import app
    # Re-fetch get_db from app.db.session RIGHT HERE, rather than using
    # the module-level import captured once at collection time above.
    # test_rate_limiting.py's rate_limited_client fixture deliberately
    # deletes `main` and every `app.*` module from sys.modules to force
    # a reimport with rate limiting enabled — and afterward deletes them
    # again so the NEXT test reimports fresh, undoing that. If a test
    # after it in the same session reused the get_db reference captured
    # at collection time, the override below would be keyed to a
    # now-stale function object that the freshly-reimported routes are
    # no longer wired to — silently making the override a no-op and
    # leaking that test's writes into the real default database instead
    # of this fixture's isolated one. Re-importing get_db here, every
    # time, keeps the override correctly matched to whatever `main` is
    # currently loaded, regardless of what ran before it in the session.
    from app.db.session import get_db as current_get_db

    app.dependency_overrides[current_get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def admin_signup_payload():
    """A ready-to-use signup payload that creates a brand new org and
    becomes its admin. Each call gets fresh unique username/email so
    tests can call this fixture-derived helper more than once without
    colliding on uniqueness constraints."""
    name = _unique("admin")
    return {
        "username": name,
        "email": f"{name}@example.com",
        "password": "correct-horse-battery",
        "role": "admin",
        "display_name": "Test Admin",
        "org_name": _unique("Org"),
    }


@pytest.fixture()
def signed_up_admin(client, admin_signup_payload):
    """Signs up a fresh admin/org and returns (token, user, org_invite_code)."""
    resp = client.post("/auth/signup", json=admin_signup_payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {
        "token": body["access_token"],
        "user": body["user"],
        "org_invite_code": body["org_invite_code"],
        "payload": admin_signup_payload,
    }


@pytest.fixture()
def auth_headers(signed_up_admin):
    return {"Authorization": f"Bearer {signed_up_admin['token']}"}


@pytest.fixture()
def customer_signup_payload():
    name = _unique("cust")
    return {
        "email": f"{name}@example.com",
        "password": "correct-horse-battery",
        "name": "Test Customer",
    }


@pytest.fixture()
def signed_up_customer(client, customer_signup_payload):
    resp = client.post("/customer/signup", json=customer_signup_payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {
        "token": body["access_token"],
        "customer": body["customer"],
        "payload": customer_signup_payload,
    }


@pytest.fixture()
def customer_auth_headers(signed_up_customer):
    return {"Authorization": f"Bearer {signed_up_customer['token']}"}
