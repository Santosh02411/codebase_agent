from __future__ import annotations
from ..config import get_settings
from .base import LLM, extract_json
from .mock import MockLLM


def get_llm(provider: str | None = None) -> LLM:
    """llm = get_llm("gemini") / get_llm("openai") / get_llm("mock") — provider is swappable per call."""
    s = get_settings()
    provider = (provider or s.llm_provider).lower()
    if provider == "mock":
        return MockLLM()
    if provider == "openai":
        from .openai_llm import OpenAILLM

        if not s.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        return OpenAILLM(s.openai_api_key, s.llm_model)
    if provider == "gemini":
        from .gemini_llm import GeminiLLM

        if not s.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        return GeminiLLM(s.gemini_api_key, s.llm_model)
    raise ValueError(f"unknown LLM provider: {provider}")


__all__ = ["LLM", "MockLLM", "get_llm", "extract_json"]
