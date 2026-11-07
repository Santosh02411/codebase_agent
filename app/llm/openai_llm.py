from __future__ import annotations
import json

from .base import LLM
from .types import LLMRequest, LLMResponse, Message, ToolCall, Usage

# reasoning-family models reject a custom temperature
_NO_TEMPERATURE = ("o1", "o3", "o4", "gpt-5")


class OpenAILLM(LLM):
    """OpenAI chat completions (also any OpenAI-compatible server via base_url): function calling + JSON mode + usage."""
    name = "openai"
    default_model = "gpt-4o-mini"  # override with LLM_MODEL

    def __init__(self, api_key: str = "", model: str = "", *, base_url: str | None = None, client=None, **kw) -> None:
        super().__init__(model, **kw)
        if client is None:
            from openai import OpenAI  # lazy import: optional dependency
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout, max_retries=0)  # retries are ours
        self.client = client

    @staticmethod
    def to_messages(req: LLMRequest) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": req.system}] if req.system else []
        for m in req.messages:
            if m.role == "assistant" and m.tool_calls:
                out.append({"role": "assistant", "content": m.content or None,
                            "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                                           for c in m.tool_calls]})
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content})
            elif m.images:
                out.append({"role": m.role, "content": [{"type": "text", "text": m.content}] + [
                    {"type": "image_url", "image_url": {"url": f"data:{i['media_type']};base64,{i['data']}"}} for i in m.images]})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _kwargs(self, req: LLMRequest, model: str) -> dict:
        kw: dict = {"model": model, "messages": self.to_messages(req), "max_completion_tokens": req.max_tokens, "timeout": self.timeout}
        if req.temperature is not None and not model.lower().startswith(_NO_TEMPERATURE):
            kw["temperature"] = req.temperature
        if req.tools:
            kw["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                           for t in req.tools]
            kw["tool_choice"] = "required" if req.require_tool else "auto"
        elif req.json_mode:
            kw["response_format"] = {"type": "json_object"}
        return kw

    def _complete(self, req: LLMRequest, model: str) -> LLMResponse:
        kw = self._kwargs(req, model)
        try:
            r = self.client.chat.completions.create(**kw)
        except Exception as e:  # noqa: BLE001 - some models / compatible servers reject a parameter: retry once without it
            msg = str(e).lower()
            for param, alt in (("max_completion_tokens", "max_tokens"), ("temperature", None)):
                if param in msg and param in kw and ("unsupported" in msg or "not supported" in msg or "unrecognized" in msg or "unknown" in msg):
                    val = kw.pop(param)
                    if alt:
                        kw[alt] = val
                    r = self.client.chat.completions.create(**kw)
                    break
            else:
                raise
        choice = r.choices[0]
        msg = choice.message
        calls = []
        for c in getattr(msg, "tool_calls", None) or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_arguments": c.function.arguments}
            calls.append(ToolCall(c.id, c.function.name, args if isinstance(args, dict) else {"value": args}))
        u = getattr(r, "usage", None)
        return LLMResponse(text=msg.content or "", tool_calls=calls, model=getattr(r, "model", model) or model,
                           usage=Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0) if u else Usage(),
                           finish_reason=choice.finish_reason or "", raw=msg)
