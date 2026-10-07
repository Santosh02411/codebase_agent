from __future__ import annotations
from .base import LLM


class GeminiLLM(LLM):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "") -> None:
        from google import genai  # lazy import: optional dependency

        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.model = model or "gemini-2.0-flash"  # override with LLM_MODEL

    def text(self, system: str, prompt: str) -> str:
        cfg = self._genai.types.GenerateContentConfig(system_instruction=system, temperature=0.1)
        r = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
        return r.text or ""
