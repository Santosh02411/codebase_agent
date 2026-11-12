"""The LLM layer, tested offline with fake SDK clients: request building, function calling, usage, retries, fallback, JSON repair."""
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from app.llm import (LLMAuthError, LLMBudgetExceeded, LLMInvalidOutput, LLMRateLimit, LLMRequest, Message, ToolSpec, UsageTracker, get_llm)
from app.llm.base import LLM, classify_exception, extract_json
from app.llm.gemini_llm import GeminiLLM
from app.llm.openai_llm import OpenAILLM
from app.llm.types import LLMResponse, ToolCall, Usage
from app.llm.usage import parse_prices

TOOL = ToolSpec("search_code", "search", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})


# ---- fakes ------------------------------------------------------------------------------------
class RateLimitError(Exception):
    status_code = 429


class FakeOpenAI:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def oa_reply(content="", tool_calls=None, usage=(11, 7)):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg, finish_reason="stop")], model="gpt-test", usage=NS(prompt_tokens=usage[0], completion_tokens=usage[1]))


def oa(replies, **kw):
    kw.setdefault("sleep", lambda s: None)
    return OpenAILLM(client=FakeOpenAI(replies), model="gpt-test", **kw)


# ---- OpenAI -----------------------------------------------------------------------------------
def test_openai_builds_function_calling_request_and_parses_tool_calls_and_usage():
    call = NS(id="c1", function=NS(name="search_code", arguments='{"query": "eta"}'))
    llm = oa([oa_reply(tool_calls=[call])])
    r = llm.chat("research", "sys", [Message("user", "find eta")], [TOOL])
    kw = llm.client.calls[0]
    assert kw["tools"][0]["function"]["name"] == "search_code" and kw["tool_choice"] == "auto"
    assert kw["messages"][0] == {"role": "system", "content": "sys"} and kw["temperature"] == 0.1 and kw["max_completion_tokens"] == 4096
    assert r.tool_calls == [ToolCall("c1", "search_code", {"query": "eta"})]
    assert (r.usage.input_tokens, r.usage.output_tokens, r.provider) == (11, 7, "openai")
    assert llm.usage.summary()["total_tokens"] == 18


def test_openai_tool_results_round_trip_and_json_mode():
    llm = oa([oa_reply('{"a": 1}')])
    msgs = [Message("user", "q"), Message("assistant", "", tool_calls=[ToolCall("c1", "grep", {"query": "x"})]), Message("tool", "3 matches", tool_call_id="c1", name="grep")]
    wire = OpenAILLM.to_messages(LLMRequest("t", "s", msgs))
    assert wire[2]["tool_calls"][0]["function"]["arguments"] == '{"query": "x"}' and wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "3 matches"}
    assert llm.json("t", "s", "p") == {"a": 1}
    assert llm.client.calls[0]["response_format"] == {"type": "json_object"}


def test_openai_reasoning_models_get_no_temperature():
    llm = OpenAILLM(client=FakeOpenAI([oa_reply("x")]), model="gpt-5-mini", sleep=lambda s: None)
    llm.text("s", "p")
    assert "temperature" not in llm.client.calls[0]


def test_openai_retries_without_a_parameter_the_server_rejects():
    llm = oa([Exception("Unsupported parameter: 'max_completion_tokens'"), oa_reply("ok")])
    assert llm.text("s", "p") == "ok" and "max_tokens" in llm.client.calls[1] and "max_completion_tokens" not in llm.client.calls[1]


# ---- retries, fallback, budget ---------------------------------------------------------------
def test_rate_limits_are_retried_with_backoff_and_counted():
    sleeps = []
    llm = oa([RateLimitError("slow down"), RateLimitError("slow down"), oa_reply("fine")], sleep=sleeps.append)
    r = llm.chat("t", "s", [Message("user", "p")])
    assert r.text == "fine" and r.attempts == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0]
    s = llm.usage.summary()
    assert s["failed_calls"] == 2 and s["retries"] == 2 and s["calls"] == 3


def test_auth_errors_are_not_retried():
    llm = oa([type("AuthenticationError", (Exception,), {"status_code": 401})("bad key"), oa_reply("never")])
    with pytest.raises(LLMAuthError):
        llm.text("s", "p")
    assert len(llm.client.calls) == 1


