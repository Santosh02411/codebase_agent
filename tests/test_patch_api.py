"""Patch proposals over the API: review, explicit approval, automatic checks, stale detection, revert, repair, screenshots."""
import base64

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURE
from tests.helpers import FIX_SCRIPT, ScriptedLLM

EDIT = {k: FIX_SCRIPT["generate_fix"][k] for k in ("file", "search", "replace")}
BAD_EDIT = dict(EDIT, replace="    return 0")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    m._conversations = None
    m._patch_store = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "delivery-sync"}).json()["id"]
    _, root, _ = m._repo(rid)
    return c, m, rid, root


def use(m, monkeypatch, script, **kw):
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM(script, **kw))


def propose(c, rid, **spec):
    return c.post("/patches", json={"repo_id": rid, **spec})


# ---- from an agent run to a reviewable proposal ------------------------------------------------------------------------------------------
def test_debug_run_returns_a_patch_proposal_with_exact_before_and_after(api, monkeypatch):
    c, m, rid, root = api
    use(m, monkeypatch, dict(FIX_SCRIPT, review_patch={"approved": True}))
    r = c.post("/debug", json={"repo_id": rid, "question": "TypeError: unsupported operand type(s) for /: 'int' and 'NoneType' in services/eta.py"}).json()
    assert r["patch_id"] and r["patch_files"] == [{"path": "services/eta.py", "op": "modify", "additions": 1, "deletions": 0, "fuzzy": False, "notes": []}]
    assert r["verification"]["status"] == "resolved" and r["error_report"]["exception_type"] == "TypeError" and r["affected_files"]
    assert "## Verification Result" in r["answer"] and r["lint"]["tool"]
    p = c.get(f"/patches/{r['patch_id']}").json()
    assert p["status"] == "proposed" and p["stats"]["files"] == 1 and p["origin"]["intent"] == "debug" and "+    speed_kmh = speed_kmh or DEFAULT_SPEED_KMH" in p["diff"]
    f = c.get(f"/patches/{r['patch_id']}/file", params={"path": "services/eta.py"}).json()
    assert f["original"] == (root / "services/eta.py").read_text() and "speed_kmh or DEFAULT_SPEED_KMH" in f["modified"] and f["op"] == "modify"
    assert (root / "services/eta.py").read_text() == f["original"]                    # proposing never writes
    assert c.get(f"/patches/{r['patch_id']}/file", params={"path": "auth.py"}).status_code == 404
    assert c.get("/patches/doesnotexist").status_code == 404


def test_apply_requires_explicit_approval_then_applies_reindexes_and_checks(api, monkeypatch):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT]).json()
    assert c.post(f"/patches/{p['id']}/apply", json={}).status_code == 403
    assert c.post(f"/patches/{p['id']}/apply", json={"approved": False}).status_code == 403
    assert "DEFAULT_SPEED_KMH\n    return" not in (root / "services/eta.py").read_text()
    r = c.post(f"/patches/{p['id']}/apply", json={"approved": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "applied" and body["applied_files"] == ["services/eta.py"] and body["index"]
    assert "speed_kmh or DEFAULT_SPEED_KMH" in (root / "services/eta.py").read_text()
    ch = body["checks"]
    assert ch["status"] == "passed" and ch["tests_before"]["status"] == "failed" and ch["tests_after"]["status"] == "passed"
    assert ch["verdict"]["status"] == "resolved" and ch["lint_after"]["tool"] and ch["lint_new"] == []
    assert [h["event"] for h in body["history"]] == ["proposed", "applied", "checks passed"]
    assert c.post(f"/patches/{p['id']}/apply", json={"approved": True}).status_code == 400          # not twice


def test_files_can_be_approved_individually(api):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT, {"file": "auth.py", "search": "def authenticate_user", "replace": "def authenticate_user_v2"}]).json()
    assert c.post(f"/patches/{p['id']}/apply", json={"approved": True, "files": ["nope.py"]}).status_code == 400
    r = c.post(f"/patches/{p['id']}/apply", json={"approved": True, "files": ["services/eta.py"], "run_checks": False}).json()
    assert r["applied_files"] == ["services/eta.py"] and r["checks"] is None
    assert "authenticate_user_v2" not in (root / "auth.py").read_text()


