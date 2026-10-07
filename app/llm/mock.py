from __future__ import annotations
import re
from .base import LLM

_DEBUG = re.compile(r"\b(error|bug|fail|failing|failed|exception|traceback|crash|500|fix|broken|wrong)\b", re.I)
_STOP = {"where", "what", "how", "why", "does", "this", "that", "with", "from", "when", "which", "the", "are", "after"}


class MockLLM(LLM):
    """Offline, deterministic stand-in so the whole pipeline runs without API keys.
    It does retrieval-only analysis and cannot generate patches."""

    name = "mock"

    def text(self, system: str, prompt: str) -> str:
        return "[mock-llm] No real LLM configured. Set LLM_PROVIDER=gemini or openai."

    def json(self, task: str, system: str, prompt: str, hints: dict | None = None) -> dict:
        hints = hints or {}
        if task == "analyze_query":
            q = hints.get("question", "")
            idents = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", q) if w.lower() not in _STOP][:4]
            return {"intent": "debug" if _DEBUG.search(q) else "explain", "queries": [q] + idents}
        if task == "analyze":
            files = hints.get("files", [])
            return {
                "need_more": False,
                "follow_up_queries": [],
                "answer": "(mock LLM) Retrieval-only result. Most relevant files: " + ", ".join(files[:5]),
                "root_cause": "",
                "affected_file": files[0] if files else "",
                "affected_function": "",
            }
        if task == "generate_fix":
            return {"file": "", "search": "", "replace": "", "explanation": "mock LLM cannot generate patches"}
        return {}
