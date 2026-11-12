"""The LangGraph workflow: dynamic routing, model-chosen tools, retries, reflection, review, degradation, context, memory."""
import json

import pytest
from fastapi.testclient import TestClient

from app.agent.context import ContextBuilder
from app.agent.graph import build_graph, run_agent
from app.agent.memory import ConversationStore
from app.agent.nodes import AgentRuntime
from app.agent.run import run_task
from app.agent.specialists import normalize_plan
from app.agent.state import new_state
from app.agent.trace import error_signature, parse_frames, resolve_frames
from app.config import get_settings
from app.llm.types import LLMUnavailable
from tests.conftest import FIXTURE
from tests.helpers import FIX_SCRIPT, ScriptedLLM

@pytest.fixture(params=["simple", "langgraph"])
def engine(request):
    return request.param
EDIT = {k: FIX_SCRIPT["generate_fix"][k] for k in ("file", "search", "replace")}
BAD = {"file": "services/eta.py", "search": "    return round(distance_km / speed_kmh * 60)", "replace": "    return 0"}


def go(tools, script, question="500 error when creating a delivery without speed", engine="simple", allow_fix=True, mode="debug", **kw):
    llm = ScriptedLLM(script, **kw.pop("llm_kw", {}))
    st = run_task(llm, tools, get_settings(), repo_id="r", mode=mode, text=question, allow_fix=allow_fix, engine=engine, **kw)
    return llm, st


def _skip(engine):
    if engine == "langgraph":
        pytest.importorskip("langgraph")


# ---- routing is decided by the plan and the results, not fixed -------------------------------------
def test_a_question_never_reaches_the_coder_or_tester(engine, tools):
    _skip(engine)
    llm, st = go(tools, {"understand": {"intent": "explain", "queries": ["authenticate"]}}, "Where is authentication implemented?", engine, False, "chat")
    assert st["status"] == "answered" and st["plan"]["needs_patch"] is False
    assert not {"generate_fix", "review_patch", "generate_change"} & set(llm.calls)
    assert [s["agent"] for s in st["plan"]["steps"]] == ["researcher", "debugger"]


def test_a_bug_report_goes_through_every_specialist(engine, tools):
    _skip(engine)
    script = dict(FIX_SCRIPT, review_patch={"approved": True, "summary": "minimal and correct"})
    llm, st = go(tools, script, engine=engine)
    assert st["status"] == "fix_verified"
    assert llm.calls.index("understand") < llm.calls.index("plan") < llm.calls.index("analyze") < llm.calls.index("generate_fix") < llm.calls.index("review_patch")
    assert st["review"]["approved"] and "Reviewer: approved" in st["answer"]
    for heading in ("## Root Cause", "## Affected Files", "## Explanation", "## Proposed Fix", "## Tests Executed", "## Verification Result"):
        assert heading in st["answer"]
    assert [s["agent"] for s in st["plan"]["steps"]] == ["researcher", "debugger", "coder", "tester", "reviewer"]


def test_the_planner_can_drop_steps_it_does_not_need(engine, tools):
    _skip(engine)
    script = dict(FIX_SCRIPT, plan={"steps": [{"agent": "researcher"}, {"agent": "coder"}], "needs_review": False})
    llm, st = go(tools, script, engine=engine)
    assert "review_patch" not in llm.calls and st["status"] == "fix_verified"


def test_planner_output_cannot_exceed_what_the_endpoint_allows():
    p = normalize_plan({"needs_patch": True, "needs_review": True, "steps": [{"agent": "coder"}]}, "debug", allow_fix=False, allow_verify=True)
    assert not p["needs_patch"] and not p["needs_tester"] and not p["needs_review"]
    p = normalize_plan({"needs_patch": False}, "debug", allow_fix=True, allow_verify=True)
    assert not p["needs_patch"]                                     # a diagnosis-only request stays diagnosis-only
    assert normalize_plan({"needs_patch": False}, "change", True, True)["needs_patch"]
    assert normalize_plan({}, "review", False, False)["needs_review"]


