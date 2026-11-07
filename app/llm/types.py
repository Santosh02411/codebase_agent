"""Provider-neutral request / response types for the LLM layer."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """A function the model may call. `parameters` is a JSON Schema object."""
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Message:
    role: str                       # user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)   # assistant turns that call tools
    tool_call_id: str | None = None  # tool turns: which call this answers
    name: str | None = None          # tool turns: tool name
    raw: Any = None                  # provider-native object to echo back verbatim (e.g. Gemini thought signatures)
    images: list[dict] = field(default_factory=list)   # user turns: [{"media_type": "image/png", "data": "<base64>"}]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False          # True when the provider reported no usage and we counted ourselves

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMRequest:
    task: str
    system: str = ""
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    json_mode: bool = False
    require_tool: bool = False       # force a tool call (when tools are given)
    temperature: float | None = None
    max_tokens: int | None = None
    hints: dict = field(default_factory=dict)   # only read by the offline mock / test doubles


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    finish_reason: str = ""
    attempts: int = 1
    fallback: bool = False
    raw: Any = None


# ---- errors ---------------------------------------------------------------------------------
class LLMError(Exception):
    retriable = False


class LLMAuthError(LLMError):
    """Bad / missing credentials or no access to the model."""


class LLMBadRequest(LLMError):
    """The provider rejected the request itself (unsupported parameter, malformed tools...)."""


class LLMContextTooLong(LLMError):
    """The prompt does not fit the model's context window."""


class LLMRateLimit(LLMError):
    retriable = True

    def __init__(self, msg: str = "", retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class LLMTimeout(LLMError):
    retriable = True


class LLMUnavailable(LLMError):
    """Network trouble or a 5xx from the provider."""
    retriable = True


class LLMInvalidOutput(LLMError):
    """The model answered, but not with valid JSON / the expected structure (after one repair attempt)."""


class LLMBudgetExceeded(LLMError):
    """The run used up its LLM call budget."""
