from app.llm.base import LLM
from app.llm.types import LLMResponse, ToolCall


class ScriptedLLM(LLM):
    """Test double: returns pre-scripted JSON per task (lists are consumed in order).
    Tasks without a script answer {} so the agent's defaults apply (pass strict=True to fail instead).
    Function-calling turns come from script["research"]: a list of {"tool_calls": [{"name", "args"}], "text": ""}; none left = no tool call."""
    name = "scripted"
    default_model = "scripted"

    supports_images = True

    def __init__(self, script, strict=False, tools=False, **kw):
        super().__init__(**kw)
        self.supports_tools = tools           # True: the coder drives generate_patch / apply_patch through script["code"]
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in script.items()}
        self.strict = strict
        self.calls, self.prompts = [], []

    def _complete(self, req, model):
        self.calls.append(req.task)
        v = self.script.get(req.task)
        step = v.pop(0) if isinstance(v, list) and v else None
        if not step:
            return LLMResponse(text="done")
        calls = [ToolCall(f"c{i}", c["name"], c.get("args", {})) for i, c in enumerate(step.get("tool_calls", []))]
        self.requests = getattr(self, "requests", []) + [req]
        return LLMResponse(text=step.get("text", ""), tool_calls=calls)

    def text(self, system, prompt, task="text"):
        return ""

    def json(self, task, system, prompt, hints=None, schema=None):
        def go():
            self.calls.append(task)
            self.prompts.append((task, prompt))
            if task not in self.script:
                if self.strict:
                    raise KeyError(task)
                return {}
            v = self.script[task]
            out = v.pop(0) if isinstance(v, list) else v
            return schema.model_validate(out).model_dump() if schema is not None else out
        return self.local_call(task, go, prompt)


FIX_SCRIPT = {
    "understand": {"intent": "debug", "queries": ["calculate_delivery_eta", "speed_kmh None"]},
    "analyze": {"need_more": False, "follow_up_queries": [], "answer": "speed_kmh may be None.",
                "root_cause": "calculate_delivery_eta divides by speed_kmh, which is None when the client omits it.",
                "affected_file": "services/eta.py", "affected_function": "calculate_delivery_eta"},
    "generate_fix": {"file": "services/eta.py", "search": "    return round(distance_km / speed_kmh * 60)",
                     "replace": "    speed_kmh = speed_kmh or DEFAULT_SPEED_KMH\n    return round(distance_km / speed_kmh * 60)",
                     "explanation": "default the speed"},
}