# ---- the model chooses its tools ----------------------------------------------------------------------
def test_model_selected_tools_feed_the_evidence(engine, tools):
    _skip(engine)
    script = {"understand": {"intent": "explain", "queries": ["zzz"]},
              "research": [{"tool_calls": [{"name": "find_symbol", "args": {"name": "authenticate_user"}},
                                           {"name": "grep", "args": {"query": "DEFAULT_SPEED_KMH"}}]},
                           {"tool_calls": [{"name": "find_symbol", "args": {"name": "authenticate_user"}}]},   # repeated call is refused
                           {"text": "enough"}]}
    llm, st = go(tools, script, "how does auth work", engine, False, "chat")
    vias = {(c["file"], c.get("via")) for c in st["evidence"]}
    assert ("auth.py", "symbol") in vias and any(v == "grep" for _, v in vias)
    assert "tool call(s)" in next(s["message"] for s in st["steps"] if s["node"] == "research")
    assert st["tool_calls_used"] == 2


def test_tool_budget_and_bad_calls_are_handled(engine, tools, monkeypatch):
    _skip(engine)
    monkeypatch.setenv("MAX_TOOL_CALLS", "2")
    script = {"research": [{"tool_calls": [{"name": "nonexistent", "args": {}}, {"name": "read_file", "args": {"path": "../../etc/passwd"}},
                                           {"name": "search_code", "args": {"query": "eta"}}]}, {"text": "ok"}]}
    llm, st = go(tools, script, "eta?", engine, False, "chat")
    # 2 model calls fit the budget (both returned errors, not crashes); the third was refused; 1 fallback search ran because nothing was found
    assert st["tool_calls_used"] == 3 and st["status"] == "answered"
    assert any(c["via"] == "search" for c in st["evidence"])


def test_if_the_model_uses_no_tools_the_planned_queries_still_run(engine, tools):
    _skip(engine)
    llm, st = go(tools, {"understand": {"intent": "explain", "queries": ["calculate_delivery_eta"]}}, "eta", engine, False, "chat")
    assert any(c["file"] == "services/eta.py" for c in st["evidence"])


# ---- stack traces start retrieval at the failing line -------------------------------------------------
TRACE = '''Traceback (most recent call last):
  File "/home/dev/app/services/eta.py", line 6, in calculate_delivery_eta
    return round(distance_km / speed_kmh * 60)
TypeError: unsupported operand type(s) for /: 'int' and 'NoneType'
'''


def test_trace_parsing():
    fr = resolve_frames(parse_frames(TRACE + '  File "/usr/lib/python3/site-packages/x.py", line 1, in f\n'), ["services/eta.py"])
    assert [(f.file, f.line, f.func) for f in fr] == [("services/eta.py", 6, "calculate_delivery_eta")]
    assert error_signature(TRACE).startswith("TypeError: unsupported operand")
    node = parse_frames("    at handler (/srv/api/routes/users.ts:42:13)\n    at Foo.bar(Foo.java:77)")
    assert [(f.file, f.line) for f in node] == [("/srv/api/routes/users.ts", 42), ("Foo.java", 77)]


def test_stack_trace_seeds_the_failing_function_first(engine, tools):
    _skip(engine)
    llm, st = go(tools, {"understand": {"intent": "debug", "queries": ["unrelated words"]}}, TRACE, engine, False, "chat")
    assert st["frames"] == [{"file": "services/eta.py", "line": 6, "func": "calculate_delivery_eta"}]
    assert st["context"][0]["file"] == "services/eta.py" and st["context"][0]["via"] in ("traceback", "symbol")
    assert any("TypeError" in q for q in st["queries"]) or "TypeError" in str(st["entities"]["errors"])


# ---- retries, reflection, review ----------------------------------------------------------------------
def test_failed_tests_trigger_reflection_and_a_retry_with_feedback(engine, tools):
    _skip(engine)
    script = dict(FIX_SCRIPT, generate_fix=[BAD, EDIT], reflect={"action": "retry_code", "reason": "returning 0 is not an ETA"},
                  review_patch={"approved": True})
    llm, st = go(tools, script, engine=engine)
    assert st["attempts"] == 2 and st["status"] == "fix_verified" and "reflect" in llm.calls
    retry_prompt = [p for t, p in llm.prompts if t == "generate_fix"][1]
    assert "did not solve it" in retry_prompt and "Test output" in retry_prompt and "returning 0 is not an ETA" in retry_prompt


