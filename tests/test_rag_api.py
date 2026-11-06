import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURE


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import app.main as m
    m._service = None
    m._experiments = None
    c = TestClient(m.app)
    c.rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "fixture"}).json()["id"]
    return c


def wait(api, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = api.get(f"/experiments/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("experiment did not finish")


def test_rag_info_describes_the_configuration(api, monkeypatch):
    info = api.get("/rag/info").json()
    assert info["store"] == "memory" and info["embedding"]["name"] == "hash" and info["embedding"]["dim"] == 512
    assert info["reranker"] == "heuristic" and info["retrieval"]["mode"] == "hybrid" and info["retrieval"]["vector_weight"] == 0.25
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    broken = api.get("/rag/info").json()
    assert "OPENAI_API_KEY" in broken["embedding"]["error"]                    # a missing key is reported, not a 500


def test_datasets_are_listed(api):
    names = {d["name"]: d for d in api.get("/experiments/datasets").json()}
    assert names["delivery_sync"]["questions"] == 12 and names["codebase_agent"]["questions"] == 50 and names["codebase_agent"]["description"]


def test_run_poll_and_browse_an_experiment(api):
    assert api.get("/experiments").json() == []
    job = api.post("/experiments", json={"repo_id": api.rid, "dataset": "delivery_sync"}).json()["job_id"]
    done = wait(api, job)
    assert done["state"] == "done" and done["result_id"]
    listing = api.get("/experiments").json()
    assert len(listing) == 1 and listing[0]["dataset"] == "delivery_sync" and listing[0]["best"]["mrr"] > 0 and listing[0]["configs"] == 4
    res = api.get(f"/experiments/{done['result_id']}").json()
    assert res["repo"] == "fixture" and [c["status"] for c in res["configs"]] == ["ok"] * 4 and not res["label_problems"]


def test_experiment_with_custom_configs_and_skipped_models(api, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = {"repo_id": api.rid, "dataset": "delivery_sync", "embedders": ["hash", "openai:text-embedding-3-small"], "rerankers": ["heuristic"]}
    res = api.get(f"/experiments/{wait(api, api.post('/experiments', json=body).json()['job_id'])['result_id']}").json()
    status = {c["config"]["name"]: c["status"] for c in res["configs"]}
    assert status["hash · hybrid + heuristic"] == "ok" and status["text-embedding-3-small · hybrid"] == "skipped"
    assert "openai:text-embedding-3-small" in res["skipped_embedders"]
    custom = {"repo_id": api.rid, "dataset": "delivery_sync", "configs": [{"name": "kw", "mode": "keyword"}], "ks": [1, 5]}
    r2 = api.get(f"/experiments/{wait(api, api.post('/experiments', json=custom).json()['job_id'])['result_id']}").json()
    assert r2["ks"] == [1, 5] and "recall@5" in r2["configs"][0]["summary"]["symbol"] and "recall@10" not in r2["configs"][0]["summary"]["symbol"]


def test_bad_requests_are_rejected_cleanly(api):
    assert api.post("/experiments", json={"repo_id": api.rid, "dataset": "../../etc/passwd"}).status_code == 400
    assert api.post("/experiments", json={"repo_id": api.rid, "dataset": "nope"}).status_code == 400
    assert api.post("/experiments", json={"repo_id": "missing", "dataset": "delivery_sync"}).status_code == 404
    assert api.post("/experiments", json={"repo_id": api.rid, "dataset": "delivery_sync", "configs": [{"name": "x", "bogus": 1}]}).status_code == 400
    assert api.post("/experiments", json={"repo_id": api.rid, "dataset": "delivery_sync", "use_pgvector": True}).status_code == 400
    assert api.get("/experiments/jobs/nope").status_code == 404 and api.get("/experiments/nope").status_code == 404
    assert api.get("/experiments/..%2F..%2Fsecrets").status_code in (404, 422)


def test_only_one_experiment_runs_at_a_time(api):
    import app.main as m
    first = m.experiments()
    assert first._lock.acquire(blocking=False)                                  # simulate a running job
    try:
        r = api.post("/experiments", json={"repo_id": api.rid, "dataset": "delivery_sync"})
        assert r.status_code == 409 and "already running" in r.json()["detail"]
    finally:
        first._lock.release()
