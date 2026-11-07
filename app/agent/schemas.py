"""Structured outputs of each agent role. Every model is lenient on purpose (coerces, defaults, ignores extras): the goal is to
turn a slightly-off model answer into a valid one, and to repair what can't be coerced, not to reject on style."""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

INTENTS = ("explain", "debug", "change", "tests", "review", "docs", "pr")
AGENTS = ("researcher", "debugger", "coder", "tester", "reviewer", "documenter")


def _strs(v: Any, limit: int = 5) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if isinstance(x, (str, int, float)) and str(x).strip()][:limit]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Understanding(_Base):
    intent: str = "explain"
    summary: str = ""
    queries: list[str] = []
    symbols: list[str] = []
    files: list[str] = []
    errors: list[str] = []
    follow_up: bool = False
    complexity: str = "moderate"

    @field_validator("queries", "symbols", "files", "errors", mode="before")
    @classmethod
    def _l(cls, v):
        return _strs(v, 6)

    @field_validator("intent", mode="before")
    @classmethod
    def _i(cls, v):
        v = str(v or "").lower().strip()
        aliases = {"bug": "debug", "fix": "debug", "debugging": "debug", "implement": "change", "feature": "change", "refactor": "change",
                   "test": "tests", "testing": "tests", "document": "docs", "documentation": "docs", "architecture": "docs"}
        v = aliases.get(v, v)
        return v if v in INTENTS else "explain"

    @field_validator("complexity", mode="before")
    @classmethod
    def _c(cls, v):
        v = str(v or "").lower()
        return v if v in ("simple", "moderate", "complex") else "moderate"


class PlanStep(_Base):
    agent: str = "researcher"
    goal: str = ""

    @field_validator("agent", mode="before")
    @classmethod
    def _a(cls, v):
        v = str(v or "").lower().strip()
        aliases = {"planner": "researcher", "analyst": "debugger", "code_researcher": "researcher", "doc": "documenter",
                   "documentation": "documenter", "docs": "documenter", "test": "tester", "review": "reviewer", "code": "coder"}
        v = aliases.get(v, v)
        return v if v in AGENTS else "researcher"


class Plan(_Base):
    steps: list[PlanStep] = []
    needs_patch: bool | None = None
    needs_review: bool | None = None
    needs_regression_test: bool | None = None
    needs_docs: bool | None = None
    rationale: str = ""

    @field_validator("steps", mode="before")
    @classmethod
    def _s(cls, v):
        out = []
        for x in v if isinstance(v, list) else []:
            if isinstance(x, str):
                out.append({"agent": x})
            elif isinstance(x, dict):
                out.append(x)
        return out[:8]


class Analysis(_Base):
    need_more: bool = False
    follow_up_queries: list[str] = []
    answer: str = ""
    root_cause: str = ""
    affected_file: str = ""
    affected_function: str = ""
    confidence: str = "medium"

    @field_validator("follow_up_queries", mode="before")
    @classmethod
    def _q(cls, v):
        return _strs(v, 3)

    @field_validator("answer", "root_cause", "affected_file", "affected_function", mode="before")
    @classmethod
    def _s(cls, v):
        return "" if v is None else str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        v = str(v or "").lower()
        return v if v in ("low", "medium", "high") else "medium"


class Edit(_Base):
    file: str
    search: str
    replace: str = ""


class NewFile(_Base):
    path: str
    content: str


class Rewrite(_Base):
    path: str
    content: str


class CodeChange(_Base):
    edits: list[Edit] = []
    new_files: list[NewFile] = []
    delete_files: list[str] = []
    rewrites: list[Rewrite] = []
    unified_diff: str = ""
    explanation: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, d):
        # the original single-edit shape {"file","search","replace"} is still accepted
        if isinstance(d, dict) and d.get("file") and d.get("search") and not d.get("edits"):
            d = {**d, "edits": [{"file": d["file"], "search": d["search"], "replace": d.get("replace", "")}]}
        return d

    @field_validator("edits", "new_files", "rewrites", mode="before")
    @classmethod
    def _items(cls, v):
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    @field_validator("delete_files", mode="before")
    @classmethod
    def _dels(cls, v):
        return _strs(v, 5)

    @field_validator("unified_diff", mode="before")
    @classmethod
    def _diff(cls, v):
        return "" if v is None else str(v)

    @field_validator("edits", "new_files", "rewrites", mode="after")
    @classmethod
    def _drop_empty(cls, v):
        return [x for x in v if (getattr(x, "search", None) or getattr(x, "content", None) is not None) and (getattr(x, "file", None) or getattr(x, "path", None))]


