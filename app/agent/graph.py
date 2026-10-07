from __future__ import annotations
from .nodes import END, AgentRuntime
from .state import AgentState

NODES = ["analyze_query", "retrieve", "analyze", "generate_fix", "verify", "respond"]


def _run_simple(rt: AgentRuntime, state: AgentState) -> AgentState:
    node, guard = "analyze_query", 0
    while node != END and guard < 40:
        state.update(getattr(rt, node)(state))
        node = rt.route(node, state)
        guard += 1
    return state


def _run_langgraph(rt: AgentRuntime, state: AgentState) -> AgentState:
    from langgraph.graph import END as LG_END, StateGraph

    g = StateGraph(AgentState)
    for n in NODES:
        g.add_node(n, getattr(rt, n))
    g.set_entry_point("analyze_query")
    for n in NODES[:-1]:
        g.add_conditional_edges(n, lambda s, _n=n: rt.route(_n, s))
    g.add_edge("respond", LG_END)
    return g.compile().invoke(state)


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
