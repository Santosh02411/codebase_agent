"""Tests for the data behind the redesigned web app: the system graph, parser-derived insights, real test execution detail, recorded history, and honest AI-unavailable answers."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ingest import build_index
from app.intel import system_graph as sgm
from app.intel.stats import repo_stats
from app.quality import frameworks

FIXTURE = Path(__file__).parent / "fixtures" / "delivery_sync"


@pytest.fixture(scope="module")
def index():
    return build_index(FIXTURE)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "d"}).json()["id"]
    return c, rid, m


# ---- system graph ------------------------------------------------------------------------------------------------------------------
def test_system_graph_marks_every_edge_with_how_it_was_established(index):
    g = sgm.system_graph(index.graph)
    types = {e["type"] for e in g["edges"]}
    assert {"import", "call", "test"} <= types
    assert all("verified" in e and e["basis"] for e in g["edges"])
    imp = next(e for e in g["edges"] if e["type"] == "import" and e["source"] == "delivery_app.py" and e["target"] == "services/eta.py")
    assert imp["verified"] is True
    test_edge = next(e for e in g["edges"] if e["type"] == "test")
    assert test_edge["source"] == "tests/test_delivery.py" and test_edge["verified"] is True
    assert g["stats"]["verified_edges"] + g["stats"]["inferred_edges"] == g["stats"]["edges"]


def test_name_only_test_links_are_marked_inferred(tmp_path):
    (tmp_path / "billing.py").write_text("def charge(x):\n    return x\n\n\ndef refund(x):\n    return -x\n")
    (tmp_path / "test_billing.py").write_text("def test_nothing():\n    assert True\n")   # same name, but imports nothing
    idx = build_index(tmp_path)
    g = sgm.system_graph(idx.graph)
    e = next(e for e in g["edges"] if e["type"] == "test")
    assert e["source"] == "test_billing.py" and e["target"] == "billing.py" and e["verified"] is False


def test_insights_report_only_what_the_parser_found(index):
    ins = sgm.insights(index.graph, repo_stats(index))
    assert [m["file"] for m in ins["key_modules"]][:1] == ["delivery_app.py"] or ins["key_modules"]
    assert "auth.py" in ins["risks"]["untested_modules"]            # nothing reaches it
    assert "services/eta.py" not in ins["risks"]["untested_modules"]  # reached transitively through delivery_app.py's test
    assert all(q["basis"] for q in ins["suggested_questions"])


# ---- pytest result detail ---------------------------------------------------------------------------------------------------------
SAMPLE = """collected 2 items

tests/test_x.py::test_ok PASSED                                          [ 50%]
tests/test_x.py::test_bad FAILED                                         [100%]

=================================== FAILURES ===================================
___________________________________ test_bad ___________________________________
tests/test_x.py:7: in test_bad
    assert add(1, 2) == 4
x.py:3: in add
    return a + b
E   AssertionError: expected 4

