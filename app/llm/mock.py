from __future__ import annotations
import re

from .base import LLM
from .types import LLMRequest, LLMResponse, ToolCall

_DEBUG = re.compile(r"\b(error|bug|fail|failing|failed|exception|traceback|crash|500|fix|broken|wrong)\b", re.I)
_STOP = {"where", "what", "how", "why", "does", "this", "that", "with", "from", "when", "which", "the", "are", "after", "walk", "through", "request", "flow", "getting", "explain", "tell", "about", "there", "error"}


class MockLLM(LLM):
    """Offline, deterministic stand-in so the whole pipeline runs without API keys.
    It picks retrieval tools by a simple policy and does retrieval-only analysis; it cannot write patches."""

    name = "mock"
    default_model = "mock"
    supports_tools = False     # the mock only searches; it cannot drive a tool loop for patches
    supports_images = False

    def _complete(self, req: LLMRequest, model: str) -> LLMResponse:
        if req.task == "read_screenshot":
            return LLMResponse(text="")
        if req.task == "research" and req.tools:
            used = any(m.role == "tool" for m in req.messages)
            if used:
                return LLMResponse(text="Enough context gathered.")
            queries = [q for q in (req.hints.get("queries") or []) if isinstance(q, str)][:3] or [req.hints.get("question", "")]
            return LLMResponse(text="", tool_calls=[ToolCall(f"mock_{i}", "search_code", {"query": q, "k": 5}) for i, q in enumerate(queries) if q])
        return LLMResponse(text="[mock-llm] No real LLM configured. Set LLM_PROVIDER=gemini or openai.")

    def json(self, task: str, system: str, prompt: str, hints: dict | None = None, schema=None) -> dict:
        return self.local_call(task, lambda: self._json(task, hints or {}), prompt)

    def _json(self, task: str, hints: dict) -> dict:
        if task in ("understand", "analyze_query"):
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
        if task in ("generate_change", "generate_tests"):
            return {"edits": [], "new_files": [], "explanation": "mock LLM cannot generate code"}
        return {}
