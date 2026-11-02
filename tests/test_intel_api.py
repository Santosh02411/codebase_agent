import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.retrieval.embeddings import HashingEmbedder
from tests.helpers_poly import write_poly


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    src = tmp_path / "poly"
    write_poly(src)
    c = TestClient(m.app)
    meta = c.post("/repositories", json={"source": str(src), "name": "poly"}).json()
    c.rid, c.main = meta["id"], m
    c.src = m.service().repos_dir / meta["id"]      # re-indexing works on the server's copy, never the original folder
    return c


def test_stats_endpoint_covers_every_requested_metric(api):
    st = api.get(f"/repositories/{api.rid}/stats").json()
    for key in ("files", "languages", "symbols", "dependencies", "tests", "apis", "models", "graph", "indexing", "repo", "parsers"):
        assert key in st
    assert st["files"] == 20 and {"functions", "classes", "methods", "interfaces", "variables"} <= set(st["symbols"])
    assert st["indexing"]["state"] == "ready" and st["indexing"]["last_index"]["mode"] == "full"
    assert st["repo"]["branch"] and st["repo"]["provider"] == "local"


def test_apis_models_and_tests_are_detected_in_a_realistic_app(api, tmp_path):
    d = tmp_path / "app2"
    (d / "backend").mkdir(parents=True)
    (d / "backend/models.py").write_text("from django.db import models\nclass Order(models.Model):\n    total = models.IntegerField()\n    note = models.TextField()\n")
    (d / "backend/api.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.post("/orders")\ndef create(): pass\n@app.get("/orders/{id}")\ndef read(id): pass\n')
    (d / "backend/test_api.py").write_text("def test_create(): pass\ndef test_read(): pass\n")
    (d / "web").mkdir()
    (d / "web/server.js").write_text('const app = require("express")();\napp.get("/health", (req, res) => res.send("ok"));\nmodule.exports = app;\n')
    rid = api.post("/repositories", json={"source": str(d), "name": "app2"}).json()["id"]
    st = api.get(f"/repositories/{rid}/stats").json()
    assert {(a["method"], a["path"]) for a in st["apis"]["items"]} == {("POST", "/orders"), ("GET", "/orders/{id}"), ("GET", "/health")}
    assert st["models"] == [{"name": "Order", "file": "backend/models.py", "line": 2, "framework": "django", "fields": 2}]
    assert st["tests"]["cases"] == 2 and st["tests"]["files"] == 1


def test_symbols_endpoint_includes_all_kinds_and_ids(api):
    syms = api.get(f"/repositories/{api.rid}/symbols", params={"q": "B"}).json()
    assert any(s["kind"] == "class" and s["file"].endswith("B.java") for s in syms)
    one = api.get(f"/repositories/{api.rid}/symbols", params={"path": "web/src/api.ts"}).json()
    assert {"load", "Svc", "Svc.go", "Svc.stop"} <= {s["qualname"] for s in one} and all(s["id"] and s["signature"] for s in one)


def test_symbol_detail_graph_and_impact_endpoints(api):
    sid = "py/app/main.py::handler"
    d = api.get(f"/repositories/{api.rid}/symbol", params={"id": sid}).json()
    assert d["signature"] == "def handler()" and [c["qualname"] for c in d["callers"]] == ["test_it"]
    assert {"calculate", "fmt", "local"} <= {c["qualname"] for c in d["callees"]}
    child = api.get(f"/repositories/{api.rid}/symbol", params={"id": "py/app/main.py::Child"}).json()
    assert [b["qualname"] for b in child["base_symbols"]] == ["Base"]
    assert api.get(f"/repositories/{api.rid}/symbol", params={"id": "nope"}).status_code == 404

    g = api.get(f"/repositories/{api.rid}/graph/calls", params={"symbol": sid, "depth": 1, "direction": "callees"}).json()
    assert {n["id"] for n in g["nodes"]} >= {sid, "py/app/util.py::fmt"} and "py/tests/test_main.py::test_it" not in {n["id"] for n in g["nodes"]}
    assert api.get(f"/repositories/{api.rid}/graph/calls", params={"symbol": "nope"}).status_code == 404

    mod = api.get(f"/repositories/{api.rid}/graph/modules", params={"path": "py/app/util.py"}).json()
    assert "py/app/main.py" in {n["id"] for n in mod["nodes"]}
    assert api.get(f"/repositories/{api.rid}/graph/modules").json()["nodes"]                 # overview
    imp = api.get(f"/repositories/{api.rid}/impact", params={"path": "py/app/util.py"}).json()
    assert imp["tests"] == ["py/tests/test_main.py"]
    assert api.get(f"/repositories/{api.rid}/impact", params={"path": "x.py"}).status_code == 404


def test_reindex_after_edit_reports_incremental_work(api):
    (api.src / "py/app/util.py").write_text("def fmt(x):\n    return str(x) + '!'\n")
    meta = api.post(f"/repositories/{api.rid}/index").json()
    r = meta["last_index"]
    assert r["mode"] == "incremental" and r["files_changed"] == 1 and r["files_unchanged"] == 19 and r["changed_files"] == ["py/app/util.py"]


def test_status_shows_progress_while_indexing_and_blocks_concurrent_runs(api, monkeypatch):
    import app.services as services

    class Slow(HashingEmbedder):
        def embed(self, texts):
            time.sleep(0.15)
            return super().embed(texts)

    (api.src / "py/app/util.py").write_text("def fmt(x):\n    return 'changed'\n")
    svc = api.main.service()
    monkeypatch.setattr(services, "get_embedder", lambda *_: Slow())
    seen, errors = [], []
    t = threading.Thread(target=lambda: svc.reindex(api.rid))
    t.start()
    deadline = time.time() + 5
    while t.is_alive() and time.time() < deadline:
        st = api.get(f"/repositories/{api.rid}/status").json()
        seen.append((st["state"], st.get("phase")))
        if st["state"] == "indexing" and not errors:
            r = api.post(f"/repositories/{api.rid}/index")        # second request while the first is running
            errors.append(r.status_code)
        time.sleep(0.02)
    t.join()
    assert ("indexing", "embedding") in seen or ("indexing", "parsing") in seen
    assert errors == [409]
    assert api.get(f"/repositories/{api.rid}/status").json()["state"] == "ready"
    assert api.get("/repositories/nope/status").status_code == 404


def test_failed_indexing_is_reported_not_swallowed(api, monkeypatch):
    import app.services as services

    class Boom(HashingEmbedder):
        def embed(self, texts):
            raise RuntimeError("embedding service down")

    (api.src / "py/app/util.py").write_text("def fmt(x):\n    return 'again'\n")
    original = services.get_embedder
    monkeypatch.setattr(services, "get_embedder", lambda *_: Boom())
    with pytest.raises(RuntimeError):
        api.main.service().reindex(api.rid)
    st = api.get(f"/repositories/{api.rid}/status").json()
    assert st["state"] == "error" and "embedding service down" in st["error"]
    monkeypatch.setattr(services, "get_embedder", original)
    # the previous good index is still served, and a retry recovers
    assert api.get(f"/repositories/{api.rid}/stats").status_code == 200
    assert api.post(f"/repositories/{api.rid}/index").status_code == 200
    assert api.get(f"/repositories/{api.rid}/status").json()["state"] == "ready"


def test_old_saved_index_is_rebuilt_automatically(api):
    import pickle
    svc = api.main.service()
    path = svc.idx_dir / f"{api.rid}.pkl"
    d = pickle.loads(path.read_bytes())
    d["format"] = 1
    path.write_bytes(pickle.dumps(d))
    svc._cache.clear()
    assert api.get(f"/repositories/{api.rid}/stats").status_code == 200


def test_preview_endpoint_rejects_bad_urls(api):
    assert api.post("/repositories/preview", json={"source": "not a url"}).status_code == 400
    assert api.post("/repositories/preview", json={"source": "file:///etc"}).status_code == 400


def test_branch_and_commit_endpoints(api):
    b = api.get(f"/repositories/{api.rid}/branches").json()
    assert b["current"] and b["branches"][0]["current"]
    log = api.get(f"/repositories/{api.rid}/commits").json()
    assert log and log[0]["subject"].startswith("baseline")
    assert api.post(f"/repositories/{api.rid}/checkout", json={"ref": "nope"}).status_code == 400
    (api.main.service().repos_dir / api.rid / "c/util.h").write_text("int add(int a, int b); // edited\n")
    assert api.post(f"/repositories/{api.rid}/checkout", json={"ref": b["current"]}).status_code == 409   # uncommitted work
    assert api.post(f"/repositories/{api.rid}/fetch", json={}).status_code == 400                          # local copy: no remote
