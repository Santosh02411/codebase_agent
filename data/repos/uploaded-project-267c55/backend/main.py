"""
FastAPI application entry point.

Run with:  uvicorn main:app --reload
Then visit http://127.0.0.1:8000/docs for the interactive Swagger UI —
a genuinely useful thing to show in interviews, since it's auto-generated
from your code.
"""

# THIS MUST RUN BEFORE ANY OTHER LOCAL IMPORT. Several modules below
# (services/email.py, services/sms.py, services/payment.py, services/push.py)
# read config like SMTP_HOST/TWILIO_ACCOUNT_SID/RAZORPAY_KEY_ID as
# MODULE-LEVEL constants — evaluated once, the moment that module is
# first imported. If .env hasn't been loaded into the process
# environment yet at that exact moment, those modules permanently
# capture `None` for every setting, and no amount of the .env file
# being technically present on disk fixes it for the rest of that
# run — env vars only reach os.environ this way, never automatically
# just because a same-named file sits next to the code. Filling in a
# real SMTP_HOST in .env and still seeing "printed instead of sent" in
# the console is exactly what that bug looks like from the outside.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging
import os
import time

from app.db.session import Base, engine
from app.db.migrate import run_lightweight_migrations
from app.services.rate_limiter import limiter
from app.routes import deliveries, sync, auth, users, bulk_import, admin, export, messages, tracking, customer_auth, customer_dashboard, customer_privacy, stores, products, cart, checkout, reviews, coupons, analytics, slots, zones, returns, websockets, subscriptions, failed_delivery_reasons, workforce, pod, sla, warehouse, rbac, reconciliation, customer_messages, rto, scan, route_analytics, notification_templates, fleet, support, finance, webhooks, public_api, advanced_analytics, organization, monitoring
from app.db.session import SessionLocal
from app.services.subscription_scheduler import start_subscription_scheduler
from app.services.sla_monitor import start_sla_monitor
from app.services.reminder_scheduler import start_reminder_scheduler
from app.services import monitoring as monitoring_svc
from app.services.webhook_scheduler import start_webhook_scheduler
from app.services.backup_scheduler import start_backup_scheduler
from app.services.demo_reset_scheduler import start_demo_reset_scheduler
# Create all database tables on startup (if they don't already exist),
# then catch up any EXISTING table to the model's current columns — see
# app/db/migrate.py's module docstring for why both steps are needed:
# create_all() alone only handles brand-new tables, never adds columns
# to ones that already exist from a previous run.
Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine, Base)

# ENVIRONMENT selects a few real, safety-relevant behaviors — not just
# a label. "development" (the default, zero-config) keeps everything
# permissive for local work: the interactive /docs explorer stays on,
# and CORS defaults to allowing any origin if ALLOWED_ORIGINS isn't
# set. "production" tightens both: /docs and /redoc are hidden by
# default (a public API explorer is routinely how people find
# undocumented-but-live endpoints on a real deployment), and an unset
# ALLOWED_ORIGINS is treated as a configuration mistake worth failing
# loudly on rather than silently defaulting to wide-open CORS. See
# services/auth.py for the third piece: refusing to start at all in
# production with the insecure default JWT signing key.
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

