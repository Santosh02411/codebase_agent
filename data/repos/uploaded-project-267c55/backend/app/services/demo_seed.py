"""
Generates (and regenerates) a single, well-known "demo" organization
with realistic sample data — staff, zones, vehicles, and weeks of
varied delivery history — so a visitor can click "Try the Demo" on the
login page and land straight in a fully-populated dispatcher dashboard
with no signup step at all. See routes/auth.py's POST /auth/demo-login
for the endpoint that logs someone into it, and
services/demo_reset_scheduler.py for the periodic reset that keeps it
from staying broken after visitors poke at it.

Design decision, stated plainly rather than left implicit: this is
ONE SHARED sandbox, not a private one per visitor. Every concurrent
demo visitor sees (and can edit) the same organization — the simplest
honest design for a portfolio demo, and it reuses this project's
already-battle-tested multi-tenant isolation (the demo org is isolated
from every REAL organization exactly the same way any two real orgs
are isolated from each other) rather than inventing a second,
parallel per-visitor sandboxing system on top of it. The trade-off —
one visitor's changes are visible to others, and could look "broken"
mid-session — is handled by resetting the whole org back to this
same, deterministic seed on a schedule (see the scheduler), not by
adding complexity here.

Every seeded person's name and email is fictional and clearly
demo-flagged (`@demo.deliverysync.example` addresses) — this only
ever touches its own dedicated, tagged rows (OrganizationDB.is_demo,
CustomerDB emails under the demo domain), never a real
org/user/customer's data. reset_demo_org() is safe to call as many
times as needed (on a fresh empty database, or to blow away and
regenerate an existing demo org) — see that function's own docstring.

Deliberately scoped: this does NOT seed the e-commerce/marketplace
subsystem (products, orders, invoices, subscriptions) or fleet
maintenance/fuel records — those would need a much deeper chain of
realistic data (checkout -> order items -> tax computation ->
invoice) to be worth seeding at all, and the delivery
operations/dispatch experience (the actual core of this project) is
fully represented without them. See mobile/README.md's own precedent
for naming a deliberate scope boundary plainly rather than leaving it
to be discovered.
"""

import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.organization import OrganizationDB
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.delivery_history import DeliveryHistoryDB
from app.models.zone import ZoneDB
from app.models.vehicle import VehicleDB
from app.models.failed_delivery_reason import FailedDeliveryReasonDB
from app.models.sla import SLAPolicyDB
from app.services.auth import hash_password

DEMO_ORG_NAME = "Demo Logistics Co."
DEMO_INVITE_CODE = "DEMO0000"
DEMO_EMAIL_DOMAIN = "demo.deliverysync.example"

# Fixed seed so every reset produces the exact same-looking demo —
# deliberate, not an oversight: a stable, describable demo ("there's
# always an overdue delivery in Zone B") is more useful for a portfolio
# piece than a different random scene every few hours.
_RANDOM_SEED = 20260906

DEMO_AGENTS = [
    ("Ravi Kumar", "ravi"),
    ("Meena Shah", "meena"),
    ("Arjun Nair", "arjun"),
    ("Divya Rao", "divya"),
]
DEMO_CUSTOMERS = [
    ("Priya Sharma", "priya"),
    ("Kabir Singh", "kabir"),
    ("Ananya Iyer", "ananya"),
    ("Rohan Gupta", "rohan"),
]
DEMO_ZONES = [
    ("Zone A - Indiranagar", 12.9784, 77.6408),
    ("Zone B - Koramangala", 12.9352, 77.6245),
    ("Zone C - Whitefield", 12.9698, 77.7500),
]


def _unusable_password_hash() -> str:
    """
    Same pattern as an OAuth-only account (see UserDB's own comment) —
    a securely random value nobody knows and this login flow never
    checks, since /auth/demo-login issues a token directly without a
    password step at all. has_usable_password=False is set alongside
    this for every demo account for the same reason it's set for an
    OAuth-only account: there genuinely isn't a password to change,
    only one to (pointlessly) set.
    """
    return hash_password(uuid.uuid4().hex + uuid.uuid4().hex)


