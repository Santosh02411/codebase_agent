from __future__ import annotations
import itertools
import json
import re

from .base import LLM
from .types import LLMRequest, LLMResponse, ToolCall, Usage


class GeminiLLM(LLM):
    """Google Gemini via google-genai: function calling + JSON mode + usage metadata."""
    name = "gemini"
    default_model = "gemini-2.0-flash"  # override with LLM_MODEL

    def __init__(self, api_key: str = "", model: str = "", *, client=None, genai=None, **kw) -> None:
        super().__init__(model, **kw)
        self._auto = not model                         # no LLM_MODEL configured: pick a current model for this key instead of trusting a built-in name that may be retired
        if genai is None:
            from google import genai as _genai  # lazy import: optional dependency
            genai = _genai
        self._genai = genai
        self.client = client or genai.Client(api_key=api_key)
        self._ids = itertools.count(1)

    @staticmethod
    def _pref_path():
        try:
            from ..config import get_settings
            return get_settings().data_dir / "llm_model.json"
        except Exception:                            # noqa: BLE001
            return None

    def _remember(self, model: str) -> None:
        """Keep the model that worked, so the next start does not repeat the failed attempts."""
        p = self._pref_path()
        try:
            if p is not None:
                p.parent.mkdir(parents=True, exist_ok=True)
                data = json.loads(p.read_text()) if p.is_file() else {}
                data["gemini"] = model
                p.write_text(json.dumps(data))
        except Exception:                            # noqa: BLE001 - best effort
            pass

    def _resolve_auto(self) -> None:
        if not getattr(self, "_auto", False):
            return
        self._auto = False
        p = self._pref_path()
        try:
            if p is not None and p.is_file():
                m = json.loads(p.read_text()).get("gemini")
                if m:
                    self.model = m
                    return
        except Exception:                            # noqa: BLE001
            pass
        ranked = self._ranked()
        if ranked:
            self.model = ranked[0]

    def _ranked(self) -> list[str]:
        """Models this key can call, best general-purpose Flash model first (cached for the process)."""
        if getattr(self, "_model_cache", None) is not None:
            return self._model_cache
        names: list[str] = []
        try:
            for m in self.client.models.list():
                nm = getattr(m, "name", "") or ""
                acts = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or ["generateContent"]
                if nm.startswith("models/gemini") and "generateContent" in acts:
                    names.append(nm.removeprefix("models/"))
        except Exception:                            # noqa: BLE001 - listing is best effort
            return []
        def rank(n: str):
            ver = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            bad_kind = any(x in n for x in ("lite", "image", "tts", "live", "audio", "embedding", "robotics", "computer-use", "preview", "exp", "thinking", "vision", "learnlm", "gemma", "-8b"))
            return (not bad_kind, "flash" in n, float(ver.group(1)) if ver else 0.0, -len(n))
        self._model_cache = sorted(names, key=rank, reverse=True)
        return self._model_cache

    @staticmethod
    def _overloaded(exc: Exception) -> bool:
        """Errors another model may not have: overloaded (503), timed out (504), or this model's quota used up (429 RESOURCE_EXHAUSTED: quotas are per model)."""
        m = str(exc).lower()
        return any(x in m for x in ("503", "unavailable", "high demand", "504", "deadline", "overloaded", "timed out", "timeout", "429", "resource_exhausted", "quota"))

    def _replacement_model(self, bad: str, exc: Exception) -> str | None:
        """Google retires model names. When the configured one is gone (404 / "no longer available"), ask the API which models this key can use, switch to the newest
        general-purpose Flash model for the rest of the run, and tell the user. Returns the new model name, or None when this is some other error."""
        msg = str(exc).lower()
        if not ("no longer available" in msg or "not found" in msg or "404" in msg) or getattr(self, "_switched", 0) >= 2:
            return None
        names = self._ranked()
        if not names:
            return None
        cands = [n for n in names if n != bad.removeprefix("models/")]
        if not cands:
            return None
        best = cands[0]
        self._switched = getattr(self, "_switched", 0) + 1
        if self.model == bad:
            self.model = best
        if self.fast_model == bad:
            self.fast_model = best
        self._emit({"type": "llm", "phase": "note", "provider": self.name, "model": best, "message": f"Model {bad} is no longer available; switched to {best}. Set LLM_MODEL={best} in .env to make this permanent."})
        return best

    def _contents(self, req: LLMRequest) -> list:
        t = self._genai.types
        out: list = []
        for m in req.messages:
            if m.role == "assistant":
                # echo the provider's own content object when we have it: Gemini needs its thought signatures on function calls
                if m.raw is not None and isinstance(m.raw, t.Content):
                    out.append(m.raw)
                    continue
                parts = ([t.Part(text=m.content)] if m.content else []) + [t.Part(function_call=t.FunctionCall(name=c.name, args=c.args)) for c in m.tool_calls]
                out.append(t.Content(role="model", parts=parts or [t.Part(text="")]))
            elif m.role == "tool":
                part = t.Part.from_function_response(name=m.name or "tool", response={"result": m.content})
                if out and out[-1].role == "user" and out[-1].parts and out[-1].parts[0].function_response is not None:
                    out[-1].parts.append(part)   # several results to one multi-call turn travel together
                else:
                    out.append(t.Content(role="user", parts=[part]))
            else:
                import base64
                parts = [t.Part(text=m.content)] + [t.Part.from_bytes(data=base64.b64decode(i["data"]), mime_type=i["media_type"]) for i in m.images]
                out.append(t.Content(role="user", parts=parts))
        return out

    def _complete(self, req: LLMRequest, model: str) -> LLMResponse:
        t = self._genai.types
        cfg: dict = {"system_instruction": req.system or None, "temperature": req.temperature, "max_output_tokens": req.max_tokens,
                     "http_options": t.HttpOptions(timeout=int(self.timeout * 1000))}
        if req.tools:
            cfg["tools"] = [t.Tool(function_declarations=[t.FunctionDeclaration(name=x.name, description=x.description,
                                                                                parameters_json_schema=x.parameters) for x in req.tools])]
            cfg["automatic_function_calling"] = t.AutomaticFunctionCallingConfig(disable=True)   # the agent runs the tools, not the SDK
            cfg["tool_config"] = t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode="ANY" if req.require_tool else "AUTO"))
        elif req.json_mode:
            cfg["response_mime_type"] = "application/json"
        def call(m: str):
            return self.client.models.generate_content(model=m, contents=self._contents(req), config=t.GenerateContentConfig(**cfg))
        self._resolve_auto()
        model = self.model if model == self.default_model and self.model != self.default_model else model
        try:
            r = call(model)
        except Exception as e:                       # noqa: BLE001
            newer = self._replacement_model(model, e)
            if newer:
                model = newer
                r = call(model)
                self._remember(model)
            elif self._overloaded(e) and getattr(self, "_alt_tries", 0) < 12:
                # this model is overloaded, timing out or out of quota: try the next-best models right away instead of waiting and retrying the same one
                last: Exception = e
                r = None
                for alt in [m for m in self._ranked() if m != model][:3]:
                    self._alt_tries = getattr(self, "_alt_tries", 0) + 1
                    self._emit({"type": "llm", "phase": "note", "provider": self.name, "model": alt, "message": f"{model} failed ({str(last)[:60]}); trying {alt}."})
                    try:
                        r = call(alt)
                    except Exception as e2:          # noqa: BLE001
                        last = e2
                        if not self._overloaded(e2):
                            raise
                        continue
                    if "quota" in str(e).lower() or "resource_exhausted" in str(e).lower():
                        self.model = alt             # this key has no quota left on the old model: stay on the one that works
                        self._remember(alt)
                    model = alt
                    break
                if r is None:
                    raise last
            else:
                raise
        text, calls, content = "", [], None
        cands = getattr(r, "candidates", None) or []
        if cands and getattr(cands[0], "content", None) is not None:
            content = cands[0].content
            for p in content.parts or []:
                if getattr(p, "function_call", None):
                    fc = p.function_call
                    calls.append(ToolCall(getattr(fc, "id", None) or f"call_{next(self._ids)}", fc.name, dict(fc.args or {})))
                elif getattr(p, "text", None) and not getattr(p, "thought", False):
                    text += p.text
        if not text and not calls:
            text = getattr(r, "text", None) or ""
        u = getattr(r, "usage_metadata", None)
        usage = Usage(getattr(u, "prompt_token_count", 0) or 0,
                      (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)) if u else Usage()
        reason = str(getattr(cands[0], "finish_reason", "") or "") if cands else ""
        return LLMResponse(text=text, tool_calls=calls, model=model, usage=usage, finish_reason=reason, raw=content)
