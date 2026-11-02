"""GitHub OAuth (web flow) and a tiny single-user token store.

This server is designed for one person running it locally: the OAuth token is kept in `data/auth.json` (mode 0600)
and is never sent to the browser. Do not expose the API to a network without adding real user accounts first."""
from __future__ import annotations
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .config import Settings

AUTHORIZE = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
_STATES: dict[str, float] = {}
_LOCK = threading.Lock()


def _client() -> httpx.Client:  # tests replace this with a MockTransport client
    return httpx.Client(timeout=20)


class AuthStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "auth.json"

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, provider: str) -> dict | None:
        return self._read().get(provider)

    def token(self, provider: str) -> str | None:
        return (self.get(provider) or {}).get("token")

    def set(self, provider: str, data: dict) -> None:
        d = self._read()
        d[provider] = data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def delete(self, provider: str) -> None:
        d = self._read()
        if d.pop(provider, None) is not None:
            self.path.write_text(json.dumps(d))


def oauth_configured(s: Settings) -> bool:
    return bool(s.github_client_id and s.github_client_secret)


def redirect_uri(s: Settings) -> str:
    return f"{s.oauth_redirect_base}/auth/github/callback"


def login_url(s: Settings) -> str:
    if not oauth_configured(s):
        raise ValueError("GitHub OAuth isn't configured: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env")
    state = secrets.token_urlsafe(24)
    with _LOCK:
        now = time.time()
        for k in [k for k, t in _STATES.items() if now - t > 600]:
            del _STATES[k]
        _STATES[state] = now
    return AUTHORIZE + "?" + urlencode({"client_id": s.github_client_id, "redirect_uri": redirect_uri(s), "scope": s.github_scope, "state": state})


def consume_state(state: str) -> bool:
    with _LOCK:
        t = _STATES.pop(state, None)
    return t is not None and time.time() - t < 600


def exchange_code(s: Settings, code: str) -> str:
    with _client() as c:
        r = c.post(TOKEN_URL, headers={"Accept": "application/json"},
                   data={"client_id": s.github_client_id, "client_secret": s.github_client_secret, "code": code, "redirect_uri": redirect_uri(s)})
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "access_token" not in data:
        raise ValueError(data.get("error_description") or data.get("error") or "GitHub did not return a token")
    return data["access_token"]


def _gh(c: httpx.Client, token: str, path: str, **params):
    r = c.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, params=params)
    if r.status_code == 401:
        raise PermissionError("GitHub rejected the saved token — reconnect GitHub")
    if r.status_code >= 400:
        raise ValueError(f"GitHub {r.status_code}: {r.json().get('message', 'request failed') if r.content else ''}")
    return r.json()


def fetch_user(token: str) -> dict:
    with _client() as c:
        u = _gh(c, token, "/user")
    return {"login": u.get("login", ""), "name": u.get("name") or "", "avatar": u.get("avatar_url", "")}


def list_repos(token: str, q: str = "", page: int = 1) -> list[dict]:
    with _client() as c:
        items = _gh(c, token, "/user/repos", per_page=100, page=page, sort="pushed",
                    affiliation="owner,collaborator,organization_member")
    out = [{"full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch", ""),
            "url": r["html_url"], "description": r.get("description") or "", "updated_at": r.get("pushed_at") or r.get("updated_at", ""),
            "language": r.get("language") or ""} for r in items]
    needle = q.strip().lower()
    return [r for r in out if needle in r["full_name"].lower() or needle in r["description"].lower()] if needle else out