def _clear_existing_demo_org(db: Session) -> None:
    existing = db.query(OrganizationDB).filter(OrganizationDB.is_demo == True).first()  # noqa: E712
    if not existing:
        return
    org_id = existing.id

    user_ids = [u.id for u in db.query(UserDB.id).filter(UserDB.org_id == org_id).all()]
    delivery_ids = [d.id for d in db.query(DeliveryRecordDB.id).filter(DeliveryRecordDB.org_id == org_id).all()]

    if delivery_ids:
        db.query(DeliveryHistoryDB).filter(DeliveryHistoryDB.delivery_id.in_(delivery_ids)).delete(synchronize_session=False)
    db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == org_id).delete(synchronize_session=False)
    db.query(ZoneDB).filter(ZoneDB.org_id == org_id).delete(synchronize_session=False)
    db.query(VehicleDB).filter(VehicleDB.org_id == org_id).delete(synchronize_session=False)
    db.query(FailedDeliveryReasonDB).filter(FailedDeliveryReasonDB.org_id == org_id).delete(synchronize_session=False)
    db.query(SLAPolicyDB).filter(SLAPolicyDB.org_id == org_id).delete(synchronize_session=False)
    if user_ids:
        db.query(UserDB).filter(UserDB.id.in_(user_ids)).delete(synchronize_session=False)
    # CustomerDB has no org_id (see models/customer.py — a customer isn't
    # scoped to one org), so it's identified by the demo-only email
    # domain instead, never touching a real customer's account.
    db.query(CustomerDB).filter(CustomerDB.email.like(f"%@{DEMO_EMAIL_DOMAIN}")).delete(synchronize_session=False)
    db.query(OrganizationDB).filter(OrganizationDB.id == org_id).delete(synchronize_session=False)
    db.commit()


def _compute_sla_status(status: str, expected_by, now: datetime, completed_at: datetime = None) -> str:
    if status in ("pending", "cancelled"):
        return "not_applicable"
    if status == "delivered":
        # Whether a completed delivery met its deadline is a comparison
        # against WHEN IT WAS ACTUALLY DELIVERED (completed_at), not
        # against the current wall-clock time — comparing to "now"
        # would make nearly every delivery from more than a few hours
        # ago read as "missed" regardless of whether it was actually on
        # time, since its deadline is almost always in the past by now.
        return "met" if (not expected_by or not completed_at or completed_at <= expected_by) else "missed"
    if not expected_by:
        return "on_track"
    if expected_by < now:
        return "breached"
    if (expected_by - now) < timedelta(hours=1):
        return "at_risk"
    return "on_track"


def _make_history(db, delivery_id, status_chain, base_time, changed_by_name, changed_by_id):
    """status_chain: list of (status, minutes_after_base) tuples, in order."""
    prev_status = None
    for status, minutes_after in status_chain:
        db.add(DeliveryHistoryDB(
            delivery_id=delivery_id,
            changed_by_user_id=changed_by_id,
            changed_by_display_name=changed_by_name,
            old_status=prev_status,
            new_status=status,
            changed_at=base_time + timedelta(minutes=minutes_after),
            note="Created and assigned" if prev_status is None else None,
        ))
        prev_status = status


