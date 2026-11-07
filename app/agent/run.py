from __future__ import annotations
from .graph import run_agent
from .memory import ConversationStore
from .nodes import AgentRuntime
from .state import AgentState, new_state


def run_task(llm, tools, settings, *, repo_id: str = "", mode: str = "chat", text: str = "", target: str = "", allow_fix: bool = False,
             allow_verify: bool = True, conversation_id: str = "", store: ConversationStore | None = None, engine: str = "auto",
             images: list[dict] | None = None, pr: dict | None = None) -> AgentState:
    """One agent run through the LangGraph workflow, for any mode (chat, debug, fix, change, tests, review, architecture)."""
    store = store or ConversationStore(None)
    history = store.render(conversation_id, settings.history_turns, settings.history_token_budget) if conversation_id else ""
    rt = AgentRuntime(llm, tools, settings, store)
    st = new_state(text, repo_id, allow_fix, allow_verify, mode=mode, target=target, conversation_id=conversation_id, history=history, images=images, pr=pr)
    return run_agent(rt, st, engine)


def run_summary(st: AgentState, llm) -> dict:
    """The observability block every response carries: what the agent planned, how much context it used, what the model calls cost."""
    return {"plan": {**(st.get("plan") or {}), "intent": st.get("intent")}, "context": st.get("context_report") or {},
            "usage": llm.usage.summary(), "tool_calls": st.get("tool_calls_used", 0), "retrieval_rounds": st.get("retrieval_rounds", 0),
            "attempts": st.get("attempts", 0)}