def test_retries_are_bounded():
    llm = oa([RateLimitError("x")] * 5, max_retries=2)
    with pytest.raises(LLMRateLimit):
        llm.text("s", "p")
    assert len(llm.client.calls) == 2


def test_fallback_provider_answers_when_primary_fails():
    backup = oa([oa_reply("from backup")])
    primary = oa([type("InternalServerError", (Exception,), {"status_code": 500})("boom")] * 3, fallbacks=[backup])
    r = primary.chat("t", "s", [Message("user", "p")])
    assert r.text == "from backup" and r.fallback and primary.usage.summary()["fallbacks"] == 1


def test_call_budget_is_enforced():
    llm = oa([oa_reply("1"), oa_reply("2")], max_calls=1)
    llm.text("s", "p")
    with pytest.raises(LLMBudgetExceeded):
        llm.text("s", "p")


def test_error_classification():
    assert isinstance(classify_exception(Exception("maximum context length exceeded")), type(classify_exception(Exception("context_length_exceeded"))))
    assert type(classify_exception(TimeoutError("timed out"))).__name__ == "LLMTimeout"
    assert type(classify_exception(RateLimitError("x"))).__name__ == "LLMRateLimit"


# ---- structured output ------------------------------------------------------------------------
class Out(BaseModel):
    answer: str
    score: int = 0


def test_json_is_repaired_once_then_validated():
    llm = oa([oa_reply("here you go: not json"), oa_reply('```json\n{"answer": "yes", "score": "3"}\n```')])
    out = llm.json("t", "s", "p", schema=Out)
    assert out == {"answer": "yes", "score": 3}
    second = llm.client.calls[1]["messages"]
    assert "not usable" in second[-1]["content"] and second[-2]["role"] == "assistant"


def test_json_that_stays_invalid_raises():
    llm = oa([oa_reply("nope"), oa_reply('{"wrong": 1}')])
    with pytest.raises(LLMInvalidOutput):
        llm.json("t", "s", "p", schema=Out)


def test_extract_json_handles_fences_and_prose():
    assert extract_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}


# ---- model selection, usage, prices ----------------------------------------------------------
def test_fast_tier_for_planning_strong_for_reasoning():
    llm = oa([], fast_model="small")
    assert llm.model_for("plan") == "small" and llm.model_for("research") == "small"
    assert llm.model_for("analyze") == "gpt-test" and llm.model_for("generate_fix") == "gpt-test"
    assert oa([]).model_for("plan") == "gpt-test"   # no fast model configured: one model for everything


def test_usage_summary_latency_and_cost():
    t = UsageTracker(prices=parse_prices('{"gpt-test": [1.0, 2.0]}'))
    llm = oa([oa_reply("a", usage=(1000, 500)), oa_reply("b", usage=(2000, 100))], tracker=t)
    llm.text("s", "p"); llm.text("s", "p")
    s = t.summary()
    assert s["input_tokens"] == 3000 and s["output_tokens"] == 600 and s["cost_usd"] == pytest.approx(0.0042)
    assert s["by_task"]["text"]["calls"] == 2 and s["p95_latency_ms"] >= 0 and not s["estimated_tokens"]
    assert "cost_usd" not in UsageTracker().summary()    # no price table -> no invented cost


def test_tokens_are_estimated_when_the_provider_reports_none():
    class Quiet(LLM):
        name = "quiet"
        def _complete(self, req, model):
            return LLMResponse(text="hello world " * 20)
    llm = Quiet("m")
    llm.text("system prompt", "user prompt " * 30)
    s = llm.usage.summary()
    assert s["input_tokens"] > 0 and s["output_tokens"] > 0 and s["estimated_tokens"]


def test_observer_sees_every_call():
    ev = []
    llm = oa([RateLimitError("x"), oa_reply("ok")])
    llm.set_observer(ev.append)
    llm.text("s", "p")
    assert [e["phase"] for e in ev] == ["start", "error", "start", "end"] and ev[-1]["input_tokens"] == 11


