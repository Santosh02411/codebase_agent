from __future__ import annotations
from ..config import get_settings
from .base import LLM, classify_exception, extract_json
from .mock import MockLLM
from .types import (LLMAuthError, LLMBadRequest, LLMBudgetExceeded, LLMContextTooLong, LLMError, LLMInvalidOutput, LLMRateLimit, LLMRequest,
                    LLMResponse, LLMTimeout, LLMUnavailable, Message, ToolCall, ToolSpec, Usage)
from .usage import GLOBAL_USAGE, UsageTracker, parse_prices

PROVIDERS = ("mock", "openai", "gemini")


def _build(provider: str, model: str, s, *, fallbacks=None, tracker=None) -> LLM:
    common = dict(fast_model=s.llm_fast_model, temperature=s.llm_temperature, max_tokens=s.llm_max_tokens, timeout=s.llm_timeout,
                  max_retries=s.llm_max_retries, fallbacks=fallbacks, tracker=tracker, max_calls=s.max_llm_calls)
    if provider == "mock":
        return MockLLM(**{**common, "fast_model": ""})
    if provider == "openai":
        from .openai_llm import OpenAILLM
        if not s.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        base = s.openai_base_url if s.openai_base_url and "api.openai.com" not in s.openai_base_url else None
        return OpenAILLM(s.openai_api_key, model, base_url=base, **common)
    if provider == "gemini":
        from .gemini_llm import GeminiLLM
        if not s.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        return GeminiLLM(s.gemini_api_key, model, **common)
    raise ValueError(f"unknown LLM provider: {provider}")


def get_llm(provider: str | None = None, model: str | None = None) -> LLM:
    """llm = get_llm("gemini") / get_llm("openai", "some-model") / get_llm("mock"): the provider is swappable per call.
    LLM_FALLBACK="openai:model" adds a backup that is tried when the primary keeps failing."""
    s = get_settings()
    provider = (provider or s.llm_provider).lower()
    tracker = UsageTracker(prices=parse_prices(s.llm_prices), parent=GLOBAL_USAGE)
    fallbacks = []
    if s.llm_fallback and provider != "mock":
        fp, _, fm = s.llm_fallback.partition(":")
        if fp.lower() != provider or (fm and fm != (model or s.llm_model)):
            try:
                fallbacks.append(_build(fp.lower(), fm, s, tracker=tracker))
            except ValueError:
                pass  # fallback not configured (no key): run without it
    return _build(provider, model if model is not None else s.llm_model, s, fallbacks=fallbacks, tracker=tracker)


def llm_info() -> dict:
    s = get_settings()
    return {"provider": s.llm_provider, "model": s.llm_model or None, "fast_model": s.llm_fast_model or None, "fallback": s.llm_fallback or None,
            "available": {"openai": bool(s.openai_api_key), "gemini": bool(s.gemini_api_key), "mock": True},
            "limits": {"max_llm_calls": s.max_llm_calls, "timeout_s": s.llm_timeout, "max_retries": s.llm_max_retries, "max_tokens": s.llm_max_tokens}}


__all__ = ["LLM", "MockLLM", "get_llm", "llm_info", "extract_json", "classify_exception", "UsageTracker", "GLOBAL_USAGE", "PROVIDERS",
           "LLMRequest", "LLMResponse", "Message", "ToolCall", "ToolSpec", "Usage", "LLMError", "LLMAuthError", "LLMBadRequest",
           "LLMBudgetExceeded", "LLMContextTooLong", "LLMInvalidOutput", "LLMRateLimit", "LLMTimeout", "LLMUnavailable"]