class Reflection(_Base):
    action: str = "retry_code"
    reason: str = ""
    queries: list[str] = []
    culprit: str = "test"          # when generated tests fail: is the TEST wrong, or did it expose a bug in the IMPLEMENTATION?

    @field_validator("culprit", mode="before")
    @classmethod
    def _culprit(cls, v):
        v = str(v or "").lower().strip()
        return v if v in ("test", "implementation") else "test"

    @field_validator("action", mode="before")
    @classmethod
    def _a(cls, v):
        v = str(v or "").lower().strip()
        return v if v in ("retry_code", "research_more", "stop") else "retry_code"

    @field_validator("queries", mode="before")
    @classmethod
    def _q(cls, v):
        return _strs(v, 3)


class Finding(_Base):
    file: str = ""
    line: int = 0
    severity: str = "low"
    confidence: str = "medium"
    message: str = ""
    evidence: str = ""
    fix: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        v = str(v or "").lower()
        return v if v in ("high", "medium", "low") else "medium"

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        v = str(v or "").lower()
        return v if v in ("high", "medium", "low") else "low"

    @field_validator("line", mode="before")
    @classmethod
    def _l(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @field_validator("file", "message", "evidence", "fix", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v)


class Review(_Base):
    approved: bool = True
    summary: str = ""
    feedback: str = ""
    findings: list[Finding] = []

    @field_validator("findings", mode="before")
    @classmethod
    def _f(cls, v):
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


class Docs(_Base):
    summary: str = ""
    changelog: str = ""

    @field_validator("summary", "changelog", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v)


class PRConcern(_Base):
    file: str = ""
    line: int = 0
    severity: str = "low"
    message: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        v = str(v or "").lower()
        return v if v in ("high", "medium", "low") else "low"

    @field_validator("line", mode="before")
    @classmethod
    def _l(cls, v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    @field_validator("file", "message", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v)


class PRAnalysis(_Base):
    summary: str = ""
    change_type: str = "mixed"
    risk: str = "medium"
    risk_reasons: list[str] = []
    key_changes: list[dict] = []
    impact: list[str] = []
    test_assessment: str = ""
    concerns: list[PRConcern] = []
    questions: list[str] = []

    @field_validator("risk", mode="before")
    @classmethod
    def _r(cls, v):
        v = str(v or "").lower()
        return v if v in ("low", "medium", "high") else "medium"

    @field_validator("risk_reasons", "impact", "questions", mode="before")
    @classmethod
    def _l(cls, v):
        return _strs(v, 8)

    @field_validator("key_changes", mode="before")
    @classmethod
    def _k(cls, v):
        return [x for x in v if isinstance(x, dict)][:12] if isinstance(v, list) else []

    @field_validator("concerns", mode="before")
    @classmethod
    def _c(cls, v):
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


class ReviewComment(_Base):
    path: str = ""
    line: int = 0
    severity: str = "medium"
    body: str = ""

    @field_validator("line", mode="before")
    @classmethod
    def _l(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        v = str(v or "").lower()
        return v if v in ("high", "medium", "low", "nit") else "medium"

    @field_validator("path", "body", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v)


class ReviewDraft(_Base):
    verdict: str = "comment"
    summary: str = ""
    comments: list[ReviewComment] = []

    @field_validator("verdict", mode="before")
    @classmethod
    def _v(cls, v):
        v = str(v or "").lower().replace(" ", "_")
        return v if v in ("approve", "comment", "request_changes") else "comment"

    @field_validator("comments", mode="before")
    @classmethod
    def _c(cls, v):
        return [x for x in v if isinstance(x, dict)][:40] if isinstance(v, list) else []


class CommitMessage(_Base):
    subject: str = ""
    body: str = ""

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v).strip()


class PRDescription(_Base):
    title: str = ""
    body: str = ""

    @field_validator("title", "body", mode="before")
    @classmethod
    def _t(cls, v):
        return "" if v is None else str(v).strip()
