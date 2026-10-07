import pytest
from app.agent.graph import run_agent
from app.agent.nodes import AgentRuntime
from app.agent.state import new_state
from app.config import get_settings
from app.llm import MockLLM
from .helpers import FIX_SCRIPT, ScriptedLLM

pytestmark = pytest.mark.parametrize("engine", ["simple", "langgraph"])


def _engine_or_skip(engine):
    if engine == "langgraph":
        pytest.importorskip("langgraph")


def test_debug_loop_fixes_and_verifies(engine, tools, repo):
    _engine_or_skip(engine)
    rt = AgentRuntime(ScriptedLLM(FIX_SCRIPT), tools, get_settings())
    st = run_agent(rt, new_state("500 error when creating a delivery without speed", "r", allow_fix=True), engine)
    assert st["test_before"]["status"] == "failed"
    assert st["test_after"]["status"] == "passed"
    assert st["status"] == "fix_verified"
    assert "DEFAULT_SPEED_KMH" in st["diff"]
    # original repo is NOT modified until the user approves the patch
    assert "or DEFAULT_SPEED_KMH" not in (repo / "services/eta.py").read_text()


def test_failed_patch_is_retried_then_reported(engine, tools):
    _engine_or_skip(engine)
    bad = {"file": "services/eta.py", "search": "    return round(distance_km / speed_kmh * 60)",
           "replace": "    return 0", "explanation": "wrong"}
    script = dict(FIX_SCRIPT, generate_fix=[bad, bad])
    rt = AgentRuntime(ScriptedLLM(script), tools, get_settings())
    st = run_agent(rt, new_state("delivery bug", "r", allow_fix=True), engine)
    assert st["attempts"] == 2 and st["status"] == "fix_failed"


def test_follow_up_retrieval_round(engine, tools):
    _engine_or_skip(engine)
    script = {"analyze_query": {"intent": "explain", "queries": ["delivery"]},
              "analyze": [{"need_more": True, "follow_up_queries": ["authenticate_user"]},
                          {"need_more": False, "answer": "ok", "affected_file": "auth.py"}]}
    st = run_agent(AgentRuntime(ScriptedLLM(script), tools, get_settings()), new_state("q", "r"), engine)
    assert st["retrieval_rounds"] == 2
    assert any(c["file"] == "auth.py" for c in st["context"])


def test_chat_never_patches(engine, tools):
    _engine_or_skip(engine)
    st = run_agent(AgentRuntime(ScriptedLLM(FIX_SCRIPT), tools, get_settings()), new_state("bug in eta", "r", allow_fix=False), engine)
    assert st["edit"] is None and st["status"] == "answered"


def test_mock_llm_runs_end_to_end(engine, tools):
    _engine_or_skip(engine)
    st = run_agent(AgentRuntime(MockLLM(), tools, get_settings()), new_state("Where is authentication implemented?", "r"), engine)
    assert "auth.py" in st["answer"]
