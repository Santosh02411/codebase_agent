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
    return TestClient(m.app), m


def _add(c):
    r = c.post("/repositories", json={"source": str(FIXTURE), "name": "delivery-sync"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_repo_lifecycle_search_and_chat(client):
    c, _ = client
    rid = _add(c)
    assert c.get("/repositories").json()[0]["id"] == rid
    assert "auth.py" in c.get(f"/repositories/{rid}/tree").json()["files"]
    assert c.post("/search", json={"repo_id": rid, "query": "authenticate_user", "k": 2}).json()[0]["file"] == "auth.py"
    r = c.post("/chat", json={"repo_id": rid, "question": "Where is authentication implemented?"}).json()
    assert r["llm"] == "mock" and "auth.py" in r["answer"]
    assert c.get(f"/runs/{r['run_id']}").status_code == 200


def test_debug_apply_patch_and_run_tests(client, monkeypatch):
    c, m = client
    rid = _add(c)
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM(FIX_SCRIPT))
    r = c.post("/debug", json={"repo_id": rid, "question": "500 error creating delivery"}).json()
    assert r["status"] == "fix_verified" and r["test_before"]["status"] == "failed"
    assert c.post("/run-tests", json={"repo_id": rid}).json()["status"] == "failed"
    assert c.post("/apply-patch", json={"repo_id": rid, **{k: r["patch"][k] for k in ("file", "search", "replace")}}).status_code == 200
    assert c.post("/run-tests", json={"repo_id": rid}).json()["status"] == "passed"


def test_errors(client):
    c, _ = client
    assert c.post("/chat", json={"repo_id": "nope", "question": "x"}).status_code == 404
    assert c.post("/repositories", json={"source": "ftp://x"}).status_code == 400
    assert c.post("/repositories", json={"source": "https://github.com/a/b;rm"}).status_code == 400


def test_local_paths_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.delenv("ALLOW_LOCAL_PATHS", raising=False)
    import app.main as m
    m._service = None
    assert TestClient(m.app).post("/repositories", json={"source": str(FIXTURE)}).status_code == 400