# ---- Gemini -----------------------------------------------------------------------------------
class FakeGemini:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.models = NS(generate_content=self._gen)

    def _gen(self, **kw):
        self.calls.append(kw)
        return self.reply


def gemini_reply(parts, usage=(30, 9)):
    from google.genai import types
    content = types.Content(role="model", parts=parts)
    return NS(candidates=[NS(content=content, finish_reason="STOP")], text=None,
              usage_metadata=NS(prompt_token_count=usage[0], candidates_token_count=usage[1], thoughts_token_count=0))


def test_gemini_function_calls_json_mode_and_usage():
    from google import genai
    from google.genai import types
    reply = gemini_reply([types.Part(function_call=types.FunctionCall(name="search_code", args={"query": "eta"}))])
    llm = GeminiLLM(client=FakeGemini(reply), genai=genai, model="gemini-test", sleep=lambda s: None)
    r = llm.chat("research", "sys", [Message("user", "find")], [TOOL])
    cfg = llm.client.calls[0]["config"]
    assert cfg.tools[0].function_declarations[0].name == "search_code" and cfg.automatic_function_calling.disable
    assert r.tool_calls[0].name == "search_code" and r.tool_calls[0].args == {"query": "eta"} and r.tool_calls[0].id
    assert (r.usage.input_tokens, r.usage.output_tokens) == (30, 9) and isinstance(r.raw, types.Content)

    llm2 = GeminiLLM(client=FakeGemini(gemini_reply([types.Part(text='{"x": 1}')])), genai=genai, model="m", sleep=lambda s: None)
    assert llm2.json("t", "s", "p") == {"x": 1}
    assert llm2.client.calls[0]["config"].response_mime_type == "application/json"


def test_gemini_echoes_its_own_content_and_groups_tool_results():
    from google import genai
    from google.genai import types
    raw = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="grep", args={"query": "a"}))])
    llm = GeminiLLM(client=FakeGemini(gemini_reply([types.Part(text="done")])), genai=genai, model="m")
    msgs = [Message("user", "q"), Message("assistant", "", tool_calls=[ToolCall("1", "grep", {"query": "a"})], raw=raw),
            Message("tool", "r1", tool_call_id="1", name="grep"), Message("tool", "r2", tool_call_id="2", name="find_symbol")]
    contents = llm._contents(LLMRequest("t", "s", msgs))
    assert contents[1] is raw and len(contents) == 3 and len(contents[2].parts) == 2
    assert contents[2].parts[0].function_response.name == "grep"


# ---- factory ----------------------------------------------------------------------------------
def test_get_llm_switches_provider_and_validates_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_llm("mock").name == "mock"
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_llm("openai")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        get_llm("gemini")
    with pytest.raises(ValueError, match="unknown"):
        get_llm("nope")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_FAST", "small-model")
    monkeypatch.setenv("LLM_MODEL", "big-model")
    llm = get_llm("openai")
    assert llm.name == "openai" and llm.model_for("plan") == "small-model" and llm.model_for("analyze") == "big-model"


def test_fallback_is_attached_only_when_configured_and_keyed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("LLM_FALLBACK", "gemini:gem-model")
    llm = get_llm("openai")
    assert [f.name for f in llm.fallbacks] == ["gemini"] and llm.fallbacks[0].model == "gem-model"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert get_llm("openai").fallbacks == []


