from pathlib import Path

from app.config import get_settings
from app.ingest import build_index
from app.agent.tools import RepoTools
from app.agent.run import run_task
from app.llm import get_llm

FIX = Path(__file__).parent / "fixtures" / "delivery_sync"


def _run(monkeypatch, fast: str, mode: str = "chat", text: str = "Where is the ETA calculated?"):
    monkeypatch.setenv("FAST_PLANNING", fast)
    s = get_settings()
    llm = get_llm("mock")
    st = run_task(llm, RepoTools(FIX, build_index(FIX), 30, llm=llm), s, mode=mode, text=text, allow_fix=False, allow_verify=False, engine="simple")
    return st, llm


def test_plain_questions_skip_both_planning_model_calls(monkeypatch):
    st, llm = _run(monkeypatch, "true")
    msgs = " | ".join(x["message"] for x in st["steps"])
    assert "fast path: no planning model call" in msgs and "fast path: default plan" in msgs
    st2, llm2 = _run(monkeypatch, "false")
    assert llm.usage.calls < llm2.usage.calls


def test_debugging_still_uses_the_planning_model(monkeypatch):
    st, _ = _run(monkeypatch, "true", mode="debug", text="TypeError: unsupported operand type(s) for /: 'int' and 'NoneType' in calculate_delivery_eta")
    assert "fast path: no planning model call" not in " | ".join(x["message"] for x in st["steps"])
