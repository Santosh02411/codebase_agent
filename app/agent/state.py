from __future__ import annotations
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    repo_id: str
    allow_fix: bool        # /debug and /generate-fix may propose a patch; /chat never does
    allow_verify: bool     # run tests before/after the patch
    intent: str            # explain | debug
    queries: list[str]
    context: list[dict]
    retrieval_rounds: int
    need_more: bool
    analysis: dict
    edit: dict | None
    diff: str
    fix_error: str
    attempts: int
    test_before: dict | None
    test_after: dict | None
    steps: list[dict]
    answer: str
    status: str            # answered | fix_verified | fix_failed | fix_unverified | no_fix


def new_state(question: str, repo_id: str, allow_fix: bool = False, allow_verify: bool = True) -> AgentState:
    return AgentState(question=question, repo_id=repo_id, allow_fix=allow_fix, allow_verify=allow_verify,
                      intent="explain", queries=[], context=[], retrieval_rounds=0, need_more=False,
                      analysis={}, edit=None, diff="", fix_error="", attempts=0, test_before=None,
                      test_after=None, steps=[], answer="", status="answered")


def log(state: AgentState, node: str, message: str, **extra: Any) -> list[dict]:
    return state.get("steps", []) + [{"node": node, "message": message, **extra}]
