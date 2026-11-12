"""Automatic test generation: learning the repository's conventions, running what was written, telling a wrong test from a bug it found."""
import pytest

from app.agent.run import run_task
from app.config import get_settings
from app.quality import frameworks, test_patterns as tp
from tests.helpers import FIX_SCRIPT, ScriptedLLM

AUTH_TEST = {"path": "tests/test_auth.py", "content": (
    "import pytest\nfrom auth import authenticate_user\n\n\ndef test_valid_token():\n    assert authenticate_user('secret-token') == 'driver-1'\n\n\n"
    "def test_missing_token():\n    with pytest.raises(PermissionError):\n        authenticate_user('')\n\n\ndef test_unknown_token():\n    with pytest.raises(PermissionError):\n        authenticate_user('nope')\n")}
ETA_TEST = {"path": "tests/test_eta.py", "content": "from services.eta import calculate_delivery_eta\n\n\ndef test_missing_speed_uses_default():\n    assert calculate_delivery_eta(30, None) == 60\n"}
EDIT = {k: FIX_SCRIPT["generate_fix"][k] for k in ("file", "search", "replace")}


def gen(tools, script, target="auth.py", **kw):
    llm = ScriptedLLM(script)
    st = run_task(llm, tools, get_settings(), mode="tests", text=f"Write tests for {target}", target=target, allow_fix=True, engine="simple", **kw)
    return llm, st


# ---- reading the repository's conventions ----------------------------------------------------------------------------------------------------
def test_patterns_of_the_fixture_repo(tools):
    p = tp.analyze(tools.root, tools.index.tree, "services/eta.py")
    assert p["framework"] == "pytest" and p["suggested_path"] == "tests/test_eta.py" and p["assertions"] == "pytest `assert` statements"
    assert p["layout"] == "tests live in a separate top-level folder" and "from delivery_app import create_delivery" in p["imports"] and p["sample_path"] == "tests/test_delivery.py"
    text = tp.render(p)
    assert "Put the new test file at: tests/test_eta.py" in text and "An existing test to imitate" in text and "def test_create_delivery_default_speed" in text


def test_conventions_are_followed_not_assumed(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "pkg" / "calc_test.py").write_text("from unittest import mock\nimport pytest\n\n@pytest.fixture\ndef x():\n    return 1\n\n@pytest.mark.parametrize('a', [1])\ndef test_a(a, x):\n    with mock.patch('os.getcwd'):\n        assert a\n")
    tree = ["pkg/calc.py", "pkg/calc_test.py"]
    p = tp.analyze(tmp_path, tree, "pkg/util.py")
    assert p["suggested_path"] == "pkg/util_test.py" and p["layout"] == "tests sit next to the code"                      # *_test.py next to the code, as the repo does
    assert p["fixtures"] and p["parametrized"] and "unittest.mock" in p["mocking"]
    fw = lambda n: frameworks.Framework(n, "x", [], n)  # noqa: E731
    assert tp.suggest_path(fw("jest"), "src/api/users.ts", ["src/api/orders.spec.ts"], tmp_path) == "src/api/users.spec.ts"
    assert tp.suggest_path(fw("jest"), "src/api/users.ts", ["src/__tests__/a.test.ts"], tmp_path) == "src/api/__tests__/users.test.ts"
    assert tp.suggest_path(fw("go"), "internal/store/db.go", [], tmp_path) == "internal/store/db_test.go"
    assert tp.suggest_path(fw("cargo"), "src/lib.rs", [], tmp_path) == "tests/lib_test.rs"
    assert tp.suggest_path(fw("maven"), "svc/src/main/java/com/acme/Calc.java", [], tmp_path) == "svc/src/test/java/com/acme/CalcTest.java"
    assert "No test framework" in tp.render(tp.analyze(tmp_path / "empty", [], "x.py"))


