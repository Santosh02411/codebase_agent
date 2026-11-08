"""Wraps tools and hooks the LLM layer so every action is reported live to the UI (Agent Activity panel).
Node start/end events come from the graph itself (agent/graph.py) through `tools.emit`."""
from __future__ import annotations
import time
from typing import Callable

Emit = Callable[[dict], None]
TOOLS = ("search_code", "related", "read_file", "find_symbol", "get_dependencies", "list_tree", "run_tests", "callers", "callees", "impact", "grep", "list_files", "git_status", "git_log", "git_diff", "search_docs", "find_config", "inspect_project", "search_web", "lint", "check_patch", "git_branches", "git_show", "git_blame", "git_file_at", "git_changed_files", "git_authors", "git_history")


def _args(name: str, a: tuple, k: dict) -> str:
    vals = [str(x) for x in a] + [f"{key}={v}" for key, v in k.items()]
    return ", ".join(vals)[:160]


def _summary(name: str, res, tools=None) -> tuple[str, list[dict]]:
    if name == "search_code" and tools is not None and tools.last_trace:
        t = tools.last_trace
        legs = f"{t.get('vector_candidates', 0)} vector + {t.get('keyword_candidates', 0)} keyword"
        text = (f"{t.get('mode')}: {legs} → {t.get('fused', 0)} fused → {t.get('reranker', 'no rerank')} → {len(res)} "
                f"({t.get('total_ms', 0)} ms)") + (f" ⚠ {t['warnings'][0]}" if t.get("warnings") else "")
        return text, [{"file": h["file"], "lines": f"{h['start']}-{h['end']}", "symbol": h["qualname"]} for h in res]
    if name in ("search_code", "related", "find_symbol"):
        hits = [{"file": h["file"], "lines": f"{h['start']}-{h['end']}", "symbol": h["qualname"]} for h in res]
        return f"{len(res)} result{'s' * (len(res) != 1)}", hits
    if name in ("callers", "callees"):
        return f"{len(res)} edge{'s' * (len(res) != 1)}", [{"file": h["file"], "lines": f"{h['start']}-{h['end']}", "symbol": h.get("caller") or h.get("callee", "")} for h in res]
    if name == "impact":
        return f"{len(res['dependents'])} dependent files, {len(res['tests'])} tests", []
    if name == "read_file":
        return f"{len(str(res).splitlines())} lines", []
    if name == "run_tests":
        return f"{res.get('status')} — {res.get('summary')}", []
    if name in ("git_status", "git_log", "git_diff", "git_branches", "git_show", "git_blame", "git_file_at", "git_changed_files", "git_authors", "git_history"):
        return f"{len(str(res).splitlines())} lines", []
    if name == "search_docs":
        return f"{len(res)} section{'s' * (len(res) != 1)}", [{"file": h["file"], "lines": f"{h['start']}-{h['end']}", "symbol": h["name"]} for h in res]
    if name == "find_config":
        return f"{len(res['matches'])} line(s) in {res['files_scanned']} config files", []
    if name == "inspect_project":
        return f"{res['files']} files; {', '.join(res['frameworks'][:4]) or 'no frameworks detected'}", []
    if name == "search_web":
        return f"{len(res)} result{'s' * (len(res) != 1)}", []
    if name == "lint":
        return f"{res['tool']}: {res['summary']}", []
    if name == "check_patch":
        return f"{len(res['lint_new'])} new lint finding(s)" + (f"; tests {res['tests']['status']}" if res.get("tests") else ""), []
    return "", []


def instrument(rt, llm, tools, emit: Emit) -> None:
    tools.emit = emit  # features._change reports its own steps through this

    def wrap_tool(name: str, orig):
        def wrapped(*a, **k):
            t0 = time.time()
            label = _args(name, a, k)
            emit({"type": "tool", "name": name, "args": label, "phase": "start"})
            try:
                res = orig(*a, **k)
            except Exception as e:
                emit({"type": "tool", "name": name, "args": label, "phase": "error", "error": str(e)[:200],
                      "ms": int((time.time() - t0) * 1000)})
                raise
            text, hits = _summary(name, res, tools)
            emit({"type": "tool", "name": name, "args": label, "phase": "end", "summary": text, "hits": hits,
                  "ms": int((time.time() - t0) * 1000)})
            return res
        return wrapped

    for n in TOOLS:
        if hasattr(tools, n):
            setattr(tools, n, wrap_tool(n, getattr(tools, n)))

    if hasattr(llm, "set_observer"):
        llm.set_observer(emit)      # every model call (start/end/retry/error, tokens, latency) reports itself
        return
    orig_json = llm.json            # a bare test double without the observer hook

    def llm_json(task, system, prompt, hints=None, **kw):
        t0 = time.time()
        emit({"type": "llm", "task": task, "model": llm.name, "phase": "start", "prompt_chars": len(prompt)})
        try:
            res = orig_json(task, system, prompt, hints=hints, **kw)
        except Exception as e:
            emit({"type": "llm", "task": task, "model": llm.name, "phase": "error", "error": str(e)[:200]})
            raise
        emit({"type": "llm", "task": task, "model": llm.name, "phase": "end", "ms": int((time.time() - t0) * 1000)})
        return res

    llm.json = llm_json
