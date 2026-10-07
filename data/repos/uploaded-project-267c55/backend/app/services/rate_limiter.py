"""
Shared Limiter instance. Defined in its own module (rather than directly
in main.py) so route files can import it and apply @limiter.limit(...) to
individual endpoints without a circular import (main.py imports the route
modules, so the route modules can't import the limiter back from main.py).

Storage backend: defaults to in-memory, which only tracks request counts
within a single running process — fine for this project's single-server
setup, but it would NOT coordinate limits correctly across multiple
server instances behind a load balancer (each instance would enforce its
own separate count). Setting the REDIS_URL environment variable switches
to a Redis-backed store instead, which every instance shares, making
rate limits consistent across a real multi-server deployment. This is
the standard fix for that gap — not implemented as "on" by default only
because it would otherwise require a Redis server to be running just to
start this project locally, which isn't needed for local development.

TESTING=1 turns limiting off entirely (slowapi's own `enabled` flag,
not a homemade bypass): the test suite hits the same endpoints dozens
of times in a loop, well past limits like "5/minute" on signup, and
that's a test-runner artifact, not a real abuse pattern worth
asserting against. The limits themselves ARE tested — see
tests/test_rate_limiting.py, which flips this flag on for just that
one file.
"""

import os
from slowapi import Limiter
from slowapi.util import get_remote_address

redis_url = os.environ.get("REDIS_URL")
_enabled = os.environ.get("TESTING") != "1"

if redis_url:
    limiter = Limiter(key_func=get_remote_address, storage_uri=redis_url, enabled=_enabled)
else:
    limiter = Limiter(key_func=get_remote_address, enabled=_enabled)  # defaults to in-memory storage