def test_reflection_can_send_the_agent_back_to_research(engine, tools):
    _skip(engine)
    script = dict(FIX_SCRIPT, generate_fix=[BAD, EDIT], reflect={"action": "research_more", "reason": "need the caller", "queries": ["create_delivery"]})
    llm, st = go(tools, script, engine=engine)
    assert st["retrieval_rounds"] == 2 and llm.calls.count("analyze") == 2 and st["status"] == "fix_verified"
    assert any(c["file"] == "delivery_app.py" for c in st["evidence"])


def test_reflection_can_stop(engine, tools):
    _skip(engine)
    script = dict(FIX_SCRIPT, generate_fix=[BAD, EDIT], reflect={"action": "stop", "reason": "not fixable"})
    llm, st = go(tools, script, engine=engine)
    assert st["status"] == "fix_failed" and st["attempts"] == 1


def test_attempts_are_capped(engine, tools):
    _skip(engine)
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix=[BAD, BAD, BAD]), engine=engine)
    assert st["attempts"] == get_settings().max_fix_attempts and st["status"] == "fix_failed"


def test_reviewer_rejection_sends_the_patch_back_to_the_coder(engine, tools):
    _skip(engine)
    other = dict(EDIT, replace=EDIT["replace"] + "  # keeps working")
    script = dict(FIX_SCRIPT, generate_fix=[EDIT, other],
                  review_patch=[{"approved": False, "summary": "hides the problem", "feedback": "validate speed_kmh explicitly"}, {"approved": True, "summary": "ok"}])
    llm, st = go(tools, script, engine=engine)
    assert st["attempts"] == 2 and llm.calls.count("review_patch") == 2 and st["review"]["approved"]
    assert "validate speed_kmh explicitly" in [p for t, p in llm.prompts if t == "generate_fix"][1]


def test_a_patch_that_does_not_parse_is_rejected_by_the_engine_and_retried(engine, tools):
    _skip(engine)
    broken = dict(EDIT, replace="    speed_kmh = (\n    return 1")
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix=[broken, EDIT], review_patch={"approved": True}), engine=engine, mode="fix", allow_verify=False)
    assert llm.calls.count("generate_fix") == 2 and llm.calls.count("review_patch") == 1     # the reviewer only ever sees the valid second patch
    assert any("rejected" in s["message"] and "syntax error" in s["message"] for s in st["steps"] if s["node"] == "generate")
    assert "syntax error" in [p for t, p in llm.prompts if t == "generate_fix"][1] and st["status"] == "fix_unverified"


def test_an_invalid_edit_is_retried_with_the_reason(engine, tools):
    _skip(engine)
    missing = {"file": "services/eta.py", "search": "this text does not exist", "replace": "x"}
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix=[missing, EDIT]), engine=engine)
    assert st["attempts"] == 2 and st["status"] == "fix_verified"
    assert any("rejected" in s["message"] for s in st["steps"])
    assert "must match exactly once" in [p for t, p in llm.prompts if t == "generate_fix"][1]


def test_regression_test_request_reaches_the_coder(engine, tools):
    _skip(engine)
    new_test = {"edits": [EDIT], "new_files": [{"path": "tests/test_eta_default.py", "content": "def test_ok():\n    assert True\n"}]}
    script = dict(FIX_SCRIPT, plan={"needs_regression_test": True}, generate_fix=new_test)
    llm, st = go(tools, script, engine=engine)
    assert "regression test" in [p for t, p in llm.prompts if t == "generate_fix"][0] and "tests/test_eta_default.py" in st["final_files"]


# ---- other modes ride the same graph --------------------------------------------------------------------
def test_change_mode_and_tests_mode(engine, tools):
    _skip(engine)
    llm, st = go(tools, {"generate_change": {"edits": [EDIT], "new_files": [], "explanation": "default speed"}}, "default the delivery speed", engine, mode="change")
    assert st["intent"] == "change" and st["status"] == "fix_verified" and "default speed" in st["answer"]
    t = {"generate_tests": {"edits": [], "new_files": [{"path": "tests/test_x.py", "content": "def test_ok():\n    assert 1\n"}], "explanation": "basic"}}
    llm, st = go(tools, t, "Write tests for services/eta.py", engine, mode="tests", target="services/eta.py")
    assert st["intent"] == "tests" and list(st["final_files"]) == ["tests/test_x.py"] and "analyze" not in llm.calls


