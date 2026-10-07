from app.llm.base import LLM


class ScriptedLLM(LLM):
    """Test double: returns pre-scripted JSON per task (lists are consumed in order)."""
    name = "scripted"

    def __init__(self, script):
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in script.items()}
        self.calls = []

    def text(self, system, prompt):
        return ""

    def json(self, task, system, prompt, hints=None):
        self.calls.append(task)
        v = self.script[task]
        return v.pop(0) if isinstance(v, list) else v


FIX_SCRIPT = {
    "analyze_query": {"intent": "debug", "queries": ["calculate_delivery_eta", "speed_kmh None"]},
    "analyze": {"need_more": False, "follow_up_queries": [], "answer": "speed_kmh may be None.",
                "root_cause": "calculate_delivery_eta divides by speed_kmh, which is None when the client omits it.",
                "affected_file": "services/eta.py", "affected_function": "calculate_delivery_eta"},
    "generate_fix": {"file": "services/eta.py", "search": "    return round(distance_km / speed_kmh * 60)",
                     "replace": "    speed_kmh = speed_kmh or DEFAULT_SPEED_KMH\n    return round(distance_km / speed_kmh * 60)",
                     "explanation": "default the speed"},
}
