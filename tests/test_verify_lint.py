"""Verification verdicts, the linter wrapper and test-run parsing."""
import json
import stat

import pytest

from app import lint, sandbox, verify
from app.verify import judge


def run(status="passed", failed=(), summary="", **kw):
    return {"status": status, "passed": status == "passed", "summary": summary or status, "output": "", "failed_tests": [{"id": f, "kind": "failed", "message": ""} for f in failed], **kw}


def blocking(code="F821"):
    return {"file": "a.py", "line": 1, "code": code, "message": "undefined name", "blocking": True, "severity": "error"}


@pytest.mark.parametrize("before,after,kw,expected", [
    (run("failed", ["t::a"]), run("passed"), {}, "resolved"),
    (run("failed", ["t::a", "t::b"]), run("failed", ["t::b"]), {}, "partial"),
    (run("failed", ["t::a"]), run("failed", ["t::a"]), {}, "not_resolved"),
    (run("failed", ["t::a"]), run("failed", ["t::a", "t::new"]), {}, "not_resolved"),
    (run("passed"), run("passed"), {}, "unverified"),                                         # nothing reproduced the bug
    (run("passed"), run("passed"), {"intent": "change"}, "no_regressions"),
    (run("failed", ["t::old"]), run("failed", ["t::old"]), {"intent": "change"}, "no_regressions"),
    (run("passed"), run("no_tests"), {}, "unverified"),
    (run("passed"), run("timeout"), {}, "unverified"),
    (run("passed"), run("error", summary="collection error"), {}, "not_resolved"),
    (run("failed", ["t::a"]), run("passed"), {"lint_new": [blocking()]}, "not_resolved"),     # tests green but the patch broke the linter
    (run("failed", ["t::a"]), run("passed"), {"lint_new": [dict(blocking(), blocking=False, code="F401")]}, "resolved"),
    (run("passed"), run("passed"), {"regression": {"failed_before": True, "passed_after": True, "tests": ["tests/test_r.py"]}}, "resolved"),   # reproduced + fixed
    (run("passed"), run("passed"), {"regression": {"failed_before": False, "passed_after": True, "tests": ["tests/test_r.py"]}}, "unverified"),
    (run("failed", ["t::x"]), run("failed", ["t::x", "tests/test_r.py::test_bug"]), {"regression": {"failed_before": True, "passed_after": False, "tests": ["tests/test_r.py"]}}, "not_resolved"),
])
def test_judge(before, after, kw, expected):
    assert judge(before, after, **{"intent": "debug", **kw})["status"] == expected


def test_judge_explains_itself():
    v = judge(run("passed"), run("passed"), regression={"failed_before": False, "passed_after": True, "tests": ["t"]})
    assert "does not demonstrate the bug" in " ".join(v["reasons"]) and "nothing demonstrated" in v["summary"]
    assert judge(run("failed", ["a"]), run("passed"))["fixed_tests"] == ["a"]
    assert judge(None, None)["status"] == "unverified"


def test_is_test_file():
    assert all(verify.is_test_file(p) for p in ("tests/test_x.py", "pkg/tests/helpers.py", "test_a.py", "src/a.test.ts", "b_test.py"))
    assert not verify.is_test_file("src/app.py")


# ---- test running -------------------------------------------------------------------------------------------------------
def test_pytest_output_is_parsed_into_failing_tests_and_counts(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_ok():\n    assert True\n\ndef test_bad():\n    assert 1 == 2, 'nope'\n")
    r = sandbox.run_tests(tmp_path, 60)
    assert r["status"] == "failed" and r["counts"] == {"failed": 1, "passed": 1}
    assert r["failed_tests"][0]["id"] == "test_a.py::test_bad" and "nope" in r["failed_tests"][0]["message"] and "pytest" in r["command"]
    only = sandbox.run_tests(tmp_path, 60, targets=["test_a.py::test_ok"])
    assert only["status"] == "passed" and only["counts"] == {"passed": 1}
    assert sandbox.run_tests(tmp_path, 60, targets=["-x; rm -rf"])["status"] in ("failed", "passed")    # option-looking targets are dropped


def test_test_command_detection(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "29"}}))
    assert sandbox.detect_command(tmp_path)[:3] == ["npx", "--no-install", "jest"]
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node run-tests.js"}}))
    assert sandbox.detect_command(tmp_path) == ["npm", "test", "--silent"]
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
    assert "pytest" in " ".join(sandbox.detect_command(tmp_path))


# ---- linter ---------------------------------------------------------------------------------------------------------------
def test_linter_flags_blocking_problems_and_compares_against_a_baseline(tmp_path):
    (tmp_path / "ok.py").write_text("import os\n\nprint(os.getcwd())\n")
    (tmp_path / "bad.py").write_text("def f(:\n    pass\n")
    r = lint.run_linter(tmp_path)
    assert r["status"] == "issues" and any(i["blocking"] and i["file"] == "bad.py" for i in r["issues"])
    assert sum(1 for i in r["issues"] if i["file"] == "bad.py" and i["code"] in ("E999", "invalid-syntax")) == 1       # reported once, not by two tools
    (tmp_path / "bad.py").write_text("print(missing_name)\n")
    before = lint.run_linter(tmp_path)
    (tmp_path / "bad.py").write_text("print(missing_name)\nprint(another_missing)\n")
    new = lint.new_issues(before, lint.run_linter(tmp_path))
    assert [i["message"] for i in new if i["blocking"]] == ["Undefined name `another_missing`"]
    (tmp_path / "bad.py").write_text("\n\n\nprint(missing_name)\n")                    # only moved: not new
    assert lint.new_issues(before, lint.run_linter(tmp_path)) == []


def test_linter_covers_only_requested_paths_and_json(tmp_path):
    (tmp_path / "a.py").write_text("x = (\n")
    (tmp_path / "b.py").write_text("print(nope)\n")
    (tmp_path / "c.json").write_text("{bad")
    assert {i["file"] for i in lint.run_linter(tmp_path, ["a.py"])["issues"]} == {"a.py"}
    assert any(i["file"] == "c.json" and i["blocking"] for i in lint.run_linter(tmp_path)["issues"])
    assert lint.run_linter(tmp_path / "missing_dir")["status"] == "clean"


def test_eslint_results_are_parsed(tmp_path):
    (tmp_path / "app.js").write_text("foo()\n")
    exe = tmp_path / "node_modules" / ".bin" / "eslint"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\necho '[{\"filePath\": \"%s/app.js\", \"messages\": [{\"ruleId\": \"no-undef\", \"severity\": 2, \"line\": 1, \"column\": 1, \"message\": \"foo is not defined\"}, "
                   "{\"ruleId\": \"semi\", \"severity\": 1, \"line\": 1, \"column\": 6, \"message\": \"Missing semicolon\"}]}]'\n" % tmp_path)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    r = lint.run_linter(tmp_path)
    assert "eslint" in r["tool"] and r["counts"]["blocking"] == 1 and r["counts"]["warnings"] == 1