def test_review_and_docs_modes(engine, tools):
    _skip(engine)
    llm, st = go(tools, {"review": {"summary": "fine", "findings": [{"file": "auth.py", "line": 3, "severity": "high", "message": "weak"}]}},
                 "review", engine, False, "review")
    assert st["status"] == "reviewed" and st["review_report"]["findings"][0]["source"] == "ai" and "weak" in st["answer"]
    llm, st = go(tools, {"document": {"summary": "## Overview\nA delivery app."}}, "architecture", engine, False, "architecture")
    assert st["intent"] == "docs" and "A delivery app." in st["answer"] and "services" in st["facts"]["folders"]


def test_chat_mode_can_never_patch_even_if_the_model_says_change(engine, tools):
    _skip(engine)
    llm, st = go(tools, dict(FIX_SCRIPT, understand={"intent": "change", "queries": ["eta"]}), "bug in eta", engine, False, "chat")
    assert st["intent"] == "explain" and st["edits"] == [] and "generate_fix" not in llm.calls


# ---- graceful degradation ----------------------------------------------------------------------------------
class Flaky(ScriptedLLM):
    def __init__(self, script, fail=(), **kw):
        super().__init__(script, **kw)
        self.fail = set(fail)

    def json(self, task, system, prompt, hints=None, schema=None):
        if task in self.fail:
            self.calls.append(task)
            raise LLMUnavailable("provider down")
        return super().json(task, system, prompt, hints, schema)


def test_planning_failures_degrade_to_heuristics_but_analysis_failures_are_reported(engine, tools):
    _skip(engine)
    llm = Flaky(FIX_SCRIPT, fail={"understand", "plan"})
    st = run_task(llm, tools, get_settings(), mode="debug", text=TRACE, allow_fix=True, engine=engine)
    assert st["intent"] == "debug" and st["status"] == "fix_verified" or st["status"] in ("fix_failed", "fix_unverified", "no_fix")
    assert any("model unavailable" in s["message"] for s in st["steps"])
    llm = Flaky(FIX_SCRIPT, fail={"analyze"})
    st = run_task(llm, tools, get_settings(), mode="debug", text="bug in eta", allow_fix=True, engine=engine)
    assert st["status"] == "error" and "provider down" in st["answer"] and st["edits"] == []


def test_runaway_runs_are_stopped(engine, tools, monkeypatch):
    _skip(engine)
    monkeypatch.setenv("MAX_AGENT_TOTAL_STEPS", "3")
    llm, st = go(tools, FIX_SCRIPT, engine=engine)
    assert st["step_count"] <= 4 and st["answer"]


# ---- context: small, ranked, budgeted -----------------------------------------------------------------------
def test_context_is_budgeted_and_ranked_by_signals(tools):
    ev = [dict(c, via="search", score=0.1) for c in tools.search_code("delivery", k=10)]
    trace = tools.chunk_at("services/eta.py", 6)
    cb = ContextBuilder(tools, get_settings())
    built = cb.build(ev + [trace], {"symbols": ["calculate_delivery_eta"], "files": []}, "debug", budget=400)
    assert built.chunks[0]["qualname"] == "calculate_delivery_eta" and built.report["tokens"] <= 400 and built.report["by_source"]["traceback"] == 1
    big = cb.build(ev, {}, "explain", budget=6000)
    assert big.report["kept"] <= get_settings().max_context_chunks
    assert "files." in cb.repo_map() and len(cb.repo_map().splitlines()) <= 3      # orientation, not a file listing


def test_coder_sees_the_exact_function_source_not_a_truncated_chunk(tools):
    cb = ContextBuilder(tools, get_settings())
    t = cb.target_code({"affected_file": "services/eta.py", "affected_function": "calculate_delivery_eta"})
    assert "return round(distance_km / speed_kmh * 60)" in t and "services/eta.py" in t


def test_prompts_do_not_contain_the_whole_repository(engine, tools):
    _skip(engine)
    llm, st = go(tools, FIX_SCRIPT, engine=engine)
    everything = sum(len(p) for _, p in llm.prompts)
    repo_chars = sum(len((tools.root / f).read_text()) for f in tools.index.tree if f.endswith(".py"))
    assert st["context_report"]["kept"] >= 1 and st["context_report"]["tokens"] <= st["context_report"]["budget"]
    assert all("Retrieved code" not in p or len(p) < repo_chars * 3 for _, p in llm.prompts) and everything > 0