app = FastAPI(
    title="Offline-First Delivery Sync API",
    description="Backend for the offline-first delivery status tracking project",
    version="0.1.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

# Rate limiting: protects against brute-force login attempts, signup spam,
# and abuse of the unauthenticated /sync endpoint. Uses in-memory storage
# (no Redis needed) — fine for a single-server deployment; a multi-server
# production deployment would need a shared store (e.g. Redis-backed
# limiter) so limits are enforced consistently across all instances.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allow the React frontend (running on a different port) to call this API.
# NOTE: allow_origins=["*"] combined with allow_credentials=True is rejected
# by browsers (invalid combination per the fetch spec) and causes silent
# "Failed to fetch" errors on the client. Since this app doesn't use
# cookies/sessions, we set allow_credentials=False and can safely allow all
# origins for local development. For a real deployment, set the
# ALLOWED_ORIGINS environment variable to a comma-separated list of exact
# frontend URLs instead of leaving this wide open.
allowed_origins_env = os.environ.get("ALLOWED_ORIGINS")
if allowed_origins_env:
    allowed_origins = allowed_origins_env.split(",")
elif IS_PRODUCTION:
    raise RuntimeError(
        "Refusing to start with ENVIRONMENT=production and no ALLOWED_ORIGINS set. "
        "Defaulting to '*' in production would mean any website can call this API "
        "as the logged-in user. Set ALLOWED_ORIGINS to a comma-separated list of "
        "your real frontend URL(s), e.g. https://app.example.com"
    )
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves uploaded product images back out at /uploads/products/<file>.
# Created on demand by routes/products.py's upload endpoint, so it may
# not exist yet on a completely fresh checkout — create it here too so
# the mount never fails on a clean clone.
UPLOAD_ROOT = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(os.path.join(UPLOAD_ROOT, "products"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_ROOT), name="uploads")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    A few standard, low-risk security headers. These don't replace proper
    hardening (see docs/SECURITY_AND_ACCESS.md for the full list of what's
    still needed before a real public deployment — HTTPS enforcement,
    a production-grade secret key, a shared-store rate limiter, etc.) but
    they're free, safe defaults worth having regardless.

    IMPORTANT — why this wraps call_next in try/except instead of just
    awaiting it directly: `@app.middleware("http")` is Starlette's
    BaseHTTPMiddleware, which runs the rest of the app in a separate
    anyio task inside a task group. If an unhandled exception happens
    deep in a route (see routes/checkout.py's Razorpay call for a real
    example that hit this), that combination can fail to deliver a
    clean 500 JSON response back to the client at all — the browser
    just sees the connection drop, `fetch()` throws a bare TypeError,
    and the frontend (reasonably, but wrongly) reports "you're offline"
    even though the real problem was a backend crash. The individual
    route-level fix is to never let external calls (payment gateways,
    etc.) raise uncaught — but this except clause is the backstop for
    any OTHER unhandled exception anywhere in the app: it guarantees the
    client always gets back a real 500 JSON response instead of a
    dropped connection, so a genuine crash always shows up as a genuine
    error message, never a misleading "offline" one.

    Also doubles as Phase 18's API request-timing hook (services/
    monitoring.py's record_api_request) — one middleware measuring
    every request rather than a second one added just for metrics.
    """
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as error:
        logging.getLogger(__name__).exception("Unhandled exception for %s %s", request.method, request.url.path)
        monitoring_svc.record_api_request(request.method, request.url.path, (time.monotonic() - start) * 1000, 500)
        try:
            db = SessionLocal()
            try:
                monitoring_svc.record_error(db, getattr(request.state, "org_id", None), request.method, request.url.path, error)
            finally:
                db.close()
        except Exception:
            pass  # logging the error must never itself crash the error response below
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    monitoring_svc.record_api_request(request.method, request.url.path, (time.monotonic() - start) * 1000, response.status_code)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

app.include_router(export.router)
app.include_router(deliveries.router)
app.include_router(sync.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(bulk_import.router)
app.include_router(admin.router)
app.include_router(zones.router)
app.include_router(returns.customer_router)
app.include_router(returns.admin_router)
app.include_router(websockets.router)
app.include_router(messages.router)
app.include_router(messages.templates_router)
app.include_router(tracking.router)
app.include_router(customer_auth.router)
app.include_router(customer_dashboard.router)
app.include_router(customer_privacy.router)
app.include_router(stores.router)
app.include_router(products.router)
app.include_router(products.store_router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(reviews.router)
app.include_router(coupons.router)
app.include_router(analytics.router)
app.include_router(slots.router)
app.include_router(subscriptions.router)
app.include_router(failed_delivery_reasons.router)
app.include_router(workforce.router)
app.include_router(pod.router)
app.include_router(sla.router)
app.include_router(warehouse.router)
app.include_router(rbac.router)
app.include_router(reconciliation.router)
app.include_router(customer_messages.router)
app.include_router(rto.router)
app.include_router(scan.router)
app.include_router(route_analytics.router)
app.include_router(notification_templates.router)
app.include_router(fleet.router)
app.include_router(support.customer_router)
app.include_router(support.admin_router)
app.include_router(finance.customer_router)
app.include_router(finance.admin_router)
app.include_router(webhooks.router)
app.include_router(public_api.router)
app.include_router(advanced_analytics.router)
app.include_router(organization.router)
app.include_router(monitoring.router)


# Background task reference kept on app.state so it isn't garbage
# collected mid-run (asyncio only holds a weak reference to a bare
# fire-and-forget task) — see services/subscription_scheduler.py.
@app.on_event("startup")
async def _launch_subscription_scheduler():
    app.state.subscription_scheduler_task = start_subscription_scheduler(SessionLocal)


@app.on_event("startup")
async def _launch_sla_monitor():
    app.state.sla_monitor_task = start_sla_monitor(SessionLocal)


@app.on_event("startup")
async def _launch_reminder_scheduler():
    app.state.reminder_scheduler_task = start_reminder_scheduler(SessionLocal)


@app.on_event("startup")
async def _launch_webhook_scheduler():
    app.state.webhook_scheduler_task = start_webhook_scheduler(SessionLocal)


@app.on_event("startup")
async def _launch_backup_scheduler():
    # Deliberately skipped during the test suite (TESTING=1) — unlike
    # the other schedulers above, a real backup tick does actual file
    # I/O (a full SQLite file copy, or a subprocess pg_dump), and every
    # one of this project's 300+ tests spins up a fresh app instance
    # via TestClient's lifespan handling. Without this guard that would
    # mean hundreds of real backup files written to backend/backups/
    # per test run for no reason — see services/backup_scheduler.py's
    # own module docstring for the same point in more detail.
    if os.environ.get("TESTING") == "1":
        return
    app.state.backup_scheduler_task = start_backup_scheduler(SessionLocal)


@app.on_event("startup")
async def _launch_demo_reset_scheduler():
    # Same reasoning and same guard as _launch_backup_scheduler above —
    # a real reset does real, somewhat expensive database writes
    # (recreating ~46 deliveries and their full history), and this
    # project's 400+ tests each spin up a fresh app instance via
    # TestClient's lifespan handling. See
    # services/demo_reset_scheduler.py's own module docstring.
    if os.environ.get("TESTING") == "1":
        return
    app.state.demo_reset_scheduler_task = start_demo_reset_scheduler(SessionLocal)


@app.get("/")
def root():
    return {"message": "Delivery Sync API is running. Visit /docs for API documentation."}