def seed_demo_org(db: Session) -> OrganizationDB:
    """
    Wipes and recreates the single demo organization from scratch.
    Idempotent and safe to call anytime — on an empty database (first
    run), or to reset an existing, visitor-modified demo back to its
    known-good state (see services/demo_reset_scheduler.py).
    """
    rng = random.Random(_RANDOM_SEED)
    now = datetime.utcnow()

    _clear_existing_demo_org(db)

    org = OrganizationDB(name=DEMO_ORG_NAME, invite_code=DEMO_INVITE_CODE, is_demo=True)
    db.add(org)
    db.commit()
    db.refresh(org)

    admin = UserDB(
        username="demo_admin", email=f"admin@{DEMO_EMAIL_DOMAIN}",
        hashed_password=_unusable_password_hash(), has_usable_password=False,
        role=UserRole.admin, display_name="Demo Admin", org_id=org.id,
        is_active=True, email_verified=True,
    )
    dispatcher = UserDB(
        username="demo_dispatcher", email=f"dispatcher@{DEMO_EMAIL_DOMAIN}",
        hashed_password=_unusable_password_hash(), has_usable_password=False,
        role=UserRole.dispatcher, display_name="Demo Dispatcher", org_id=org.id,
        is_active=True, email_verified=True,
    )
    db.add(admin)
    db.add(dispatcher)

    agents = []
    for display_name, slug in DEMO_AGENTS:
        agent = UserDB(
            username=f"demo_{slug}", email=f"{slug}@{DEMO_EMAIL_DOMAIN}",
            hashed_password=_unusable_password_hash(), has_usable_password=False,
            role=UserRole.agent, display_name=display_name, org_id=org.id,
            is_active=True, email_verified=True,
        )
        db.add(agent)
        agents.append(agent)
    db.commit()
    for a in agents:
        db.refresh(a)
    db.refresh(admin)
    db.refresh(dispatcher)

    customers = []
    for name, slug in DEMO_CUSTOMERS:
        customer = CustomerDB(
            email=f"{slug}@{DEMO_EMAIL_DOMAIN}", name=name,
            hashed_password=_unusable_password_hash(), has_usable_password=False,
            email_verified=True,
        )
        db.add(customer)
        customers.append(customer)
    db.commit()
    for c in customers:
        db.refresh(c)

    zones = []
    for name, lat, lon in DEMO_ZONES:
        zone = ZoneDB(org_id=org.id, name=name, center_latitude=lat, center_longitude=lon, radius_km=5.0)
        db.add(zone)
        zones.append(zone)

    vehicle_types = ["bike", "bike", "van", "car"]
    for agent, vtype in zip(agents, vehicle_types):
        db.add(VehicleDB(
            org_id=org.id, vehicle_type=vtype,
            registration_number=f"KA-05-{rng.randint(1000, 9999)}",
            capacity_kg=25.0 if vtype == "bike" else 150.0,
            status="in_use", assigned_agent_id=agent.id,
            odometer_km=rng.randint(2000, 40000),
        ))

    reasons = [
        FailedDeliveryReasonDB(org_id=org.id, code="CUSTOMER_UNAVAILABLE", label="Customer unavailable", eligible_for_rto=False),
        FailedDeliveryReasonDB(org_id=org.id, code="WRONG_ADDRESS", label="Wrong or incomplete address", eligible_for_rto=True),
        FailedDeliveryReasonDB(org_id=org.id, code="REFUSED", label="Refused by customer", eligible_for_rto=True),
    ]
    for r in reasons:
        db.add(r)

    db.add(SLAPolicyDB(org_id=org.id, name="Standard 3-hour SLA", target_minutes=180, warning_threshold_percent=80))
    db.commit()

    # ---------- Deliveries: ~45 spread across the last 14 days ----------
    zone_names = [z.name for z in zones]
    customer_contacts = [(c.name, c.email, f"+91 9{rng.randint(100000000, 999999999)}") for c in customers]

    status_weights = [
        (DeliveryStatus.delivered, 26),
        (DeliveryStatus.out_for_delivery, 5),
        (DeliveryStatus.picked_up, 5),
        (DeliveryStatus.pending, 5),
        (DeliveryStatus.failed_attempt, 3),
        (DeliveryStatus.cancelled, 2),
    ]
    statuses_pool = [s for s, w in status_weights for _ in range(w)]

    for i in range(len(statuses_pool)):
        status = statuses_pool[i]
        order_id = f"ORD-{10000 + i}"
        delivery_id = str(uuid.uuid4())
        zone = rng.choice(zone_names)
        agent = None if status == "pending" else rng.choice(agents)
        # Still-open statuses (nothing done with them yet, or actively
        # in progress) skew recent — a "pending" order sitting
        # unassigned for two weeks would look like a forgotten bug, not
        # a believable active queue. Closed-out statuses (delivered,
        # failed, cancelled) spread across the full history window,
        # since that's what two weeks of completed operational history
        # actually looks like.
        if status in (DeliveryStatus.pending, DeliveryStatus.picked_up, DeliveryStatus.out_for_delivery):
            days_ago = rng.choice([0, 0, 0, 1, 1, 2])
        else:
            days_ago = rng.randint(0, 13)
        created_at = now - timedelta(days=days_ago, hours=rng.randint(0, 20))
        use_known_customer = rng.random() < 0.4
        cname, cemail, cphone = rng.choice(customer_contacts) if use_known_customer else (
            f"Customer {i}", f"customer{i}@{DEMO_EMAIL_DOMAIN}", f"+91 9{rng.randint(100000000, 999999999)}"
        )
        matched_customer = next((c for c in customers if c.email == cemail), None) if use_known_customer else None

        expected_by = created_at + timedelta(hours=rng.choice([4, 5, 6, 8]))
        is_partial = status == "delivered" and rng.random() < 0.1

        if status == "delivered":
            # Biased toward completing WITHIN the expected_by window —
            # a demo whose SLA badges are almost all red would tell a
            # worse, less representative story than a normal, mostly-
            # healthy operation with a believable minority of misses.
            on_time = rng.random() < 0.8
            completion_hours = rng.uniform(1, 3) if on_time else rng.uniform(6, 10)
            updated_at = created_at + timedelta(hours=completion_hours)
            chain = [
                (DeliveryStatus.picked_up.value, 5),
                (DeliveryStatus.out_for_delivery.value, rng.randint(20, 60)),
                (DeliveryStatus.delivered.value, rng.randint(80, 200)),
            ]
        elif status == DeliveryStatus.out_for_delivery:
            updated_at = created_at + timedelta(hours=rng.uniform(0.5, 2))
            chain = [(DeliveryStatus.picked_up.value, 5), (DeliveryStatus.out_for_delivery.value, rng.randint(20, 60))]
        elif status == DeliveryStatus.picked_up:
            updated_at = created_at + timedelta(minutes=rng.randint(5, 40))
            chain = [(DeliveryStatus.picked_up.value, 5)]
        elif status == DeliveryStatus.failed_attempt:
            updated_at = created_at + timedelta(hours=rng.uniform(1, 3))
            chain = [
                (DeliveryStatus.picked_up.value, 5),
                (DeliveryStatus.out_for_delivery.value, 30),
                (DeliveryStatus.failed_attempt.value, rng.randint(60, 150)),
            ]
        elif status == DeliveryStatus.cancelled:
            updated_at = created_at + timedelta(minutes=rng.randint(10, 90))
            chain = [(DeliveryStatus.cancelled.value, rng.randint(10, 90))]
            agent = None
        else:  # pending
            updated_at = created_at
            chain = []

        sla_status = _compute_sla_status(
            status.value if hasattr(status, "value") else status, expected_by, now,
            completed_at=(updated_at if status == DeliveryStatus.delivered else None),
        )

        db.add(DeliveryRecordDB(
            id=delivery_id, agent_id=(agent.id if agent else None), order_id=order_id,
            status=status, notes=("Customer requested contactless drop-off" if rng.random() < 0.15 else None),
            created_at=created_at, updated_at=updated_at, zone=zone,
            expected_by=expected_by, org_id=org.id,
            customer_email=cemail, customer_phone=cphone,
            customer_id=(matched_customer.id if matched_customer else None),
            is_partial=is_partial,
            sla_status=sla_status,
            sla_target_at=expected_by,
        ))

        changed_by_name = agent.display_name if agent else dispatcher.display_name
        changed_by_id = agent.id if agent else dispatcher.id
        full_chain = [("pending", 0)] + chain if status != "pending" else [("pending", 0)]
        _make_history(db, delivery_id, full_chain, created_at, changed_by_name, changed_by_id)

    db.commit()
    return org


def get_demo_admin(db: Session) -> UserDB | None:
    org = db.query(OrganizationDB).filter(OrganizationDB.is_demo == True).first()  # noqa: E712
    if not org:
        return None
    return db.query(UserDB).filter(UserDB.org_id == org.id, UserDB.username == "demo_admin").first()