# ---- memory --------------------------------------------------------------------------------------------------
def test_conversation_history_reaches_the_next_prompt_and_persists(engine, tools, tmp_path):
    _skip(engine)
    store = ConversationStore(tmp_path / "conv")
    s1 = ScriptedLLM(FIX_SCRIPT)
    run_task(s1, tools, get_settings(), mode="chat", text="why does the eta crash?", conversation_id="c1", store=store, engine=engine)
    assert store.turns("c1")[0]["files"][0] == "services/eta.py"
    s2 = ScriptedLLM(dict(FIX_SCRIPT, understand={"intent": "debug", "queries": ["eta"], "follow_up": True}))
    st = run_task(s2, tools, get_settings(), mode="debug", text="ok, fix it", allow_fix=True, conversation_id="c1", store=ConversationStore(tmp_path / "conv"), engine=engine)
    prompt = dict(s2.prompts)["understand"]
    assert "why does the eta crash?" in prompt and "services/eta.py" in prompt
    assert "services/eta.py" in st["entities"]["files"]               # "it" resolved to the file of the last turn
    assert len(ConversationStore(tmp_path / "conv").turns("c1")) == 2


def test_history_is_budgeted_and_ids_are_validated(tmp_path):
    st = ConversationStore(tmp_path)
    for i in range(12):
        st.append("c", {"question": f"question {i} " * 20, "status": "answered", "summary": "x" * 400, "files": [f"f{i}.py"]})
    text = st.render("c", recent=3, budget=300)
    assert "question 11" in text and "question 0" not in text and len(text) < 2500
    assert st.render("../../etc", 3, 300) == "" and not ConversationStore.valid("a/b")
    st.append("../x", {"question": "q"})
    assert not list(tmp_path.glob("*x*"))


def test_langgraph_graph_is_inspectable(engine, tools):
    pytest.importorskip("langgraph")
    mermaid = build_graph(AgentRuntime(ScriptedLLM({}), tools, get_settings())).get_graph().draw_mermaid()
    for node in ("understand", "plan", "research", "analyze", "code", "test", "reflect", "review", "document", "respond"):
        assert node in mermaid


# ---- API ------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    m._conversations = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "delivery-sync"}).json()["id"]
    return c, m, rid


def test_api_returns_plan_context_usage_and_a_conversation_id(engine, client, monkeypatch):
    c, m, rid = client
    llms = []
    def make(p=None):
        llms.append(ScriptedLLM(dict(FIX_SCRIPT, review_patch={"approved": True})))
        return llms[-1]
    monkeypatch.setattr(m, "get_llm", make)
    r = c.post("/debug", json={"repo_id": rid, "question": "500 error when creating a delivery"}).json()
    assert r["status"] == "fix_verified" and r["conversation_id"] and r["patch"]["file"] == "services/eta.py"
    assert r["plan"]["intent"] == "debug" and r["plan"]["needs_patch"] and r["context"]["kept"] >= 1
    assert r["usage"]["calls"] >= 5 and "by_task" in r["usage"] and r["tool_calls"] >= 0
    r2 = c.post("/chat", json={"repo_id": rid, "question": "and why?", "conversation_id": r["conversation_id"]}).json()
    assert r2["conversation_id"] == r["conversation_id"]
    assert "500 error when creating a delivery" in dict(llms[-1].prompts)["understand"]
    assert c.delete(f"/conversations/{r['conversation_id']}").status_code == 200


def test_api_usage_and_info_endpoints(engine, client):
    c, m, rid = client
    c.post("/chat", json={"repo_id": rid, "question": "where is auth?"})
    u = c.get("/llm/usage").json()
    assert u["calls"] >= 1 and "by_model" in u and isinstance(u["recent"], list)
    assert c.get("/llm/info").json()["provider"] == "mock"


def test_api_surfaces_model_failure_as_502(engine, client, monkeypatch):
    c, m, rid = client
    monkeypatch.setattr(m, "get_llm", lambda p=None: Flaky(FIX_SCRIPT, fail={"analyze"}))
    r = c.post("/chat", json={"repo_id": rid, "question": "q"})
    assert r.status_code == 502 and "provider down" in r.json()["detail"]
