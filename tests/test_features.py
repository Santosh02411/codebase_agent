import httpx
import pytest
from fastapi.testclient import TestClient

from app import features, github_pr
from tests.conftest import FIXTURE
from tests.helpers import FIX_SCRIPT, ScriptedLLM

EDIT = {k: FIX_SCRIPT["generate_fix"][k] for k in ("file", "search", "replace")}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "delivery-sync"}).json()["id"]
    return c, m, rid


def test_architecture_works_offline(client):
    c, _, rid = client
    r = c.post("/architecture", json={"repo_id": rid}).json()
    assert "services" in r["facts"]["folders"] and "services" in r["answer"]


def test_review_static_and_ai_findings(client, monkeypatch):
    c, m, rid = client
    code = "def f(x=[]):\n    try:\n        eval(x)\n    except:\n        pass\n"
    msgs = {f["message"] for f in features.static_checks("a.py", code)}
    assert any("mutable default" in x for x in msgs) and any("Bare" in x for x in msgs) and any("eval" in x for x in msgs)
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM({"review": {"summary": "ok", "findings": [
        {"file": "auth.py", "line": 3, "severity": "high", "message": "weak check"}]}}))
    r = c.post("/review", json={"repo_id": rid}).json()
    assert r["summary"] == "ok" and any(f["source"] == "ai" and f["severity"] == "high" for f in r["findings"])


def test_multi_file_change_verified_then_applied(client, monkeypatch):
    c, m, rid = client
    bad = {"edits": [{"file": "services/eta.py", "search": "does not exist", "replace": "x"}], "new_files": []}
    good = {"edits": [EDIT], "new_files": [{"path": "docs/CHANGES.md", "content": "eta defaults speed\n"}], "explanation": "default speed"}
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM({"generate_change": [bad, good]}))
    r = c.post("/change", json={"repo_id": rid, "request": "default the delivery speed"}).json()
    assert r["status"] == "verified" and r["test_before"]["status"] == "failed" and r["test_after"]["status"] == "passed"
    assert r["files"] == ["services/eta.py", "docs/CHANGES.md"] and "/dev/null" in r["diff"]
    assert any("rejected" in s["message"] for s in r["steps"])
    assert c.post("/apply-changes", json={"repo_id": rid, "edits": r["edits"], "new_files": r["new_files"]}).status_code == 200
    assert c.post("/run-tests", json={"repo_id": rid}).json()["status"] == "passed"
    # the same change can't be applied twice (the new file now exists)
    assert c.post("/apply-changes", json={"repo_id": rid, "edits": [], "new_files": r["new_files"]}).status_code == 400


def test_mock_llm_change_is_a_clean_no_change(client):
    c, _, rid = client
    assert c.post("/change", json={"repo_id": rid, "request": "add a feature"}).json()["status"] == "no_change"


def test_generate_tests_adds_one_file(client, monkeypatch):
    c, m, rid = client
    script = {"generate_tests": {"edits": [], "new_files": [{"path": "tests/test_extra.py", "content": "def test_ok():\n    assert 1 + 1 == 2\n"}], "explanation": "basic"}}
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM(script))
    r = c.post("/generate-tests", json={"repo_id": rid, "target": "services/eta.py", "verify": False}).json()
    assert r["status"] == "unverified" and r["files"] == ["tests/test_extra.py"]


def test_path_traversal_in_changes_is_blocked(client):
    c, _, rid = client
    r = c.post("/apply-changes", json={"repo_id": rid, "new_files": [{"path": "../evil.py", "content": "x"}]})
    assert r.status_code == 400


def test_pull_request_flow_with_mocked_github():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        p = req.url.path
        if req.method == "GET" and p == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if req.method == "GET" and "/contents/" in p:
            return httpx.Response(404, json={"message": "Not Found"})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7", "number": 7})
        return httpx.Response(201, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = github_pr.create_pr("https://github.com/o/r", "tok", {"a.py": "x=1\n"}, "Fix", client=client)
    assert r["url"].endswith("/pull/7") and r["branch"].startswith("agent/change-")
    assert ("PUT", "/repos/o/r/contents/a.py") in calls
    with pytest.raises(ValueError):
        github_pr.create_pr("https://github.com/o/r", "", {"a": "b"}, "t", client=client)
    with pytest.raises(ValueError):
        github_pr.parse_repo("/local/path")


def test_pr_endpoint_requires_confirm_and_token(client):
    c, _, rid = client
    body = {"repo_id": rid, "files": {"a.py": "x"}, "title": "t"}
    assert c.post("/create-pr", json=body).status_code == 400
    assert "confirm" in c.post("/create-pr", json=body).json()["detail"]
    assert c.post("/create-pr", json={**body, "confirm": True}).status_code == 400  # local project, no token
