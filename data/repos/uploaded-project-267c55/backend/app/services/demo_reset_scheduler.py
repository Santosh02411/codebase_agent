"""
Periodically resets the shared demo organization back to its known-good
seeded state — see services/demo_seed.py's own module docstring for why
this is a single SHARED sandbox rather than a private one per visitor,
and why that design choice is what makes this scheduler necessary: a
visitor exploring the demo can (and should be able to) freely reassign
deliveries, mark things delivered, edit settings — genuinely try the
product — and none of that should require read-only restrictions that
would defeat the whole point of a hands-on demo. This scheduler is
what "undoes" that afterward, on a fixed interval, rather than the
demo slowly degrading into a confusing mess for the next visitor.

Same interval-loop shape as services/reminder_scheduler.py /
services/backup_scheduler.py. Deliberately NOT started during the test
suite (see main.py's _launch_demo_reset_scheduler) — same reasoning as
the backup scheduler: a real reset does real, somewhat expensive
database writes (recreating ~46 deliveries and their full history),
and every one of this project's 400+ tests spins up a fresh app
instance via TestClient's lifespan handling.
"""

import asyncio
import logging
import os
import time

from app.services import demo_seed as demo_seed_svc
from app.services import monitoring as monitoring_svc

logger = logging.getLogger(__name__)

DEMO_RESET_INTERVAL_SECONDS = int(os.environ.get("DEMO_RESET_INTERVAL_HOURS", "6")) * 3600


async def _demo_reset_loop(session_factory):
    while True:
        await asyncio.sleep(DEMO_RESET_INTERVAL_SECONDS)
        start = time.monotonic()
        db = session_factory()
        try:
            demo_seed_svc.seed_demo_org(db)
            logger.info("Demo organization reset to its seeded state.")
            monitoring_svc.record_job_heartbeat(db, "demo_reset_scheduler", "success", int((time.monotonic() - start) * 1000))
        except Exception as error:
            logger.exception("Demo reset failed")
            try:
                monitoring_svc.record_job_heartbeat(db, "demo_reset_scheduler", "error", int((time.monotonic() - start) * 1000), str(error)[:500])
            except Exception:
                pass
        finally:
            db.close()


def start_demo_reset_scheduler(session_factory) -> asyncio.Task:
    return asyncio.create_task(_demo_reset_loop(session_factory))
