"""Debugging as the headline feature: structured error reports, reproduction, patch, verification, and the report the user reads."""
import pytest

from app.agent.errors import ErrorReport, from_test_output, infer_variables, parse_error
from app.agent.run import run_task
from app.config import get_settings
from tests.helpers import FIX_SCRIPT, ScriptedLLM

TREE = ["services/eta.py", "delivery_app.py", "tests/test_delivery.py", "api/routes/users.ts", "src/App.java", "src/Util.java"]
SRC = {"services/eta.py": "    return round(distance_km / speed_kmh * 60)", "delivery_app.py": '    eta = calculate_delivery_eta(payload["distance_km"], payload.get("speed_kmh"))'}
read_line = lambda f, n: SRC.get(f, "")  # noqa: E731

PY_TRACE = '''Traceback (most recent call last):
  File "/srv/app/delivery_app.py", line 9, in create_delivery
    eta = calculate_delivery_eta(payload["distance_km"], payload.get("speed_kmh"))
  File "/srv/app/services/eta.py", line 6, in calculate_delivery_eta
    return round(distance_km / speed_kmh * 60)
TypeError: unsupported operand type(s) for /: 'int' and 'NoneType'
'''
EDIT = {k: FIX_SCRIPT["generate_fix"][k] for k in ("file", "search", "replace")}


def go(tools, script, question=PY_TRACE, *, mode="debug", llm_kw=None, **kw):
    llm = ScriptedLLM(script, **(llm_kw or {}))
    st = run_task(llm, tools, get_settings(), mode=mode, text=question, allow_fix=True, engine="simple", **kw)
    return llm, st


# ---- the error report: type, file, line, variable, stack, related functions ---------------------------------------------------------
def test_python_traceback_is_fully_decoded():
    r = parse_error(PY_TRACE, TREE, read_line)
    assert (r.exception_type, r.language, r.file, r.line, r.function) == ("TypeError", "python", "services/eta.py", 6, "calculate_delivery_eta")
    assert r.category == "missing value (None / null / undefined)" and r.code_line == SRC["services/eta.py"].strip()
    assert [f["func"] for f in r.frames] == ["create_delivery", "calculate_delivery_eta"]          # outermost first
    assert r.variables[0]["name"] == "speed_kmh" and "right operand" in r.variables[0]["evidence"]
    assert "services/eta.py:6" in r.headline() and r.found


def test_chained_exceptions_report_the_final_one_and_keep_the_cause():
    t = ('Traceback (most recent call last):\n  File "services/eta.py", line 6, in f\n    x\nKeyError: \'speed\'\n\n'
         'During handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File "delivery_app.py", line 9, in g\n    y\nValueError: bad payload\n')
    r = parse_error(t, TREE)
    assert r.exception_type == "ValueError" and r.file == "delivery_app.py" and r.chained == ["KeyError: 'speed'"]


def test_javascript_and_java_traces():
    js = "TypeError: Cannot read properties of undefined (reading 'id')\n    at getUser (/srv/api/routes/users.ts:42:13)\n    at Layer.handle (/srv/node_modules/express/lib/router/layer.js:95:5)\n"
    r = parse_error(js, TREE)
    assert (r.language, r.exception_type, r.file, r.line, r.function) == ("javascript", "TypeError", "api/routes/users.ts", 42, "getUser")
    assert r.variables[0]["name"] == "id"
    java = 'Exception in thread "main" java.lang.IllegalStateException: failed to start\n\tat com.acme.App.main(App.java:12)\nCaused by: java.lang.NullPointerException: Cannot invoke "String.length()" because "name" is null\n\tat com.acme.Util.len(Util.java:7)\n'
    r = parse_error(java, TREE)
    assert r.language == "java" and r.exception_type == "java.lang.NullPointerException" and r.variables[0]["name"] == "name"
    assert r.file == "src/Util.java" and r.line == 7 and r.chained == ["java.lang.IllegalStateException: failed to start"]