# ---- generate → run → report -------------------------------------------------------------------------------------------------------------------------
def test_generated_tests_are_run_measured_and_reported(tools):
    llm, st = gen(tools, {"generate_tests": {"edits": [], "new_files": [AUTH_TEST], "explanation": "valid, missing and unknown tokens"}})
    prompt = [p for t, p in llm.prompts if t == "generate_tests"][0]
    assert "Write pytest tests for `auth.py`" in prompt and "Put the new test file at: tests/test_auth.py" in prompt and "pytest `assert` statements" in prompt    # conventions reached the model
    assert "do not change implementation code" in prompt
    assert st["status"] == "fix_verified" and list(st["final_files"]) == ["tests/test_auth.py"] and st["verification"]["status"] == "no_regressions"
    cd = st["coverage_delta"]
    assert cd["before"] < cd["after"] and cd["files"][0]["path"] == "auth.py" and cd["files"][0]["before"] == 0.0 and cd["files"][0]["after"] > 0
    a = st["answer"]
    for h in ("## Generated Tests", "## What the Tests Cover", "## Proposed Change", "## Tests Executed", "## Coverage", "## Verification Result"):
        assert h in a
    assert "`tests/test_auth.py`" in a and "Framework: **pytest**" in a and "`auth.py`: 0.0% → **" in a and "✅ **No regressions.**" in a
    assert st["test_patterns"]["framework"] == "pytest" and not st["impl_change"]


def test_a_wrong_test_is_fixed_and_the_implementation_is_left_alone(tools):
    wrong = {"path": "tests/test_auth.py", "content": "from auth import authenticate_user\n\n\ndef test_unknown_token():\n    assert authenticate_user('nope') is True\n"}
    llm, st = gen(tools, {"generate_tests": [{"new_files": [wrong]}, {"new_files": [AUTH_TEST]}], "reflect": {"action": "retry_code", "culprit": "test", "reason": "the expectation was inverted"}})
    assert st["attempts"] == 2 and st["verification"]["status"] == "no_regressions" and not st["impl_change"]
    retry = [p for t, p in llm.prompts if t == "generate_tests"][1]
    assert "fix the TEST" in retry and "do not change implementation code" in retry and "expectation was inverted" in retry
    assert [s["message"] for s in st["steps"] if s["node"] == "reflect"][0].endswith("(culprit: test)") or "culprit: test" in " ".join(s["message"] for s in st["steps"] if s["node"] == "reflect")
    assert "implementation" not in " ".join(f for f in st["final_files"])


def test_a_test_that_exposes_a_bug_can_lead_to_a_reviewed_implementation_fix(tools):
    script = {"generate_tests": [{"new_files": [ETA_TEST], "explanation": "the default speed should apply when it is missing"},
                                 {"edits": [EDIT], "new_files": [ETA_TEST], "explanation": "default the speed; the test caught the missing default"}],
              "reflect": {"action": "retry_code", "culprit": "implementation", "reason": "the test is right: calculate_delivery_eta crashes on a missing speed"}}
    llm, st = gen(tools, script, target="services/eta.py")
    assert st["attempts"] == 2 and st["impl_change"] is True and st["status"] == "fix_verified"
    assert {f["path"] for f in st["patch_files"]} == {"services/eta.py", "tests/test_eta.py"}
    retry = [p for t, p in llm.prompts if t == "generate_tests"][1]
    assert "CORRECT" in retry and "edits to source files are allowed now" in retry
    assert "## ⚠ Implementation Changed" in st["answer"] and "`services/eta.py`" in st["answer"] and "Review that change as carefully as any bug fix" in st["answer"]
    assert st["verification"]["fixed_tests"] == ["tests/test_delivery.py::test_create_delivery_default_speed"] or st["verification"]["status"] in ("resolved", "partial")


def test_tests_may_not_quietly_change_implementation_code(tools):
    llm, st = gen(tools, {"generate_tests": [{"edits": [EDIT], "new_files": [ETA_TEST]}, {"new_files": [ETA_TEST]}]}, target="services/eta.py")
    assert st["steps"] and any("rejected" in s["message"] and "must live in test files" in s["message"] for s in st["steps"] if s["node"] == "generate")
    assert st["attempts"] == 2 and not st["impl_change"] and "services/eta.py" not in st["final_files"]


def test_a_patch_without_a_test_file_is_rejected(tools):
    llm, st = gen(tools, {"generate_tests": [{"new_files": [{"path": "notes/readme.txt", "content": "hi"}]}, {"new_files": [AUTH_TEST]}]})
    assert any("a test file is required" in s["message"] for s in st["steps"] if s["node"] == "generate") and list(st["final_files"]) == ["tests/test_auth.py"]


def test_test_file_recognition_covers_other_ecosystems():
    from app import verify
    for p in ("pkg/util_test.go", "src/test/java/com/acme/CalcTest.java", "tests/integration.rs", "src/utils/date.test.ts", "web/__tests__/a.js", "tests/test_x.py", "pkg/test_y.py"):
        assert verify.is_test_file(p), p
    for p in ("pkg/util.go", "src/main/java/com/acme/Calc.java", "src/lib.rs", "src/utils/date.ts"):
        assert not verify.is_test_file(p), p
