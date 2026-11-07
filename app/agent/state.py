from __future__ import annotations
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # ---- request ----
    question: str
    repo_id: str
    mode: str              # chat | debug | fix | change | tests | review | architecture
    target: str            # file for tests / review
    conversation_id: str
    history: str           # rendered conversation memory (already budgeted)
    allow_fix: bool        # may propose a patch (/debug, /generate-fix, /change, /generate-tests; never /chat)
    allow_verify: bool     # run tests before/after the patch
    images: list[dict]     # attached screenshots [{media_type, data(base64)}]; read by a vision model into text
    # ---- understanding & plan ----
    intent: str            # explain | debug | change | tests | review | docs
    understanding: dict
    entities: dict         # {symbols, files, errors}: what the request names
    frames: list[dict]     # stack frames that resolve to repository files (outermost first)
    error_report: dict     # structured error facts: exception type, message, file, line, function, variables, stack, related functions
    plan: dict             # {steps, needs_patch, needs_tester, needs_review, needs_regression_test, needs_docs, rationale}
    # ---- research ----
    queries: list[str]     # pending follow-up searches
    evidence: list[dict]   # everything the researcher found (deduplicated)
    context: list[dict]    # the packed, budgeted subset the models are shown ([n] citation ids index into this)
    context_report: dict
    tool_calls_used: int
    retrieval_rounds: int
    need_more: bool
    # ---- reasoning ----
    analysis: dict
    citations: dict        # {"cited": [1, 3], "invalid": []}: markers the answer used, validated against the context
    # ---- change ----
    edits: list[dict]
    new_files: list[dict]
    edit: dict | None      # the single edit when the patch is exactly one edit (kept for /apply-patch and older clients)
    delete_files: list[str]
    spec: dict             # the whole patch spec {edits, new_files, delete_files, rewrites, unified_diff}: what the engine builds and the sandbox applies
    patch_files: list[dict]  # per-file summary {path, op, additions, deletions, fuzzy, notes}
    explanation: str
    diff: str
    final_files: dict
    fix_error: str
    proposed: bool         # the coder proposed something (valid or not) on its latest attempt
    attempts: int
    # ---- verification ----
    test_before: dict | None
    test_after: dict | None
    lint_before: dict | None
    lint_after: dict | None
    lint_new: list[dict]
    regression: dict | None      # {tests, before, failed_before, passed_after}: a new test that reproduces the problem
    verification: dict | None    # judge(): resolved | partial | no_regressions | unverified | not_resolved, with reasons
    test_patterns: dict          # how this repository writes tests (framework, naming, fixtures, a sample)
    impl_change: bool            # a tests run changed implementation code because a test exposed a bug
    coverage_delta: dict | None  # coverage before / after for the files under test
    pr: dict                     # pull request context (GitHub metadata, diff, valid comment lines): pr_analyze / pr_review modes
    pr_report: dict              # the analysis or the review draft
    repro_note: str              # what running the tests before any change showed
    affected_files: list[dict]   # [{path, role, detail}]
    review: dict | None
    review_rounds: int
    reflection: dict
    review_report: dict    # review intent: {summary, findings}
    docs: str
    facts: dict
    # ---- output ----
    steps: list[dict]
    step_count: int
    answer: str
    status: str            # answered | reviewed | fix_verified | fix_failed | fix_unverified | no_fix | error
    error: str


def new_state(question: str, repo_id: str, allow_fix: bool = False, allow_verify: bool = True, *, mode: str = "chat",
              target: str = "", conversation_id: str = "", history: str = "", images: list[dict] | None = None, pr: dict | None = None) -> AgentState:
    return AgentState(question=question, repo_id=repo_id, mode=mode, target=target or "", conversation_id=conversation_id or "",
                      history=history, allow_fix=allow_fix, allow_verify=allow_verify, images=images or [], intent="explain", understanding={}, error_report={},
                      entities={"symbols": [], "files": [], "errors": []}, frames=[], plan={}, queries=[], evidence=[], context=[],
                      context_report={}, tool_calls_used=0, retrieval_rounds=0, need_more=False, analysis={}, edits=[], new_files=[],
                      edit=None, delete_files=[], spec={}, patch_files=[], explanation="", diff="", final_files={}, fix_error="", proposed=False, attempts=0,
                      test_before=None, test_after=None, lint_before=None, lint_after=None, lint_new=[], regression=None, verification=None, pr=pr or {}, pr_report={}, test_patterns={}, impl_change=False, coverage_delta=None, repro_note="",
                      affected_files=[], review=None, review_rounds=0, reflection={}, review_report={}, docs="", facts={}, steps=[],
                      step_count=0, answer="", status="answered", error="")


def log(state: AgentState, node: str, message: str, **extra: Any) -> list[dict]:
    return state.get("steps", []) + [{"node": node, "message": message, **extra}]