@pytest.mark.parametrize("etype,msg,line,expect", [
    ("AttributeError", "'NoneType' object has no attribute 'strip'", "name = user.email.strip()", "user.email"),
    ("NameError", "name 'totl' is not defined", "return totl + 1", "totl"),
    ("KeyError", "'customer'", "x = payload['customer']", "customer"),
    ("ImportError", "cannot import name 'helper' from 'util'", "from util import helper", "helper"),
    ("ZeroDivisionError", "division by zero", "return a / count", "count"),
    ("ModuleNotFoundError", "No module named 'requests'", "import requests", "requests"),
])
def test_variable_inference(etype, msg, line, expect):
    assert expect in [v["name"] for v in infer_variables(etype, msg, line)]


def test_logs_with_http_errors_and_plain_descriptions():
    log = '2026-10-26 10:00:01 INFO request id=5\n2026-10-26 10:00:02 ERROR POST /deliveries -> status=500 Internal Server Error\n'
    r = parse_error(log, TREE)
    assert r.http_status == 500 and not r.exception_type and r.found is False
    d = parse_error("login is slow after the deploy", TREE)
    assert not d.found and d.headline().startswith("error (no exception type")


def test_report_from_a_failing_test_run():
    out = ("tests/test_delivery.py:12: in test_x\n    create_delivery(...)\ndelivery_app.py:9: in create_delivery\n    eta = calculate_delivery_eta(...)\n"
           "services/eta.py:6: in calculate_delivery_eta\n    return round(distance_km / speed_kmh * 60)\nE   TypeError: unsupported operand type(s) for /: 'int' and 'NoneType'\n")
    r = from_test_output(out, TREE, read_line)
    assert r.source == "test run" and r.exception_type == "TypeError" and r.file == "services/eta.py" and r.line == 6


# ---- the whole flow ------------------------------------------------------------------------------------------------------------------------
def test_debug_run_reproduces_by_running_tests_and_reports_in_the_requested_shape(tools):
    script = dict(FIX_SCRIPT, review_patch={"approved": True, "summary": "minimal"})
    llm, st = go(tools, script)
    rep = st["error_report"]
    assert rep["exception_type"] == "TypeError" and rep["file"] == "services/eta.py" and rep["line"] == 6 and rep["variables"][0]["name"] == "speed_kmh"
    assert any(f["name"] == "create_delivery" for f in rep["related_functions"]) is True
    assert st["test_before"]["status"] == "failed" and "Test run on the original code" in st["repro_note"]       # reproduced before touching anything
    assert any("reproduction" in s["message"] for s in st["steps"] if s["node"] == "research")
    assert "Test run on the original code" in dict(llm.prompts)["analyze"] and "Parsed error report" in dict(llm.prompts)["analyze"]
    v = st["verification"]
    assert v["status"] == "resolved" and v["fixed_tests"] == ["tests/test_delivery.py::test_create_delivery_default_speed"] and st["status"] == "fix_verified"
    a = st["answer"]
    heads = [a.index(h) for h in ("## Root Cause", "## Affected Files", "## Explanation", "## Proposed Fix", "## Tests Executed", "## Verification Result")]
    assert heads == sorted(heads)
    assert "`TypeError`" in a and "`services/eta.py:6`" in a and "speed_kmh" in a
    assert "`services/eta.py` — failure point, root cause, modified" in a and "`delivery_app.py`" in a                    # file roles merged, callers listed
    assert "Before the fix: **failed**" in a and "After the fix: **passed**" in a and "Linter (" in a
    assert "✅ **Resolved.**" in a and "```diff" in a and "+    speed_kmh = speed_kmh or DEFAULT_SPEED_KMH" in a
    assert {f["path"] for f in st["affected_files"]} >= {"services/eta.py", "delivery_app.py"}