def test_a_patch_is_refused_when_files_changed_since_it_was_proposed(api):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT]).json()
    (root / "services/eta.py").write_text((root / "services/eta.py").read_text() + "\n# edited meanwhile\n")
    r = c.post(f"/patches/{p['id']}/apply", json={"approved": True})
    assert r.status_code == 409 and "changed since" in r.json()["detail"] and "edited meanwhile" in (root / "services/eta.py").read_text()


def test_revert_restores_everything_and_refuses_to_discard_later_edits(api):
    c, m, rid, root = api
    before = (root / "services/eta.py").read_text()
    p = propose(c, rid, edits=[EDIT], new_files=[{"path": "tests/test_new.py", "content": "def test_x():\n    assert True\n"}]).json()
    c.post(f"/patches/{p['id']}/apply", json={"approved": True, "run_checks": False})
    assert (root / "tests/test_new.py").exists()
    assert c.post(f"/patches/{p['id']}/revert", json={}).json()["status"] == "reverted"
    assert (root / "services/eta.py").read_text() == before and not (root / "tests/test_new.py").exists()
    p2 = propose(c, rid, edits=[EDIT]).json()
    c.post(f"/patches/{p2['id']}/apply", json={"approved": True, "run_checks": False})
    (root / "services/eta.py").write_text((root / "services/eta.py").read_text() + "# user edit\n")
    assert c.post(f"/patches/{p2['id']}/revert", json={}).status_code == 409
    assert c.post(f"/patches/{p2['id']}/revert", json={"force": True}).status_code == 200


def test_reject_and_listing(api):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT]).json()
    assert c.post(f"/patches/{p['id']}/reject").json()["status"] == "rejected"
    assert c.post(f"/patches/{p['id']}/apply", json={"approved": True}).status_code == 400
    assert [x["id"] for x in c.get("/patches", params={"repo_id": rid}).json()] == [p["id"]] and c.get("/patches", params={"repo_id": "other"}).json() == []


# ---- the engine through the API -------------------------------------------------------------------------------------------------------------------
def test_create_patch_from_a_unified_diff_new_and_deleted_files(api):
    c, m, rid, root = api
    diff = "--- a/services/eta.py\n+++ b/services/eta.py\n@@ -1,5 +1,5 @@\n DEFAULT_SPEED_KMH = 30\n \n \n def calculate_delivery_eta(distance_km, speed_kmh):\n-    \"\"\"Return estimated minutes for a delivery.\"\"\"\n+    \"\"\"Return the estimated minutes for a delivery.\"\"\"\n"
    r = propose(c, rid, unified_diff=diff, new_files=[{"path": "notes/CHANGES.md", "content": "# changes\n"}], delete_files=["services/validation.py"])
    assert r.status_code == 200, r.text
    ops = {f["path"]: f["op"] for f in r.json()["files"]}
    assert ops == {"services/eta.py": "modify", "notes/CHANGES.md": "create", "services/validation.py": "delete"}
    pid = r.json()["id"]
    c.post(f"/patches/{pid}/apply", json={"approved": True, "run_checks": False})
    assert not (root / "services/validation.py").exists() and (root / "notes/CHANGES.md").exists()
    c.post(f"/patches/{pid}/revert", json={})
    assert (root / "services/validation.py").exists() and not (root / "notes").exists()


@pytest.mark.parametrize("spec,msg", [({"edits": [dict(EDIT, search="nope")]}, "found 0"), ({}, "no changes proposed"), ({"new_files": [{"path": "../x.py", "content": "x"}]}, "escapes repository"),
                                      ({"edits": [dict(EDIT, replace="    return (")]}, "syntax error"), ({"delete_files": [".git/config"]}, ".git")])
def test_invalid_patches_are_rejected_with_a_useful_message(api, spec, msg):
    c, m, rid, root = api
    r = propose(c, rid, **spec)
    assert r.status_code == 400 and msg in r.json()["detail"]


