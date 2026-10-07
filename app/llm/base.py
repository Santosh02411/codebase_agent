from __future__ import annotations
import json
import re


class LLM:
    """Provider-agnostic LLM interface. Implement `text`; `json` is derived from it."""

    name = "base"

    def text(self, system: str, prompt: str) -> str:
        raise NotImplementedError

    def json(self, task: str, system: str, prompt: str, hints: dict | None = None) -> dict:
        # `task` and `hints` are only used by the offline MockLLM / test doubles.
        raw = self.text(system + "\nRespond with a single valid JSON object and nothing else.", prompt)
        return extract_json(raw)


def extract_json(raw: str) -> dict:
    raw = raw.strip()
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