def test_a_regression_test_that_fails_before_and_passes_after_proves_the_fix(tools, repo):
    (repo / "tests/test_delivery.py").write_text("from delivery_app import create_delivery\n\n\ndef test_create_delivery_with_speed():\n    assert create_delivery({'customer': 'A', 'distance_km': 30, 'speed_kmh': 60})['eta_minutes'] == 30\n")
    from app.ingest import build_index
    tools.index = build_index(repo)                                   # the suite is now green: nothing existing reproduces the bug
    reg_test = {"path": "tests/test_eta_regression.py", "content": "from services.eta import calculate_delivery_eta\n\n\ndef test_missing_speed_uses_default():\n    assert calculate_delivery_eta(30, None) == 60\n"}
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix={"edits": [EDIT], "new_files": [reg_test], "explanation": "default + regression test"}, review_patch={"approved": True}))
    assert "regression test" in [p for t, p in llm.prompts if t == "generate_fix"][0]
    rg = st["regression"]
    assert rg["failed_before"] is True and rg["passed_after"] is True and rg["tests"] == ["tests/test_eta_regression.py"]
    assert st["verification"]["status"] == "resolved" and st["verification"]["reproduced"] is True
    assert "**fails on the original code**" in st["answer"] and "**passes with the fix**" in st["answer"]


def test_a_green_suite_that_never_failed_is_reported_as_not_verified(tools, repo):
    (repo / "tests/test_delivery.py").write_text("def test_ok():\n    assert True\n")
    from app.ingest import build_index
    tools.index = build_index(repo)
    llm, st = go(tools, dict(FIX_SCRIPT, review_patch={"approved": True}))
    assert st["verification"]["status"] == "unverified" and st["status"] == "fix_unverified"
    assert "⚠️ **Not verified.**" in st["answer"] and "nothing demonstrated" in st["answer"]
    assert "do NOT reproduce" in st["repro_note"]


def test_a_regression_test_that_passes_on_the_original_code_is_called_out(tools, repo):
    (repo / "tests/test_delivery.py").write_text("def test_ok():\n    assert True\n")
    from app.ingest import build_index
    tools.index = build_index(repo)
    useless = {"path": "tests/test_useless.py", "content": "def test_nothing():\n    assert True\n"}
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix={"edits": [EDIT], "new_files": [useless]}, review_patch={"approved": True}))
    assert st["regression"]["failed_before"] is False and st["verification"]["status"] == "unverified"
    assert "does **not** reproduce the problem" in st["answer"] and "does not demonstrate the bug" in st["answer"]


def test_a_patch_that_introduces_a_lint_error_fails_verification_and_is_retried(tools):
    typo = dict(EDIT, replace="    speed_kmh = speed_kmh or DEFAULT_SPEED\n    return round(distance_km / speed_kmh * 60)")     # DEFAULT_SPEED is undefined
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix=[typo, EDIT], review_patch={"approved": True}))
    assert st["attempts"] == 2 and st["verification"]["status"] == "resolved"
    retry = [p for t, p in llm.prompts if t == "generate_fix"][1]
    assert "blocking lint errors" in retry and "DEFAULT_SPEED" in retry
    assert any("blocking" in s["message"] and "lint" in s["message"] for s in st["steps"] if s["node"] == "verify")


def test_unresolved_problems_say_so_plainly(tools):
    bad = dict(EDIT, replace="    return 0")
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix=[bad, bad], reflect={"action": "retry_code", "reason": "still wrong"}))
    assert st["status"] == "fix_failed" and st["verification"]["status"] == "not_resolved"
    assert "❌ **Not resolved.**" in st["answer"] and "tried 2 time(s)" in st["answer"]


def test_no_patch_still_gets_the_full_report(tools):
    llm, st = go(tools, dict(FIX_SCRIPT, generate_fix={"edits": [], "new_files": []}))
    assert st["status"] == "no_fix" and "_No patch was generated._" in st["answer"] and "## Verification Result\n❌" in st["answer"]


def test_fix_without_verification_is_labelled_unverified(tools):
    llm = ScriptedLLM(FIX_SCRIPT)
    st = run_task(llm, tools, get_settings(), mode="fix", text=PY_TRACE, allow_fix=True, allow_verify=False, engine="simple")
    assert st["status"] == "fix_unverified" and st["test_before"] is None
    assert "Tests were not run" in st["answer"]


