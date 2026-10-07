from __future__ import annotations
from .base import LLM


class OpenAILLM(LLM):
    name = "openai"

    def __init__(self, api_key: str, model: str = "") -> None:
        from openai import OpenAI  # lazy import: optional dependency

        self.client = OpenAI(api_key=api_key)
        self.model = model or "gpt-4o-mini"  # override with LLM_MODEL

    def text(self, system: str, prompt: str) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content or ""
