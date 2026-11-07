"""Provider-agnostic LLM interface.

Providers implement ONE method, `_complete(request, model) -> LLMResponse`. Everything else lives here, once:
  * model selection per task (fast tier for planning / tool choice, strong tier for reasoning and code)
  * retries with exponential backoff + jitter (rate limits, timeouts, 5xx), optional fallback model/provider
  * token + latency tracking (provider-reported usage, estimated when absent), per-run call budget
  * structured output: JSON mode, pydantic validation and one automatic repair round-trip
  * observers, so the UI can show every model call live
`text()` and `json()` keep their old signatures, so existing callers (rerankers, eval generation) are unchanged.
"""
from __future__ import annotations
import json
import random
import re
import time
from typing import Callable

from .types import (LLMAuthError, LLMBadRequest, LLMBudgetExceeded, LLMContextTooLong, LLMError, LLMInvalidOutput, LLMRateLimit,
                    LLMRequest, LLMResponse, LLMTimeout, LLMUnavailable, Message, ToolSpec, Usage)
from .usage import GLOBAL_USAGE, CallRecord, UsageTracker

# Which tier answers which task. "fast" = planning, tool choice, short decisions; everything else uses the strong model.
TASK_TIER = {"understand": "fast", "plan": "fast", "research": "fast", "reflect": "fast", "rerank": "fast",
             "generate_question": "fast", "document": "fast", "text": "fast"}


def classify_exception(e: Exception) -> LLMError:
    """Map any SDK exception to our error types by duck-typing (so no SDK has to be imported)."""
    if isinstance(e, LLMError):
        return e
    name = type(e).__name__.lower()
    msg = str(e)
    low = msg.lower()
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    if not isinstance(status, int):
        status = None
    retry_after = None
    headers = getattr(getattr(e, "response", None), "headers", None)
    if headers is not None:
        try:
            retry_after = float(headers.get("retry-after")) if headers.get("retry-after") else None
        except (TypeError, ValueError):
            retry_after = None
    if status == 429 or "ratelimit" in name or "rate limit" in low or "resource_exhausted" in low or "quota" in low:
        return LLMRateLimit(msg, retry_after)
    if "timeout" in name or "timed out" in low or status in (408, 504):
        return LLMTimeout(msg)
    if status in (401, 403) or "authentication" in name or "permission" in name or "api key" in low and "invalid" in low:
        return LLMAuthError(msg)
    if "context_length" in low or "context length" in low or "maximum context" in low or "too many tokens" in low or "token limit" in low:
        return LLMContextTooLong(msg)
    if status is not None and 500 <= status < 600 or "connection" in name or "internalserver" in name or "unavailable" in low or "overloaded" in low:
        return LLMUnavailable(msg)
    if status is not None and 400 <= status < 500 or "badrequest" in name or "invalid" in name:
        return LLMBadRequest(msg)
    return LLMUnavailable(f"{type(e).__name__}: {msg}")  # unknown failure: treat as transient, the retry budget bounds it


