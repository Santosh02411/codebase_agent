import base64
import json
import os
import stat
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, github_pr


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        url = str(req.url)
        if url.startswith(auth.TOKEN_URL):
            form = parse_qs(req.content.decode())
            if form.get("code") == ["good"] and form.get("client_secret") == ["csecret"]:
                return httpx.Response(200, json={"access_token": "gho_tok", "token_type": "bearer"})
            return httpx.Response(200, json={"error": "bad_verification_code", "error_description": "The code passed is incorrect"})
        if req.headers.get("authorization") != "Bearer gho_tok":
            return httpx.Response(401, json={"message": "Bad credentials"})
        if url.startswith(f"{auth.API}/user/repos"):
            return httpx.Response(200, json=[
                {"full_name": "me/private-app", "private": True, "default_branch": "develop", "html_url": "https://github.com/me/private-app",
                 "description": "secret sauce", "pushed_at": "2026-01-02T00:00:00Z", "language": "Python"},
                {"full_name": "org/website", "private": False, "default_branch": "main", "html_url": "https://github.com/org/website",
                 "description": None, "pushed_at": "2025-01-01T00:00:00Z", "language": "TypeScript"}])
        if url == f"{auth.API}/user":
            return httpx.Response(200, json={"login": "octo", "name": "Octo Cat", "avatar_url": "https://a/x.png"})
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(auth, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    import app.main as m
    m._service = None
    c = TestClient(m.app, follow_redirects=False)
    c.calls = calls
    c.main = m
    return c


def connect(c):
    loc = c.get("/auth/github/login").headers["location"]
    state = parse_qs(urlparse(loc).query)["state"][0]
    return c.get("/auth/github/callback", params={"code": "good", "state": state})


def test_login_redirects_to_github_with_state_and_scope(client):
    r = client.get("/auth/github/login")
    assert r.status_code == 307
    u = urlparse(r.headers["location"])
    q = parse_qs(u.query)
    assert u.netloc == "github.com" and u.path == "/login/oauth/authorize"
    assert q["client_id"] == ["cid"] and q["scope"] == ["repo read:user"] and len(q["state"][0]) >= 20
    assert q["redirect_uri"] == ["http://localhost:8000/auth/github/callback"]


def test_callback_stores_token_privately_and_never_returns_it(client, tmp_path):
    r = connect(client)
    assert r.status_code == 307 and r.headers["location"] == "http://localhost:3000/?connected=github"
    path = tmp_path / "data" / "auth.json"
    assert json.loads(path.read_text())["github"]["token"] == "gho_tok"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    st = client.get("/auth/status")
    assert st.json()["github"]["connected"] and st.json()["github"]["user"]["login"] == "octo"
    assert "gho_tok" not in st.text and "gho_tok" not in client.get("/health").text
    assert client.get("/health").json()["github_configured"] is True


def test_callback_rejects_bad_state_replays_and_provider_errors(client):
    assert "auth_error=invalid_or_expired_state" in client.get("/auth/github/callback", params={"code": "good", "state": "forged"}).headers["location"]
    loc = client.get("/auth/github/login").headers["location"]
    state = parse_qs(urlparse(loc).query)["state"][0]
    assert client.get("/auth/github/callback", params={"code": "good", "state": state}).headers["location"].endswith("connected=github")
    assert "invalid_or_expired_state" in client.get("/auth/github/callback", params={"code": "good", "state": state}).headers["location"]   # one-time
    loc = client.get("/auth/github/login").headers["location"]
    state = parse_qs(urlparse(loc).query)["state"][0]
    assert "auth_error=" in client.get("/auth/github/callback", params={"code": "WRONG", "state": state}).headers["location"]
    assert "auth_error=access_denied" in client.get("/auth/github/callback", params={"error": "access_denied"}).headers["location"]


def test_unconfigured_oauth_explains_itself(client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "")
    r = client.get("/auth/github/login")
    assert "auth_error=GitHub%20OAuth" in r.headers["location"] or "auth_error=GitHub OAuth" in r.headers["location"]
    assert client.get("/auth/status").json()["github"]["oauth_configured"] is False


def test_repo_picker_search_and_disconnect(client):
    assert client.get("/github/repos").status_code == 401                 # not connected
    connect(client)
    repos = client.get("/github/repos").json()
    assert [r["full_name"] for r in repos] == ["me/private-app", "org/website"]
    assert repos[0]["private"] and repos[0]["default_branch"] == "develop"
    assert [r["full_name"] for r in client.get("/github/repos", params={"q": "sauce"}).json()] == ["me/private-app"]
    assert client.post("/auth/github/logout").json() == {"connected": False}
    assert client.get("/github/repos").status_code == 401
    assert client.get("/auth/status").json()["github"]["connected"] is False


def test_revoked_token_is_forgotten(client):
    connect(client)
    client.main.service().auth.set("github", {"token": "revoked", "login": "octo"})
    assert client.get("/github/repos").status_code == 401
    assert client.main.service().auth.token("github") is None


def test_oauth_token_is_used_for_clone_and_pull_requests(client, monkeypatch):
    connect(client)
    header = client.main.service()._header_for("https://github.com/me/private-app")
    assert header.startswith("Authorization: Basic ")
    assert base64.b64decode(header.split()[-1]).decode() == "x-access-token:gho_tok"
    assert client.main.service()._header_for("https://gitlab.com/g/r") is None     # tokens are never sent to other hosts

    seen = {}
    monkeypatch.setattr(github_pr, "create_pr", lambda source, token, files, title, body: seen.update(token=token) or {"url": "u", "number": 1, "branch": "b"})
    repo_dir = client.main.service().repos_dir / "x"
    repo_dir.mkdir(parents=True)
    (repo_dir / "a.py").write_text("x = 1\n")
    client.main.service().auth  # noqa: B018
    meta = {"x": {"id": "x", "name": "x", "source": "https://github.com/me/private-app", "files": 1, "chunks": 1, "embedder": "hash"}}
    client.main.service()._save_meta(meta)
    client.main.service().reindex("x")
    r = client.post("/create-pr", json={"repo_id": "x", "files": {"a.py": "x = 2\n"}, "title": "t", "confirm": True})
    assert r.status_code == 200 and seen["token"] == "gho_tok"
