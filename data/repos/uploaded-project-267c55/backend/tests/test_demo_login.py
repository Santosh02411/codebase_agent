"""
Tests for POST /auth/demo-login and services/demo_seed.py — see that
module's own docstring for the overall design (one shared sandbox org,
reset on a schedule).
"""

from app.services import demo_seed as demo_seed_svc
from app.models.organization import OrganizationDB
from app.models.user import UserDB
from app.models.delivery import DeliveryRecordDB
from app.models.delivery_history import DeliveryHistoryDB
from app.models.customer import CustomerDB
from app.models.zone import ZoneDB
from app.models.vehicle import VehicleDB
from app.models.sla import SLAPolicyDB


# ---------- POST /auth/demo-login ----------

def test_demo_login_returns_a_real_working_session(client):
    resp = client.post("/auth/demo-login")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["username"] == "demo_admin"
    assert body["user"]["role"] == "admin"


def test_demo_login_token_actually_works_against_a_real_endpoint(client):
    body = client.post("/auth/demo-login").json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    resp = client.get("/deliveries/unassigned", headers=headers)
    assert resp.status_code == 200
    # At least one seeded delivery should genuinely be unassigned
    # (status == pending) — a real, populated queue, not an empty one.
    assert len(resp.json()) > 0


def test_demo_login_seeds_on_first_call_and_reuses_after(client, db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    assert db.query(OrganizationDB).filter(OrganizationDB.is_demo == True).count() == 0  # noqa: E712
    db.close()

    first = client.post("/auth/demo-login").json()
    second = client.post("/auth/demo-login").json()

    assert first["user"]["id"] == second["user"]["id"]
    assert first["user"]["org_id"] == second["user"]["org_id"]

    db2 = Session()
    assert db2.query(OrganizationDB).filter(OrganizationDB.is_demo == True).count() == 1
    db2.close()


def test_demo_login_is_not_gated_behind_any_credentials(client):
    # The entire point — no body, no auth header, nothing.
    resp = client.post("/auth/demo-login", json={})
    assert resp.status_code == 200


# ---------- services/demo_seed.py ----------

def test_seed_creates_realistic_populated_org(db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    org = demo_seed_svc.seed_demo_org(db)

    assert org.is_demo is True
    assert org.invite_code == demo_seed_svc.DEMO_INVITE_CODE

    users = db.query(UserDB).filter(UserDB.org_id == org.id).all()
    assert len(users) == 6  # 1 admin + 1 dispatcher + 4 agents
    assert any(u.role.value == "admin" for u in users)
    assert any(u.role.value == "dispatcher" for u in users)
    assert sum(1 for u in users if u.role.value == "agent") == 4
    # Demo accounts have no real usable password — same story as an
    # OAuth-only account (see UserDB's own comment).
    assert all(u.has_usable_password is False for u in users)

    deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == org.id).all()
    assert len(deliveries) > 30
    statuses_present = {d.status.value for d in deliveries}
    # Every status should be represented — this is meant to showcase
    # the full range of the dispatcher dashboard, not just one state.
    assert statuses_present == {"pending", "picked_up", "out_for_delivery", "delivered", "failed_attempt", "cancelled"}

    assert db.query(DeliveryHistoryDB).count() > 0
    assert db.query(ZoneDB).filter(ZoneDB.org_id == org.id).count() == 3
    assert db.query(VehicleDB).filter(VehicleDB.org_id == org.id).count() == 4
    assert db.query(SLAPolicyDB).filter(SLAPolicyDB.org_id == org.id).count() == 1

    customers = db.query(CustomerDB).filter(CustomerDB.email.like(f"%@{demo_seed_svc.DEMO_EMAIL_DOMAIN}")).all()
    assert len(customers) == 4
    assert all(c.has_usable_password is False for c in customers)

    db.close()


def test_seed_is_idempotent_and_fully_replaces_the_old_org(db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    first_org = demo_seed_svc.seed_demo_org(db)
    first_org_id = first_org.id
    first_delivery_count = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == first_org_id).count()
    assert first_delivery_count > 0

    second_org = demo_seed_svc.seed_demo_org(db)

    assert second_org.id != first_org_id
    assert db.query(OrganizationDB).filter(OrganizationDB.id == first_org_id).count() == 0
    assert db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == first_org_id).count() == 0
    assert db.query(OrganizationDB).filter(OrganizationDB.is_demo == True).count() == 1  # noqa: E712

    db.close()


def test_seed_never_touches_a_real_organization(db_engine, client, signed_up_admin):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    real_org_id = signed_up_admin["user"]["org_id"]
    real_user_count_before = db.query(UserDB).filter(UserDB.org_id == real_org_id).count()

    demo_seed_svc.seed_demo_org(db)
    demo_seed_svc.seed_demo_org(db)  # run twice — a real org must survive repeated demo resets too

    real_user_count_after = db.query(UserDB).filter(UserDB.org_id == real_org_id).count()
    assert real_user_count_after == real_user_count_before
    assert db.query(OrganizationDB).filter(OrganizationDB.id == real_org_id).count() == 1

    db.close()


def test_seed_never_touches_a_real_customer_account(db_engine, client, signed_up_customer):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    real_customer_id = signed_up_customer["customer"]["id"]

    demo_seed_svc.seed_demo_org(db)

    still_there = db.query(CustomerDB).filter(CustomerDB.id == real_customer_id).first()
    assert still_there is not None

    db.close()


def test_get_demo_admin_returns_none_when_no_demo_org_exists(db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    assert demo_seed_svc.get_demo_admin(db) is None
    db.close()


def test_delivered_orders_mostly_meet_their_sla_not_mostly_miss_it(db_engine):
    # Regression test for a real bug caught while building this:
    # comparing a delivered order's deadline against the CURRENT time
    # (rather than against when it was actually delivered) made nearly
    # every historical delivery read as "missed" regardless of whether
    # it was actually on time — see docs/PROJECT_WORKFLOW.md's entry
    # on this. A healthy demo should show mostly "met", not mostly
    # "missed"/"breached".
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    org = demo_seed_svc.seed_demo_org(db)
    delivered = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == org.id, DeliveryRecordDB.status == "delivered"
    ).all()

    met_count = sum(1 for d in delivered if d.sla_status == "met")
    assert met_count > len(delivered) / 2

    db.close()