class LLM:
    name = "base"
    default_model = ""
    supports_tools = True      # native function calling; offline doubles set this to False
    supports_images = True

    def __init__(self, model: str = "", *, fast_model: str = "", temperature: float = 0.1, max_tokens: int = 4096,
                 timeout: float = 60.0, max_retries: int = 3, fallbacks: "list[LLM] | None" = None,
                 tracker: UsageTracker | None = None, max_calls: int | None = None,
                 sleep: Callable[[float], None] = time.sleep, backoff: float = 0.5) -> None:
        self.model = model or self.default_model
        self.fast_model = fast_model
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self.max_retries, self.fallbacks, self.max_calls = max_retries, list(fallbacks or []), max_calls
        self.usage = tracker or UsageTracker(parent=GLOBAL_USAGE)
        self._sleep, self._backoff = sleep, backoff
        self._observers: list[Callable[[dict], None]] = []

    # ---- configuration ------------------------------------------------------------------------
    def model_for(self, task: str) -> str:
        if self.fast_model and TASK_TIER.get(task) == "fast":
            return self.fast_model
        return self.model

    def set_observer(self, cb: Callable[[dict], None] | None) -> None:
        self._observers = [cb] if cb else []

    def _emit(self, ev: dict) -> None:
        for cb in self._observers:
            try:
                cb(ev)
            except Exception:  # noqa: BLE001 - observers must never break a model call
                pass

    # ---- provider hook ------------------------------------------------------------------------
    def _complete(self, req: LLMRequest, model: str) -> LLMResponse:
        raise NotImplementedError

    # ---- the one public entry point -----------------------------------------------------------
    def complete(self, req: LLMRequest) -> LLMResponse:
        if self.max_calls is not None and self.usage.calls >= self.max_calls:
            raise LLMBudgetExceeded(f"LLM call budget of {self.max_calls} reached for this run")
        req.temperature = self.temperature if req.temperature is None else req.temperature
        req.max_tokens = req.max_tokens or self.max_tokens
        model = self.model_for(req.task)
        prompt_chars = len(req.system) + sum(len(m.content) for m in req.messages)   # images are not counted here
        t_all = time.time()
        last: LLMError | None = None
        providers: list[tuple[LLM, bool]] = [(self, False)] + [(f, True) for f in self.fallbacks]
        attempts = 0
        for prov, is_fb in providers:
            pmodel = model if not is_fb else prov.model_for(req.task)
            for attempt in range(1, (self.max_retries if prov is self else 1) + 1):
                attempts += 1
                self._emit({"type": "llm", "task": req.task, "model": pmodel, "provider": prov.name, "phase": "start",
                            "prompt_chars": prompt_chars, "attempt": attempt, "fallback": is_fb})
                t0 = time.time()
                try:
                    resp = prov._complete(req, pmodel)
                except Exception as exc:  # noqa: BLE001
                    err = classify_exception(exc)
                    ms = int((time.time() - t0) * 1000)
                    self.usage.record(CallRecord(req.task, prov.name, pmodel, latency_ms=ms, ok=False, error=f"{type(err).__name__}: {err}"[:300],
                                                 attempts=attempt, fallback=is_fb))
                    self._emit({"type": "llm", "task": req.task, "model": pmodel, "provider": prov.name, "phase": "error",
                                "error": str(err)[:200], "ms": ms, "retriable": err.retriable, "attempt": attempt})
                    last = err
                    if not err.retriable or attempt >= (self.max_retries if prov is self else 1):
                        break
                    delay = err.retry_after if isinstance(err, LLMRateLimit) and err.retry_after else self._backoff * (2 ** (attempt - 1))
                    self._sleep(min(delay, 30.0) + random.uniform(0, self._backoff / 2))
                    continue
                resp.latency_ms = int((time.time() - t0) * 1000)
                resp.model, resp.provider, resp.attempts, resp.fallback = resp.model or pmodel, prov.name, attempts, is_fb
                if not resp.usage.total:  # provider reported nothing: count ourselves, and say so
                    from ..rag.context import estimate_tokens
                    resp.usage = Usage(estimate_tokens(req.system + "".join(m.content for m in req.messages)),
                                       estimate_tokens(resp.text + "".join(json.dumps(c.args) for c in resp.tool_calls)), estimated=True)
                self.usage.record(CallRecord(req.task, prov.name, resp.model, resp.usage.input_tokens, resp.usage.output_tokens,
                                             resp.usage.estimated, resp.latency_ms, True, "", attempt, is_fb))
                self._emit({"type": "llm", "task": req.task, "model": resp.model, "provider": prov.name, "phase": "end",
                            "ms": resp.latency_ms, "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                            "tool_calls": len(resp.tool_calls), "fallback": is_fb, "attempts": attempts,
                            "total_ms": int((time.time() - t_all) * 1000)})
                return resp
            if isinstance(last, (LLMContextTooLong, LLMBadRequest)) and not is_fb and not self.fallbacks:
                break
        assert last is not None
        raise last

    def local_call(self, task: str, fn: Callable[[], dict], prompt: str = "") -> dict:
        """For offline doubles that answer `json()` without a provider: same events + accounting as a real call."""
        self._emit({"type": "llm", "task": task, "model": self.model, "provider": self.name, "phase": "start", "prompt_chars": len(prompt), "attempt": 1})
        t0 = time.time()
        out = fn()
        ms = int((time.time() - t0) * 1000)
        self.usage.record(CallRecord(task, self.name, self.model, latency_ms=ms))
        self._emit({"type": "llm", "task": task, "model": self.model, "provider": self.name, "phase": "end", "ms": ms,
                    "input_tokens": 0, "output_tokens": 0})
        return out

    # ---- convenience layers -------------------------------------------------------------------
    def chat(self, task: str, system: str, messages: list[Message], tools: list[ToolSpec] | None = None, *,
             hints: dict | None = None, require_tool: bool = False, **kw) -> LLMResponse:
        return self.complete(LLMRequest(task=task, system=system, messages=messages, tools=tools or [], hints=hints or {},
                                        require_tool=require_tool, **kw))

    def text(self, system: str, prompt: str, task: str = "text") -> str:
        return self.chat(task, system, [Message("user", prompt)]).text

    def json(self, task: str, system: str, prompt: str, hints: dict | None = None, schema=None) -> dict:
        """Structured output. `schema` is an optional pydantic model class: the reply is validated and normalised through it,
        and on failure the model gets ONE repair turn that quotes the problem. Raises LLMInvalidOutput if that fails too."""
        sys_ = system + "\nRespond with a single valid JSON object and nothing else (no prose, no markdown fences)."
        msgs = [Message("user", prompt)]
        problem = ""
        for attempt in (1, 2):
            resp = self.complete(LLMRequest(task=task, system=sys_, messages=msgs, json_mode=True, hints=hints or {}))
            try:
                data = extract_json(resp.text)
                return validate_json(data, schema)
            except ValueError as e:
                problem = str(e)
                self._emit({"type": "llm", "task": task, "model": resp.model, "phase": "repair", "error": problem[:200]})
                msgs = msgs + [Message("assistant", resp.text[:4000]),
                               Message("user", f"That reply was not usable: {problem[:400]}\nReply again with ONLY the corrected JSON object.")]
        raise LLMInvalidOutput(f"{task}: model did not return valid JSON ({problem[:200]})")


def validate_json(data, schema=None) -> dict:
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    if schema is None:
        return data
    try:
        return schema.model_validate(data).model_dump()
    except Exception as e:  # pydantic.ValidationError
        raise ValueError(str(e).splitlines()[0] + " | " + "; ".join(str(x) for x in str(e).splitlines()[1:3]))


def extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(raw[s : e + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError("LLM did not return valid JSON")
