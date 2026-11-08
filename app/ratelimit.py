"""A small per-client rate limit for the endpoints that start agents or run code (the expensive ones). Off unless RATE_LIMIT_PER_MINUTE > 0.
In-memory and per process: enough for one server; put a real gateway in front for a fleet."""
from __future__ import annotations
import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import get_settings

HEAVY_PREFIXES = ("/chat", "/debug", "/generate-fix", "/change", "/generate-tests", "/review", "/architecture", "/agent/stream", "/quality/run", "/github/pr/", "/github/issue/",
                  "/patches/", "/actions/push", "/actions/pull-request", "/actions/review", "/git/commit-message", "/git/pr-description")
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"      # behind a proxy, configure it to set the real client address


def check(key: str, limit: int, now: float | None = None) -> float:
    """0 if the request may proceed, else the seconds until the oldest hit leaves the 60-second window."""
    now = time.time() if now is None else now
    with _lock:
        q = _hits[key]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= limit:
            return max(1.0, 60 - (now - q[0]))
        q.append(now)
        return 0.0


async def middleware(request: Request, call_next):
    limit = get_settings().rate_limit_per_minute
    if limit > 0 and request.method == "POST" and request.url.path.startswith(HEAVY_PREFIXES):
        wait = check(client_key(request), limit)
        if wait:
            return JSONResponse({"detail": f"Too many requests: at most {limit} per minute for this operation. Try again in {int(wait)}s."}, status_code=429, headers={"Retry-After": str(int(wait))})
    return await call_next(request)
