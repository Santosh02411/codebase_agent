"""Wraps tools, LLM calls and agent nodes so every action is reported live to the UI (Agent Activity panel)."""
from __future__ import annotations
import time
from typing import Callable

Emit = Callable[[dict], None]
NODES = ("analyze_query", "retrieve", "analyze", "generate_fix", "verify", "respond")
TOOLS = ("search_code", "related", "read_file", "find_symbol", "get_dependencies", "list_tree", "run_tests")


def _args(name: str, a: tuple, k: dict) -> str:
    vals = [str(x) for x in a] + [f"{key}={v}" for key, v in k.items()]
    return ", ".join(vals)[:160]


def _summary(name: str, res) -> tuple[str, list[dict]]:
    if name in ("search_code", "related", "find_symbol"):
        hits = [{"file": h["file"], "lines": f"{h['start']}-{h['end']}", "symbol": h["qualname"]} for h in res]
        return f"{len(res)} result{'s' * (len(res) != 1)}", hits
    if name == "read_file":
        return f"{len(str(res).splitlines())} lines", []
    if name == "run_tests":
        return f"{res.get('status')} — {res.get('summary')}", []
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
            text, hits = _summary(name, res)
            emit({"type": "tool", "name": name, "args": label, "phase": "end", "summary": text, "hits": hits,
                  "ms": int((time.time() - t0) * 1000)})
            return res
        return wrapped

    for n in TOOLS:
        if hasattr(tools, n):
            setattr(tools, n, wrap_tool(n, getattr(tools, n)))

    orig_json = llm.json

    def llm_json(task, system, prompt, hints=None):
        t0 = time.time()
        emit({"type": "llm", "task": task, "model": llm.name, "phase": "start", "prompt_chars": len(prompt)})
        try:
            res = orig_json(task, system, prompt, hints=hints)
        except Exception as e:
            emit({"type": "llm", "task": task, "model": llm.name, "phase": "error", "error": str(e)[:200]})
            raise
        emit({"type": "llm", "task": task, "model": llm.name, "phase": "end", "ms": int((time.time() - t0) * 1000)})
        return res

    llm.json = llm_json

    if rt is None:
        return

    def wrap_node(name: str, orig):
        def wrapped(state):
            emit({"type": "node", "node": name, "phase": "start"})
            before = len(state.get("steps", []))
            out = orig(state)
            for s in (out.get("steps") or [])[before:]:
                emit({"type": "step", **s})
            emit({"type": "node", "node": name, "phase": "end"})
            return out
        return wrapped

    for n in NODES:
        setattr(rt, n, wrap_node(n, getattr(rt, n)))