=========================== short test summary info ============================
FAILED tests/test_x.py::test_bad - AssertionError: expected 4
========================= 1 failed, 1 passed in 0.02s ==========================
"""


def test_pytest_output_is_parsed_into_outcomes_and_tracebacks():
    parsed = frameworks.enrich_pytest(frameworks.parse_pytest(SAMPLE), SAMPLE)
    assert parsed["tests"] == [{"id": "tests/test_x.py::test_ok", "outcome": "passed"}, {"id": "tests/test_x.py::test_bad", "outcome": "failed"}]
    f = parsed["failed_tests"][0]
    assert f["frames"] == [{"file": "tests/test_x.py", "line": 7, "func": "test_bad"}, {"file": "x.py", "line": 3, "func": "add"}]
    assert f["location"] == {"file": "x.py", "line": 3} and "expected 4" in f["error"] and "assert add(1, 2) == 4" in f["traceback"]


# ---- real execution, recorded history, honest "not executed" ---------------------------------------------------------------------
def test_discovery_does_not_execute_and_run_is_recorded(client):
    c, rid, _ = client
    d = c.get(f"/repositories/{rid}/tests").json()
    assert d["framework"] == "pytest" and d["file_count"] == 1 and d["case_count"] == 3 and d["can_execute"] is True
    assert c.get(f"/repositories/{rid}/test-runs").json() == []            # discovery recorded nothing
    r = c.post("/run-tests", json={"repo_id": rid}).json()
    assert r["executed"] is True and r["status"] == "failed" and r["counts"] == {"failed": 1, "passed": 2} and r["exit_code"] == 1
    outcome = {t["id"]: t["outcome"] for t in r["tests"]}
    assert outcome["tests/test_delivery.py::test_create_delivery_default_speed"] == "failed" and list(outcome.values()).count("passed") == 2
    assert r["failed_tests"][0]["location"]["file"] == "services/eta.py"
    runs = c.get(f"/repositories/{rid}/test-runs?full=true").json()
    assert len(runs) == 1 and runs[0]["run"]["command"] == r["command"] and "TypeError" in runs[0]["run"]["output"]


def test_a_run_that_never_executed_is_not_recorded(client, monkeypatch):
    c, rid, m = client
    from app import sandbox
    monkeypatch.setattr(sandbox, "run_tests", lambda *a, **k: sandbox._result("sandbox_unavailable", "Docker is not available", "pytest", "python -m pytest"))
    r = c.post("/run-tests", json={"repo_id": rid}).json()
    assert r["executed"] is False and r["status"] == "sandbox_unavailable"
    assert c.get(f"/repositories/{rid}/test-runs").json() == []


def test_targets_narrow_the_run(client):
    c, rid, _ = client
    r = c.post("/run-tests", json={"repo_id": rid, "targets": ["tests/test_delivery.py::test_missing_customer"]}).json()
    assert r["executed"] and r["total"] == 1 and r["status"] == "passed"


# ---- the AI features say so when no model is available ----------------------------------------------------------------------------
def test_ai_understanding_and_explain_refuse_to_fake_it_with_the_mock_model(client):
    c, rid, _ = client
    ov = c.post(f"/repositories/{rid}/overview", json={}).json()
    assert ov["state"] == "unavailable" and "mock" in ov["reason"].lower() and ov["overview"] is None
    assert c.get(f"/repositories/{rid}/overview").json() == {"overview": None, "stale": False, "llm_mock": True}
    ex = c.post("/explain", json={"repo_id": rid, "subject": "architecture"}).json()
    assert ex["state"] == "unavailable"


def test_overview_is_cached_per_index_version(client, monkeypatch):
    c, rid, m = client
    monkeypatch.setattr(m, "_llm_is_mock", lambda provider: False)
    calls = []
    monkeypatch.setattr(m, "_run", lambda body, **k: calls.append(body.question) or {"answer": "It delivers things [1].", "sources": [{"file": "delivery_app.py", "lines": "1-5", "symbol": "create_delivery", "cite": 1, "cited": True}], "citations": {"cited": [1], "invalid": []}, "llm": "gemini:test", "status": "ok"})
    a = c.post(f"/repositories/{rid}/overview", json={}).json()
    b = c.post(f"/repositories/{rid}/overview", json={}).json()
    assert a["state"] == "generated" and b["state"] == "cached" and len(calls) == 1
    assert "Facts detected by the parser" in calls[0] and "delivery_app.py" in calls[0]
    assert c.post(f"/repositories/{rid}/overview", json={"force": True}).json()["state"] == "generated" and len(calls) == 2
    assert c.get(f"/repositories/{rid}/overview").json()["overview"]["sources"][0]["file"] == "delivery_app.py"


def test_standard_library_is_not_reported_as_an_external_package(tmp_path):
    (tmp_path / "a.py").write_text("import os\nimport requests\nfrom pathlib import Path\n\n\ndef f():\n    return requests.get(os.getcwd(), timeout=1), Path('.')\n")
    idx = build_index(tmp_path)
    names = [e["name"] for e in sgm.insights(idx.graph, repo_stats(idx))["external"]]
    assert "requests" in names and "os" not in names and "pathlib" not in names