# ---- failing checks -> the agent proposes another correction ------------------------------------------------------------------------------------
def test_failed_checks_can_be_repaired_by_the_agent(api, monkeypatch):
    c, m, rid, root = api
    p = propose(c, rid, edits=[BAD_EDIT]).json()
    r = c.post(f"/patches/{p['id']}/apply", json={"approved": True}).json()
    assert r["checks"]["status"] == "failed" and r["checks"]["verdict"]["status"] == "not_resolved"
    assert r["checks"]["tests_after"]["status"] == "failed"
    # the repair is proposed against the code as it is NOW (the bad patch is applied)
    fix_now = {"file": "services/eta.py", "search": "    return 0", "replace": "    speed_kmh = speed_kmh or DEFAULT_SPEED_KMH\n    return round(distance_km / speed_kmh * 60)"}
    use(m, monkeypatch, dict(FIX_SCRIPT, generate_fix=fix_now, review_patch={"approved": True}))
    rep = c.post(f"/patches/{p['id']}/repair", json={}).json()
    assert rep["patch_id"] and rep["patch_id"] != p["id"] and rep["verification"]["status"] == "resolved"
    child = c.get(f"/patches/{rep['patch_id']}").json()
    assert child["parent_id"] == p["id"] and child["status"] == "proposed"
    assert c.post(f"/patches/{rep['patch_id']}/apply", json={"approved": True}).json()["checks"]["status"] == "passed"
    assert "speed_kmh or DEFAULT_SPEED_KMH" in (root / "services/eta.py").read_text()


def test_only_applied_patches_can_be_repaired(api):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT]).json()
    assert c.post(f"/patches/{p['id']}/repair", json={}).status_code == 400


def test_the_repair_briefing_contains_the_failure(api):
    c, m, rid, root = api
    import app.patches as patches
    p = propose(c, rid, edits=[BAD_EDIT]).json()
    rec = c.post(f"/patches/{p['id']}/apply", json={"approved": True}).json()
    text = patches.repair_request(m.patch_store().get(p["id"]))
    assert "automatic checks FAILED" in text and "CURRENT code" in text and "return 0" in text and "test_create_delivery_default_speed" in text


def test_recheck_runs_tests_and_lint_again(api):
    c, m, rid, root = api
    p = propose(c, rid, edits=[EDIT]).json()
    c.post(f"/patches/{p['id']}/apply", json={"approved": True, "run_checks": False})
    r = c.post(f"/patches/{p['id']}/checks").json()
    assert r["checks"]["tests_after"]["status"] == "passed" and r["checks"]["status"] in ("passed", "inconclusive")


# ---- /change and /generate-tests also produce proposals ----------------------------------------------------------------------------------------
def test_change_and_tests_produce_proposals(api, monkeypatch):
    c, m, rid, root = api
    use(m, monkeypatch, {"generate_change": {"edits": [EDIT], "new_files": [], "explanation": "default speed"}})
    r = c.post("/change", json={"repo_id": rid, "request": "default the speed"}).json()
    assert r["status"] == "verified" and r["patch_id"] and c.get(f"/patches/{r['patch_id']}").json()["origin"]["intent"] == "change"
    assert r["verification"]["status"] == "resolved"                                       # the suite was failing before and passes now


# ---- screenshots -----------------------------------------------------------------------------------------------------------------------------------------
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def test_screenshot_validation_and_use(api, monkeypatch):
    c, m, rid, root = api
    base = {"repo_id": rid, "question": "see the screenshot"}
    assert c.post("/chat", json={**base, "images": [{"media_type": "image/svg+xml", "data": PNG}]}).status_code == 422
    assert c.post("/chat", json={**base, "images": [{"media_type": "image/png", "data": "not base64!!"}]}).status_code == 422
    assert c.post("/chat", json={**base, "images": [{"media_type": "image/png", "data": PNG}] * 4}).status_code == 422
    llms = []
    def make(p=None):
        llms.append(ScriptedLLM(dict(FIX_SCRIPT, read_screenshot=[{"text": "TypeError: unsupported operand type(s) for /: 'int' and 'NoneType'"}])))
        return llms[-1]
    monkeypatch.setattr(m, "get_llm", make)
    r = c.post("/chat", json={**base, "images": [{"media_type": "image/png", "data": PNG}]})
    assert r.status_code == 200 and r.json()["error_report"]["exception_type"] == "TypeError"
    assert llms[0].requests[0].messages[0].images[0]["data"] == PNG
    saved = (m.get_settings().data_dir / "runs" / f"{r.json()['run_id']}.json").read_text()
    assert PNG not in saved                                                           # screenshots are never persisted
