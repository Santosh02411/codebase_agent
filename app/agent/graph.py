"""The agent as a LangGraph state machine.

    understand → plan → research ⇄ analyze → code → test → (reflect → code | research) → review → document → respond

The edges are conditional: `AgentRuntime.route` reads the planner's plan and the results so far, so a question never reaches the coder,
a failed test goes to reflection (retry the patch, or go back and gather more code), a rejected patch goes back to the coder with the
reviewer's feedback, and insufficient context sends the run back to research. Without LangGraph installed the same nodes run in a
plain loop."""
from __future__ import annotations
import time
from ..llm.types import LLMError
from .nodes import AGENT_OF, END, AgentRuntime
from .state import AgentState, log

NODES = ["understand", "plan", "research", "analyze", "code", "test", "reflect", "review", "pr", "document", "respond"]
EDGES = {"understand": ["plan"], "plan": ["research"], "research": ["analyze", "review", "pr", "document", "code", "respond"], "pr": ["respond"],
         "analyze": ["research", "code", "respond"], "code": ["code", "test", "review", "document", "respond"],
         "test": ["reflect", "review", "document", "respond"], "reflect": ["code", "research", "respond"],
         "review": ["code", "document", "respond"], "document": ["respond"]}


def _wrap(rt: AgentRuntime, name: str):
    """Report node start/end/steps live (through tools.emit, set by instrument) and turn model failures into a clean error state."""
    def run(state: AgentState) -> dict:
        emit = getattr(rt.tools, "emit", None)
        agent = AGENT_OF.get(name, "")
        if emit:
            emit({"type": "node", "node": name, "agent": agent, "phase": "start"})
        before = len(state.get("steps", []))
        if name != "respond" and (rt.cancel.is_set() or (rt.deadline is not None and time.monotonic() > rt.deadline)):
            why = "cancelled" if rt.cancel.is_set() else f"exceeded the {getattr(rt.s, 'max_run_seconds', 0)}s time limit"
            out = {"error": f"the run was {why}", "status": "error", "steps": log(state, name, f"stopped: the run was {why}")}
            return dict(out, step_count=state.get("step_count", 0) + 1)
        try:
            out = getattr(rt, name)(state)
        except LLMError as e:
            msg = f"{type(e).__name__}: {e}"[:300]
            out = {"error": msg, "status": "error", "steps": log(state, name, f"model call failed: {msg}")}
        out = dict(out, step_count=state.get("step_count", 0) + 1)
        if emit:
            for s in out.get("steps", [])[before:]:
                emit({"type": "step", "agent": agent, **s})
            emit({"type": "node", "node": name, "agent": agent, "phase": "end"})
        return out
    return run


def _run_simple(rt: AgentRuntime, state: AgentState) -> AgentState:
    node, guard = "understand", 0
    while node != END and guard < 80:
        state.update(_wrap(rt, node)(state))
        node = rt.route(node, state)
        guard += 1
    return state


def _run_langgraph(rt: AgentRuntime, state: AgentState) -> AgentState:
    from langgraph.graph import END as LG_END, START, StateGraph

    g = StateGraph(AgentState)
    for n in NODES:
        g.add_node(n, _wrap(rt, n))
    g.add_edge(START, "understand")
    for n, targets in EDGES.items():
        g.add_conditional_edges(n, lambda s, _n=n: rt.route(_n, s), {t: t for t in targets})
    g.add_edge("respond", LG_END)
    return g.compile().invoke(state, {"recursion_limit": 120})


def build_graph(rt: AgentRuntime):
    """The compiled LangGraph (for inspection / drawing: `build_graph(rt).get_graph().draw_mermaid()`)."""
    from langgraph.graph import END as LG_END, START, StateGraph

    g = StateGraph(AgentState)
    for n in NODES:
        g.add_node(n, _wrap(rt, n))
    g.add_edge(START, "understand")
    for n, targets in EDGES.items():
        g.add_conditional_edges(n, lambda s, _n=n: rt.route(_n, s), {t: t for t in targets})
    g.add_edge("respond", LG_END)
    return g.compile()


def run_agent(rt: AgentRuntime, state: AgentState, engine: str = "auto") -> AgentState:
    """engine: 'langgraph' | 'simple' | 'auto' (LangGraph when installed, else the built-in loop)."""
    if engine in ("auto", "langgraph"):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            if engine == "langgraph":
                raise
        else:
            return _run_langgraph(rt, state)
    return _run_simple(rt, state)
