import json

import pytest
from fastapi.testclient import TestClient
from tests.conftest import FIXTURE
from tests.helpers import FIX_SCRIPT, ScriptedLLM


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "ds"}).json()["id"]
    return c, m, rid


def events(resp):
    return [json.loads(l[6:]) for l in resp.text.splitlines() if l.startswith("data: ")]


def test_symbols_and_grep(client):
    c, _, rid = client
    syms = c.get(f"/repositories/{rid}/symbols", params={"path": "services/eta.py"}).json()
    assert any(s["name"] == "calculate_delivery_eta" and s["start"] >= 1 for s in syms)
    assert any(s["file"] == "services/eta.py" for s in c.get(f"/repositories/{rid}/symbols", params={"q": "eta"}).json())
    g = c.get(f"/repositories/{rid}/grep", params={"q": "speed_kmh"}).json()
    assert g["files"] >= 1 and g["matches"][0]["line"] >= 1
    assert c.get(f"/repositories/{rid}/grep", params={"q": "(", "regex": True}).status_code == 400


def test_git_flow_after_apply(client):
    c, _, rid = client
    assert c.get(f"/repositories/{rid}/git/status").json()["files"] == []
    r = c.post("/apply-changes", json={"repo_id": rid, "edits": [{"file": "auth.py", "search": "def ", "replace": "def "}],
                                       "new_files": [{"path": "notes.txt", "content": "hi\n"}]})
    assert r.status_code == 200, r.text
    st = c.get(f"/repositories/{rid}/git/status").json()
    assert {f["path"]: f["status"] for f in st["files"]} == {"notes.txt": "untracked"}
    v = c.get(f"/repositories/{rid}/git/file", params={"path": "notes.txt"}).json()
    assert v["is_new"] and v["modified"] == "hi\n"
    assert c.post("/git/discard", json={"repo_id": rid, "path": "notes.txt"}).json()["files"] == []
    assert c.get(f"/repositories/{rid}/git/file", params={"path": "../x"}).status_code == 400


def test_terminal_is_restricted(client):
    c, _, rid = client
    run = lambda cmd: c.post("/terminal/exec", json={"repo_id": rid, "command": cmd}).json()
    assert "auth.py" in run("ls")["output"]
    assert "authenticate_user" in run("cat auth.py")["output"]
    assert run("grep speed_kmh")["exit_code"] == 0
    assert run("git status")["exit_code"] == 0
    assert run("rm -rf /")["exit_code"] == 127
    assert run("cat ../../etc/passwd")["exit_code"] == 1
    assert run("git diff --output=x")["exit_code"] == 2
    assert run("pytest --rootdir=/")["exit_code"] == 2


def test_agent_stream_emits_live_events_then_result(client, monkeypatch):
    c, m, rid = client
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM(FIX_SCRIPT))
    resp = c.post("/agent/stream", json={"repo_id": rid, "mode": "debug", "text": "500 error creating delivery"})
    ev = events(resp)
    types = [e["type"] for e in ev]
    assert types[0] == "run_start" and types[-1] == "result"
    assert {"node", "tool", "llm", "step"} <= set(types)
    assert [e["seq"] for e in ev] == sorted(e["seq"] for e in ev)
    assert ev[-1]["data"]["status"] == "fix_verified"


def test_agent_stream_review_replays_steps_and_errors_are_events(client, monkeypatch):
    c, m, rid = client
    ev = events(c.post("/agent/stream", json={"repo_id": rid, "mode": "review"}))
    assert ev[-1]["type"] == "result" and any(e["type"] == "step" for e in ev)
    ev = events(c.post("/agent/stream", json={"repo_id": rid, "mode": "chat", "text": "x", "provider": "nope"}))
    assert ev[-1]["type"] == "error"


def test_save_file_updates_copy_index_and_git(client):
    c, _, rid = client
    new = "def authenticate_user(u, p):\n    return True\n"
    assert c.put(f"/repositories/{rid}/file", json={"path": "auth.py", "text": new}).status_code == 200
    assert c.get(f"/repositories/{rid}/file", params={"path": "auth.py"}).json()["text"] == new
    assert [f["path"] for f in c.get(f"/repositories/{rid}/git/status").json()["files"]] == ["auth.py"]
    assert c.put(f"/repositories/{rid}/file", json={"path": "../evil.py", "text": "x"}).status_code == 400
    assert c.put(f"/repositories/{rid}/file", json={"path": "nope.py", "text": "x"}).status_code == 400