def test_gemini_switches_to_a_current_model_when_the_configured_one_is_retired():
    from google import genai
    from google.genai import types
    good = gemini_reply([types.Part(text="ok")])

    class Retired(FakeGemini):
        def __init__(self):
            super().__init__(good)
            self.models = NS(generate_content=self._gen2, list=lambda: [NS(name="models/gemini-2.0-flash", supported_actions=["generateContent"]), NS(name="models/gemini-3.1-flash-lite", supported_actions=["generateContent"]),
                                                                        NS(name="models/gemini-3.5-flash", supported_actions=["generateContent"]), NS(name="models/gemini-3.5-flash-image", supported_actions=["generateContent"]),
                                                                        NS(name="models/text-embedding-9", supported_actions=["embedContent"])])

        def _gen2(self, **kw):
            self.calls.append(kw)
            if kw["model"] == "gemini-2.0-flash":
                raise Exception("404 NOT_FOUND. This model models/gemini-2.0-flash is no longer available.")
            return good

    llm = GeminiLLM(client=Retired(), genai=genai, model="gemini-2.0-flash", sleep=lambda s: None)
    r = llm.chat("t", "s", [Message("user", "hi")])
    assert r.text == "ok" and r.model == "gemini-3.5-flash" and llm.model == "gemini-3.5-flash"
    assert [c["model"] for c in llm.client.calls] == ["gemini-2.0-flash", "gemini-3.5-flash"]
    # a different failure is not swallowed
    class Boom(Retired):
        def _gen2(self, **kw):
            raise Exception("429 quota exceeded")
    with pytest.raises(Exception):
        GeminiLLM(client=Boom(), genai=genai, model="gemini-2.0-flash", sleep=lambda s: None, max_retries=0).chat("t", "s", [Message("user", "hi")])


def test_gemini_tries_the_next_model_immediately_when_one_is_overloaded():
    from google import genai
    from google.genai import types
    good = gemini_reply([types.Part(text="ok")])

    class Busy(FakeGemini):
        def __init__(self):
            super().__init__(good)
            self.models = NS(generate_content=self._g, list=lambda: [NS(name="models/gemini-3.5-flash", supported_actions=["generateContent"]), NS(name="models/gemini-3.0-flash", supported_actions=["generateContent"])])

        def _g(self, **kw):
            self.calls.append(kw)
            if kw["model"] == "gemini-3.5-flash":
                raise Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return good

    llm = GeminiLLM(client=Busy(), genai=genai, model="gemini-3.5-flash", sleep=lambda s: None)
    r = llm.chat("t", "s", [Message("user", "hi")])
    assert r.text == "ok" and [c["model"] for c in llm.client.calls] == ["gemini-3.5-flash", "gemini-3.0-flash"]
    assert llm.model == "gemini-3.5-flash"          # a one-off detour: the preferred model is kept


def test_gemini_out_of_quota_model_falls_through_to_one_that_works_and_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from google import genai
    from google.genai import types
    good = gemini_reply([types.Part(text="ok")])

    class Quota(FakeGemini):
        def __init__(self):
            super().__init__(good)
            self.models = NS(generate_content=self._g, list=lambda: [NS(name="models/gemini-3.5-flash", supported_actions=["generateContent"]), NS(name="models/gemini-3.0-flash", supported_actions=["generateContent"]),
                                                                    NS(name="models/gemini-2.5-flash", supported_actions=["generateContent"])])

        def _g(self, **kw):
            self.calls.append(kw)
            if kw["model"] in ("gemini-3.5-flash", "gemini-3.0-flash"):
                raise Exception("429 RESOURCE_EXHAUSTED. You exceeded your current quota")
            return good

    llm = GeminiLLM(client=Quota(), genai=genai, model="gemini-3.5-flash", sleep=lambda s: None)
    r = llm.chat("t", "s", [Message("user", "hi")])
    assert r.text == "ok" and [c["model"] for c in llm.client.calls] == ["gemini-3.5-flash", "gemini-3.0-flash", "gemini-2.5-flash"]
    assert llm.model == "gemini-2.5-flash"
    llm2 = GeminiLLM(client=Quota(), genai=genai, sleep=lambda s: None)      # next start, no LLM_MODEL configured: uses what worked
    llm2.chat("t", "s", [Message("user", "hi")])
    assert llm2.client.calls[0]["model"] == "gemini-2.5-flash"


def test_gemini_without_a_configured_model_picks_a_current_one_up_front(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from google import genai
    from google.genai import types
    good = gemini_reply([types.Part(text="ok")])
    client = FakeGemini(good)
    client.models = NS(generate_content=client._gen, list=lambda: [NS(name="models/gemini-2.0-flash", supported_actions=["generateContent"]), NS(name="models/gemini-3.5-flash", supported_actions=["generateContent"])])
    llm = GeminiLLM(client=client, genai=genai, sleep=lambda s: None)
    llm.chat("t", "s", [Message("user", "hi")])
    assert client.calls[0]["model"] == "gemini-3.5-flash"