def test_a_description_without_a_trace_is_debugged_via_the_failing_test(tools):
    llm, st = go(tools, dict(FIX_SCRIPT, understand={"intent": "debug", "queries": ["eta default speed"]}), "creating a delivery without speed gives a 500")
    assert st["error_report"]["exception_type"] == "TypeError" and st["error_report"]["source"] == "test run"       # recovered from reproducing it
    assert st["error_report"]["file"] == "services/eta.py"
    assert st["status"] == "fix_verified" and "`TypeError`" in st["answer"]


# ---- the coder as a tool user ----------------------------------------------------------------------------------------------------------------
def test_tool_calling_coder_iterates_with_generate_and_apply_patch(tools):
    bad = {"edits": [dict(EDIT, search="    return round(distance_km / speed * 60)")]}
    good = {"edits": [EDIT], "explanation": "default the speed"}
    script = dict(FIX_SCRIPT, code=[{"tool_calls": [{"name": "read_file", "args": {"path": "services/eta.py"}}]},
                                    {"tool_calls": [{"name": "generate_patch", "args": bad}]},                      # rejected: the model sees why
                                    {"tool_calls": [{"name": "generate_patch", "args": good}]},
                                    {"tool_calls": [{"name": "apply_patch", "args": {"run_tests": True}}]},
                                    {"text": "Defaulted the speed."}], review_patch={"approved": True})
    llm, st = go(tools, script, llm_kw={"tools": True})
    assert "generate_fix" not in llm.calls                               # the JSON path was never needed
    assert st["status"] == "fix_verified" and st["explanation"] == "Defaulted the speed." and "function calling" in " ".join(s["message"] for s in st["steps"] if s["node"] == "generate")
    msgs = llm.requests[-1].messages                                      # the model was told why its first patch failed, and what the sandbox check found
    tool_texts = [m.content for m in msgs if m.role == "tool"]
    assert any("found 0" in t and "Closest existing text" in t for t in tool_texts) and any("SANDBOX COPY" in t and "tests passed" in t for t in tool_texts)


def test_tool_calling_coder_falls_back_to_json_if_it_never_proposes_a_patch(tools):
    llm, st = go(tools, dict(FIX_SCRIPT, code=[{"text": "I am not sure."}], review_patch={"approved": True}), llm_kw={"tools": True})
    assert "generate_fix" in llm.calls and st["status"] == "fix_verified"


# ---- screenshots -----------------------------------------------------------------------------------------------------------------------------
SHOT = [{"media_type": "image/png", "data": "iVBORw0KGgo="}]


def test_screenshot_text_joins_the_request_and_is_parsed_like_pasted_text(tools):
    shot_text = 'Traceback (most recent call last):\n  File "services/eta.py", line 6, in calculate_delivery_eta\nTypeError: unsupported operand type(s) for /: \'int\' and \'NoneType\'\nContext: terminal running pytest'
    llm, st = go(tools, dict(FIX_SCRIPT, read_screenshot=[{"text": shot_text}], review_patch={"approved": True}), "this error appears when I create a delivery", images=SHOT)
    assert "Transcribed from the attached screenshot" in st["question"] and st["error_report"]["exception_type"] == "TypeError"
    assert st["error_report"]["file"] == "services/eta.py" and "read 2" not in "" and any("screenshot" in s["message"] for s in st["steps"] if s["node"] == "understand")
    assert llm.requests[0].messages[0].images == SHOT


def test_models_that_cannot_read_images_degrade_gracefully(tools):
    from app.llm import get_llm
    llm = get_llm("mock")
    st = run_task(llm, tools, get_settings(), mode="debug", text="error shown in the screenshot", allow_fix=True, engine="simple", images=SHOT)
    assert any("cannot read images" in s["message"] for s in st["steps"] if s["node"] == "understand") and st["answer"]


