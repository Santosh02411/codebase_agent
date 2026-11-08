"""Architecture overview, code review, multi-file changes and test generation.
These are modes of the one LangGraph agent (app/agent): each wrapper starts a run in the right mode and reshapes the final state
into the response the API has always returned."""
from __future__ import annotations

from .agent.checks import SECRET, static_checks  # noqa: F401  (re-exported: tests and callers import them from here)
from .agent.run import run_summary, run_task
from .agent.nodes import SYSTEM  # noqa: F401
from .rag.context import extract_citations

STATUS = {"fix_verified": "verified", "fix_unverified": "unverified", "fix_failed": "failed", "no_fix": "no_change", "answered": "no_change", "error": "error"}


def _sources(ctx: list[dict], text: str = "") -> list[dict]:
    cited = set(extract_citations(text, len(ctx))["cited"])
    out = [{"file": c["file"], "lines": f"{c['start']}-{c['end']}", "symbol": c["qualname"], "cite": n, "cited": n in cited}
           for n, c in enumerate(ctx, 1)]
    return sorted(out, key=lambda s: (not s["cited"], s["cite"]))


def _run(llm, tools, s, mode: str, **kw):
    st = run_task(llm, tools, s, mode=mode, **kw)
    if st.get("status") == "error":
        raise RuntimeError(st.get("error") or "agent failed")
    return st


def architecture(llm, tools, s=None) -> dict:
    from .config import get_settings
    st = _run(llm, tools, s or get_settings(), "architecture", text="Explain the architecture of this project.")
    return {"answer": st["docs"], "facts": st["facts"], "steps": st["steps"], "sources": [], **run_summary(st, llm)}


def review(llm, tools, path: str | None = None, s=None) -> dict:
    from .config import get_settings
    st = _run(llm, tools, s or get_settings(), "review", text=f"Review {path}" if path else "Review this project for bugs, security problems and maintainability.", target=path or "")
    rr = st["review_report"]
    return {"summary": rr["summary"], "findings": rr["findings"], "steps": st["steps"], "sources": [], **run_summary(st, llm)}


def _change(llm, tools, s, mode: str, text: str, verify: bool, target: str = "") -> dict:
    st = _run(llm, tools, s, mode, text=text, target=target, allow_fix=True, allow_verify=verify)
    has = bool(st["patch_files"])
    status = STATUS.get(st["status"], "no_change") if has else "no_change"
    out = {"status": status, "explanation": st.get("explanation", ""), "steps": st["steps"], "test_before": st["test_before"], "test_after": st["test_after"],
           "sources": _sources(st["context"], str(st.get("explanation", ""))), "edits": [], "new_files": [], "delete_files": [], "files": [], "final_files": {},
           "diff": "", "review": st.get("review"), "verification": st.get("verification"), "lint_new": st.get("lint_new", []), "lint_before": st.get("lint_before"),
           "spec": None, "patch_files": [], **run_summary(st, llm)}
    if has:
        out.update(edits=st["edits"], new_files=st["new_files"], delete_files=st["delete_files"], files=[f["path"] for f in st["patch_files"]],
                   final_files=st["final_files"], diff=st["diff"], spec=st["spec"], patch_files=st["patch_files"])
    return out


def change_code(llm, tools, s, request: str, verify: bool = True) -> dict:
    return _change(llm, tools, s, "change", request, verify)


def generate_tests(llm, tools, s, target: str, verify: bool = True) -> dict:
    return _change(llm, tools, s, "tests", f"Write tests for {target}", verify, target=target)