# ---- the whole agent through the real OpenAI provider code (wire format, function calling, JSON mode) -------------------------------------------
def test_full_debug_run_through_the_openai_provider_with_a_fake_client(tools):
    """Everything between the agent and the HTTP call is real: request building, tool schemas, tool-call parsing, JSON mode, usage tracking.
    Only the network is replaced by a script that answers each request the way a competent model would."""
    import json
    from types import SimpleNamespace as NS

    from app.llm.openai_llm import OpenAILLM

    def msg(content="", calls=None):
        return NS(choices=[NS(message=NS(content=content, tool_calls=calls), finish_reason="stop")], model="gpt-fake", usage=NS(prompt_tokens=120, completion_tokens=40))

    def tc(i, name, args):
        return NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))

    researcher = [msg(calls=[tc(1, "find_symbol", {"name": "calculate_delivery_eta"}), tc(2, "get_callers", {"name": "calculate_delivery_eta"}),
                             tc(3, "find_config", {"query": "default speed"})]), msg("Enough context.")]
    coder = [msg(calls=[tc(4, "generate_patch", {"edits": [EDIT], "explanation": "default the speed"})]), msg(calls=[tc(5, "apply_patch", {"run_tests": False})]), msg("Defaulted the speed to 30 km/h.")]
    seen_tools: list[list[str]] = []
    used_models: list[str] = []

    class Fake:
        def __init__(self):
            self.chat = NS(completions=NS(create=self.create))
            self.json_calls = []

        def create(self, **kw):
            used_models.append(kw["model"])
            sysm = kw["messages"][0]["content"]
            if "tools" in kw:
                names = [t["function"]["name"] for t in kw["tools"]]
                seen_tools.append(names)
                assert all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in kw["tools"]) and "response_format" not in kw
                return (coder if "generate_patch" in names else researcher).pop(0)
            assert kw["response_format"] == {"type": "json_object"}
            self.json_calls.append(sysm[:60])
            if "task understanding" in sysm:
                return msg(json.dumps({"intent": "debug", "summary": "TypeError in the ETA calculation", "queries": ["calculate_delivery_eta"], "complexity": "simple"}))
            if "ROLE: planner" in sysm:
                return msg(json.dumps({"steps": [{"agent": "researcher"}, {"agent": "debugger"}, {"agent": "coder"}, {"agent": "tester"}], "needs_patch": True, "needs_review": False, "rationale": "small bug"}))
            if "ROLE: debugger" in sysm:
                return msg(json.dumps({"need_more": False, "answer": "speed_kmh is None when the client omits it [1].", "root_cause": "calculate_delivery_eta divides by speed_kmh without a default.",
                                       "affected_file": "services/eta.py", "affected_function": "calculate_delivery_eta", "confidence": "high"}))
            raise AssertionError(f"unexpected JSON task: {sysm[:80]}")

    fake = Fake()
    llm = OpenAILLM(client=fake, model="gpt-fake", fast_model="gpt-fake-mini", sleep=lambda s: None)
    st = run_task(llm, tools, get_settings(), mode="debug", text=PY_TRACE, allow_fix=True, engine="langgraph")
    assert st["status"] == "fix_verified" and st["verification"]["status"] == "resolved" and st["explanation"] == "Defaulted the speed to 30 km/h."
    assert "get_callers" in seen_tools[0] and "find_config" in seen_tools[0] and "run_tests" in seen_tools[0] and "generate_patch" not in seen_tools[0]      # researcher tool set
    assert "generate_patch" in seen_tools[-1] and "apply_patch" in seen_tools[-1] and "git_log" not in seen_tools[-1]                                       # coder tool set
    assert st["plan"]["needs_regression_test"] is True                                         # planner left it open: a bug fix gets a regression-test request
    s = llm.usage.summary()
    assert s["calls"] >= 6 and s["input_tokens"] >= 720 and s["output_tokens"] >= 240
    assert used_models.count("gpt-fake-mini") >= 4 and used_models.count("gpt-fake") >= 3     # understand / plan / research on the fast model; analysis and code on the strong one
    assert "## Verification Result\n✅ **Resolved.**" in st["answer"]
