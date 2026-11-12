"""Test frameworks, analyzers (real tools where installed, recorded output otherwise), coverage, the quality score and the run API."""
import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from app import sandbox, sandbox_exec
from app.quality import analyzers, coverage, frameworks, runner, score
from app.quality.analyzers import Finding
from tests.conftest import FIXTURE

have = lambda tool: shutil.which(tool) is not None  # noqa: E731


# ---- frameworks: detection, commands, parsing ----------------------------------------------------------------------------------------------
def test_detection_of_every_supported_framework(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "1"}, "scripts": {"test": "vitest"}}))
    (tmp_path / "go.mod").write_text("module x\n")
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "pom.xml").write_text("<project/>")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    names = [f.name for f in frameworks.detect_all(tmp_path)]
    assert names == ["pytest", "vitest", "go", "cargo", "maven"]
    assert [f.language for f in frameworks.detect_all(tmp_path)] == ["python", "node", "go", "rust", "java"]
    only_gradle = tmp_path / "g"
    only_gradle.mkdir()
    (only_gradle / "build.gradle").write_text("")
    assert frameworks.detect(only_gradle).name == "gradle" and frameworks.detect(tmp_path / "nothing") is None


@pytest.mark.parametrize("pkg,expect", [({"devDependencies": {"jest": "29"}}, "jest"), ({"devDependencies": {"mocha": "10"}, "scripts": {"test": "mocha"}}, "mocha"),
                                        ({"scripts": {"test": "node t.js"}}, "npm"), ({"scripts": {"test": 'echo "no test specified"'}}, None)])
def test_node_runner_choice(tmp_path, pkg, expect):
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    fw = frameworks.detect(tmp_path)
    assert (fw.name if fw else None) == expect


def test_targeted_commands():
    fw = lambda n: next(f for f in [frameworks.Framework("pytest", "python", list(frameworks.PYTEST), "pytest"), frameworks.Framework("jest", "node", ["npx", "jest", "--json"], "jest"),
                                    frameworks.Framework("go", "go", ["go", "test", "-json", "./..."], "go"), frameworks.Framework("maven", "java", ["mvn", "-B", "-ntp", "test"], "maven"),
                                    frameworks.Framework("cargo", "rust", ["cargo", "test", "--no-fail-fast"], "cargo")] if f.name == n)
    assert frameworks.command_for(fw("pytest"), ["tests/test_a.py::test_x", "-x; rm"])[-1] == "tests/test_a.py::test_x" and "-x; rm" not in frameworks.command_for(fw("pytest"), ["-x; rm"])
    assert frameworks.command_for(fw("jest"), ["src/a.test.ts"])[-2:] == ["--runTestsByPath", "src/a.test.ts"]
    assert frameworks.command_for(fw("go"), ["pkg/util/strs_test.go::TestJoin"]) == ["go", "test", "-json", "./pkg/util", "-run", "^(TestJoin)$"]
    assert "-Dtest=CalcTest#adds" in frameworks.command_for(fw("maven"), ["CalcTest::adds"])
    assert frameworks.command_for(fw("cargo"), ["tests/x.rs::my_test"])[-1] == "my_test"


JEST = json.dumps({"numTotalTests": 3, "numPassedTests": 2, "numFailedTests": 1, "numPendingTests": 0, "testResults": [{"name": "/work/src/a.test.js", "status": "failed", "assertionResults": [
    {"fullName": "adds works", "status": "passed", "failureMessages": []}, {"fullName": "adds overflow", "status": "failed", "failureMessages": ["Expected: 3\nReceived: 4"]},
    {"fullName": "subtract", "status": "passed", "failureMessages": []}]}]})
GO_EVENTS = "\n".join(json.dumps(e) for e in [{"Action": "run", "Package": "x/p", "Test": "TestA"}, {"Action": "output", "Package": "x/p", "Test": "TestA", "Output": "    a_test.go:9: got 1 want 2\n"},
                                               {"Action": "fail", "Package": "x/p", "Test": "TestA"}, {"Action": "pass", "Package": "x/p", "Test": "TestB"},
                                               {"Action": "output", "Package": "x/q", "Output": "# x/q\nq.go:3:1: syntax error\n"}, {"Action": "fail", "Package": "x/q"}])
CARGO = ("running 2 tests\ntest tests::adds ... ok\ntest tests::overflow ... FAILED\n\nfailures:\n\n---- tests::overflow stdout ----\nthread 'tests::overflow' panicked at src/lib.rs:9:9:\n"
         "assertion `left == right` failed\n\nfailures:\n    tests::overflow\n\ntest result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured\n")
MAVEN = ("[INFO] Running com.acme.CalcTest\n[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.05 s <<< FAILURE! - in com.acme.CalcTest\n"
         "[ERROR] com.acme.CalcTest.overflow:14 expected:<3> but was:<4>\n[INFO] Results:\n[ERROR] Failures:\n[ERROR]   CalcTest.overflow:14 expected:<3> but was:<4>\n[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0\n")


def test_every_framework_output_normalises_to_one_shape():
    fw = lambda parser: frameworks.Framework(parser, "x", [], parser)  # noqa: E731
    j = frameworks.parse(fw("jest"), "PASS banner\n" + JEST + "\ntrailing")
    assert j["counts"] == {"passed": 2, "failed": 1, "skipped": 0, "error": 0} and j["failed_tests"][0]["id"].endswith("adds overflow") and "Expected: 3" in j["failed_tests"][0]["message"]
    m = frameworks.parse(fw("mocha"), json.dumps({"stats": {"tests": 2, "passes": 1, "failures": 1}, "failures": [{"fullTitle": "A b", "err": {"message": "boom"}}]}))
    assert m["counts"]["failed"] == 1 and m["failed_tests"] == [{"id": "A b", "kind": "failed", "message": "boom"}]
    g = frameworks.parse(fw("go"), GO_EVENTS)
    assert g["counts"] == {"passed": 1, "failed": 2, "skipped": 0} and {t["id"] for t in g["failed_tests"]} == {"x/p::TestA", "x/q"} and "got 1 want 2" in g["failed_tests"][0]["message"]
    c = frameworks.parse(fw("cargo"), CARGO)
    assert c["counts"] == {"passed": 1, "failed": 1, "skipped": 0} and c["failed_tests"][0]["id"] == "tests::overflow" and "left == right" in c["failed_tests"][0]["message"]
    mv = frameworks.parse(fw("maven"), MAVEN)
    assert mv["counts"] == {"passed": 2, "failed": 1, "skipped": 0} and mv["total"] == 3 and mv["failed_tests"]
    gr = frameworks.parse(fw("gradle"), "> Task :test\nCalcTest > overflow() FAILED\n3 tests completed, 1 failed\n")
    assert gr["counts"] == {"passed": 2, "failed": 1} and gr["failed_tests"][0]["id"] == "CalcTest > overflow()"
    assert frameworks.parse(fw("generic"), "anything")["total"] == 0


def test_run_tests_maps_other_frameworks_through_the_sandbox(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"jest": "29"}}))
    monkeypatch.setattr(sandbox_exec, "run", lambda *a, **k: sandbox_exec.ExecResult(1, stdout=JEST, mode="docker", image="node-img", duration_ms=40))
    r = sandbox.run_tests(tmp_path, 30)
    assert r["status"] == "failed" and r["framework"] == "jest" and r["counts"]["failed"] == 1 and r["sandbox"] == {"mode": "docker", "image": "node-img"} and r["failed_tests"]
    monkeypatch.setattr(sandbox_exec, "run", lambda *a, **k: sandbox_exec.ExecResult(0, stdout=json.dumps({"numTotalTests": 0, "testResults": []})))
    assert sandbox.run_tests(tmp_path, 30)["status"] == "no_tests"
    monkeypatch.setattr(sandbox_exec, "run", lambda *a, **k: sandbox_exec.ExecResult(1, stderr="No tests found, exiting with code 1"))
    assert sandbox.run_tests(tmp_path, 30)["status"] == "no_tests"
    assert sandbox.run_tests(tmp_path / "empty", 5)["status"] == "no_tests"


# ---- coverage --------------------------------------------------------------------------------------------------------------------------------------
def test_coverage_for_python_via_the_runner():
    work = sandbox.copy_repo(FIXTURE)
    try:
        r = sandbox.run_tests(work, 120, coverage=True)
    finally:
        sandbox.cleanup(work)
    cov = r["coverage"]
    assert r["status"] == "failed" and cov["tool"] == "coverage.py" and 0 < cov["percent"] <= 100
    files = {f["path"]: f for f in cov["files"]}
    assert files["auth.py"]["percent"] == 0.0 and "6-9" in files["auth.py"]["missing"] and files["services/eta.py"]["percent"] == 100.0
    assert not any(p.startswith("tests/") for p in files)                                    # test files are not "covered code"


def test_coverage_parsers_for_jest_and_go(tmp_path):
    (tmp_path / coverage.JS_DIR).mkdir()
    (tmp_path / coverage.JS_DIR / "coverage-summary.json").write_text(json.dumps({"total": {"lines": {"pct": 50}}, "/work/src/a.js": {"lines": {"total": 10, "covered": 5, "pct": 50}},
                                                                                  "/work/src/a.test.js": {"lines": {"total": 4, "covered": 4, "pct": 100}}}))
    cov = coverage.collect(tmp_path, frameworks.Framework("jest", "node", [], "jest"))
    assert cov["percent"] == 50.0 and [f["path"] for f in cov["files"]] == ["src/a.js"]
    prof = "mode: set\nexample.com/m/pkg/a.go:3.10,5.2 2 1\nexample.com/m/pkg/a.go:7.2,9.3 3 0\nexample.com/m/pkg/a_test.go:1.1,2.2 1 1\n"
    g = coverage.parse_go_profile(prof)
    assert g["percent"] == 40.0 and len(g["files"]) == 1 and g["files"][0]["missing"] == ["7-9"]
    assert coverage.collect(tmp_path / "none", frameworks.Framework("pytest", "python", [], "pytest")) is None
    assert coverage.supported(frameworks.Framework("go", "go", [], "go")) and not coverage.supported(frameworks.Framework("cargo", "rust", [], "cargo"))


# ---- analyzers: the real tools ------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def messy(tmp_path):
    (tmp_path / "app.py").write_text('''import os
import subprocess
import hashlib


def run(cmd, items=[]):
    subprocess.run(cmd, shell=True)
    return eval(cmd) + hashlib.md5(cmd.encode()).hexdigest() + undefined_name


def add(a: int, b: int) -> int:
    return a + "x"
''')
    return tmp_path


def codes(res):
    return {(f.code, f.severity) for f in res.findings}


@pytest.mark.skipif(not have("ruff"), reason="ruff not installed")
def test_ruff_finds_blocking_undefined_names(messy):
    r = analyzers.run(messy, "ruff")
    assert r.status == "issues" and any(f.code == "F821" and f.blocking and f.severity == "high" for f in r.findings) and any(f.code == "F401" for f in r.findings)


@pytest.mark.skipif(not have("pylint"), reason="pylint not installed")
def test_pylint(messy):
    r = analyzers.run(messy, "pylint")
    assert r.status == "issues" and any(f.code == "E0602" and f.blocking for f in r.findings) and any(f.file == "app.py" and f.line == 6 for f in r.findings)


@pytest.mark.skipif(not have("mypy"), reason="mypy not installed")
def test_mypy(messy):
    r = analyzers.run(messy, "mypy")
    assert r.category == "types" and any(f.file == "app.py" and f.line == 12 and "operand" in f.message.lower() for f in r.findings) and all(f.severity == "medium" for f in r.findings)


@pytest.mark.skipif(not have("bandit"), reason="bandit not installed")
def test_bandit(messy):
    r = analyzers.run(messy, "bandit")
    got = {f.code: f for f in r.findings}
    assert r.category == "security" and got["B602"].severity == "high" and got["B602"].cwe == "CWE-78" and "B307" in got and "B324" in got


@pytest.mark.skipif(not have("semgrep"), reason="semgrep not installed")
def test_semgrep_with_the_bundled_offline_rules(messy):
    r = analyzers.run(messy, "semgrep")
    assert {f.code for f in r.findings} >= {"python-subprocess-shell-true", "python-eval-exec"} and all(f.cwe.startswith("CWE-") for f in r.findings)


def test_clean_code_is_clean(tmp_path):
    (tmp_path / "ok.py").write_text('"""Fine."""\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n')
    for name in ("ruff", "bandit", "mypy"):
        if have(name):
            assert analyzers.run(tmp_path, name).status == "ok", name


# ---- analyzers: recorded output (tools that need a toolchain or network) ------------------------------------------------------------------------------------
def canned(monkeypatch, stdout="", stderr="", rc=0):
    monkeypatch.setattr(analyzers, "_exec", lambda *a, **k: (sandbox_exec.ExecResult(rc, stdout=stdout, stderr=stderr, duration_ms=5), None))


def test_pip_audit_is_off_by_default_and_parses_when_allowed(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("flask==0.12\n")
    r = analyzers.run(tmp_path, "pip-audit")
    assert r.status == "skipped" and "SANDBOX_AUDIT_NETWORK" in r.summary
    monkeypatch.setenv("SANDBOX_AUDIT_NETWORK", "true")
    canned(monkeypatch, json.dumps({"dependencies": [{"name": "flask", "version": "0.12", "vulns": [{"id": "PYSEC-2018-66", "fix_versions": ["0.12.3"], "aliases": ["CVE-2018-1000656"],
                                                                                                "description": "DoS via crafted JSON"}]}, {"name": "click", "version": "8.0", "vulns": []}]}))
    r = analyzers.run(tmp_path, "pip-audit")
    assert r.status == "issues" and r.findings[0].category == "dependency" and r.findings[0].cwe == "CVE-2018-1000656" and "upgrade to 0.12.3" in r.findings[0].fix and "flask 0.12" in r.findings[0].message
    seen = {}
    monkeypatch.setattr(analyzers, "_exec", lambda root, argv, lang, timeout, network=False, env=None: seen.update(argv=argv, net=network) or (sandbox_exec.ExecResult(0, stdout='{"dependencies": []}'), None))
    analyzers.run(tmp_path, "pip-audit")
    assert seen["net"] is True and "--disable-pip" in seen["argv"] and "--no-deps" in seen["argv"]            # never resolves (= builds) packages: only reads pinned requirements


def test_npm_audit(tmp_path, monkeypatch):
    (tmp_path / "package-lock.json").write_text("{}")
    assert analyzers.run(tmp_path, "npm-audit").status == "skipped"
    monkeypatch.setenv("SANDBOX_AUDIT_NETWORK", "true")
    canned(monkeypatch, json.dumps({"vulnerabilities": {"lodash": {"name": "lodash", "severity": "high", "range": "<4.17.21", "via": [{"title": "Prototype Pollution", "url": "https://github.com/advisories/GHSA-x"}],
                                                                   "fixAvailable": {"name": "lodash", "version": "4.17.21"}},
                                                        "minimist": {"name": "minimist", "severity": "moderate", "via": ["x"], "range": "*", "fixAvailable": False}}}))
    r = analyzers.run(tmp_path, "npm-audit")
    sev = {f.message.split()[0]: f.severity for f in r.findings}
    assert sev == {"lodash": "high", "minimist": "medium"} and r.findings[0].fix.startswith("run npm audit fix") and r.findings[0].file == "package-lock.json"


def test_go_vet_and_clippy_and_eslint(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("module x\n")
    canned(monkeypatch, stderr="# x/p\np/a.go:12:5: Printf format %d has arg s of wrong type string\n")
    r = analyzers.run(tmp_path, "go-vet")
    assert [(f.file, f.line, f.col) for f in r.findings] == [("p/a.go", 12, 5)] and "Printf" in r.findings[0].message
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    msg = lambda level, code, line: json.dumps({"reason": "compiler-message", "message": {"level": level, "message": f"{code} problem", "code": {"code": code}, "spans": [{"file_name": "src/lib.rs", "line_start": line, "column_start": 1, "is_primary": True}]}})  # noqa: E731
    canned(monkeypatch, stdout="\n".join([msg("warning", "clippy::needless_return", 4), msg("error", "E0308", 9), json.dumps({"reason": "build-finished"})]))
    r = analyzers.run(tmp_path, "clippy")
    assert [(f.code, f.severity, f.blocking) for f in r.findings] == [("clippy::needless_return", "low", False), ("E0308", "high", True)]
    (tmp_path / ".eslintrc.json").write_text("{}")
    (tmp_path / "a.js").write_text("x\n")
    canned(monkeypatch, stdout=json.dumps([{"filePath": "/work/a.js", "messages": [{"ruleId": "no-undef", "severity": 2, "line": 1, "column": 1, "message": "x is not defined"},
                                                                                   {"ruleId": None, "fatal": True, "severity": 2, "line": 2, "column": 1, "message": "Parsing error"},
                                                                                   {"ruleId": "semi", "severity": 1, "line": 1, "column": 2, "message": "Missing semicolon"}]}]))
    r = analyzers.run(tmp_path, "eslint")
    assert [(f.code, f.severity, f.blocking) for f in r.findings] == [("no-undef", "high", True), ("parse-error", "high", True), ("semi", "low", False)] and r.findings[0].file == "a.js"
    (tmp_path / ".eslintrc.json").unlink()
    assert analyzers.run(tmp_path, "eslint").status == "skipped"


def test_missing_tools_and_a_missing_sandbox_are_reported_not_hidden(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(sandbox_exec, "run", lambda *a, **k: sandbox_exec.ExecResult(127, stderr='exec: "semgrep": executable file not found in $PATH'))
    r = analyzers.run(tmp_path, "semgrep")
    assert r.status == "unavailable" and "not installed" in r.summary
    def down(*a, **k):
        raise sandbox_exec.SandboxUnavailable("Docker is not available")
    monkeypatch.setattr(sandbox_exec, "run", down)
    assert analyzers.run(tmp_path, "bandit").status == "unavailable" and "Docker" in analyzers.run(tmp_path, "mypy").summary
    monkeypatch.setattr(sandbox_exec, "run", lambda *a, **k: sandbox_exec.ExecResult(-9, timed_out=True))
    assert analyzers.run(tmp_path, "mypy", 3).status == "timeout"
    assert analyzers.run(tmp_path, "ruff").status in ("unavailable", "ok", "issues")
    with pytest.raises(ValueError, match="unknown analyzer"):
        analyzers.run(tmp_path, "nope")


def test_applicable_analyzers_follow_the_project(tmp_path):
    assert analyzers.applicable(tmp_path) == []
    (tmp_path / "a.py").write_text("x=1\n")
    (tmp_path / "requirements.txt").write_text("flask==3\n")
    assert analyzers.applicable(tmp_path) == ["ruff", "pylint", "mypy", "bandit", "semgrep", "pip-audit"]
    (tmp_path / "go.mod").write_text("module m\n")
    (tmp_path / "package-lock.json").write_text("{}")
    assert {"go-vet", "npm-audit"} <= set(analyzers.applicable(tmp_path))


# ---- the score -------------------------------------------------------------------------------------------------------------------------------------------------
def res(tool, *sev, status="issues", blocking=False):
    return {"tool": tool, "status": status if (sev or status != "issues") else "ok", "findings": [Finding(tool, "x", "a.py", 1, "C", "m", s, blocking).to_dict() for s in sev]}


def test_score_weights_and_grades():
    tests = {"status": "passed", "counts": {"passed": 10}, "total": 10}
    perfect = score.compute(tests=tests, coverage={"percent": 100.0, "total": 50}, analyzers={"ruff": res("ruff"), "mypy": res("mypy"), "bandit": res("bandit")}, loc=2000, maint={"available": True, "functions": 20, "too_complex_or_long": 0, "avg_complexity": 2})
    assert perfect["overall"] == 100.0 and perfect["grade"] == "A" and perfect["not_measured"] == []
    failing = score.compute(tests={"status": "failed", "counts": {"passed": 5, "failed": 5}, "total": 10}, coverage=None, analyzers={}, loc=1000, maint={"available": False})
    assert failing["dimensions"]["tests"]["score"] == 50.0 and failing["overall"] == 50.0 and failing["grade"] == "F" and "coverage" in failing["not_measured"]      # only what was measured counts
    assert [score.grade(x) for x in (95, 85, 75, 65, 10)] == ["A", "B", "C", "D", "F"]
    none = score.compute(tests=None, coverage=None, analyzers={}, loc=10, maint={"available": False})
    assert none["overall"] is None and none["grade"] == "n/a"


def test_score_penalties():
    base = dict(tests={"status": "passed", "counts": {"passed": 1}, "total": 1}, coverage=None, loc=1000, maint={"available": False})
    sec = score.compute(**base, analyzers={"bandit": res("bandit", "critical", "high", "medium", "low")})["dimensions"]["security"]
    assert sec["score"] == 100 - (25 + 15 + 5 + 1) and "1 critical" in sec["detail"]
    assert score.compute(**base, analyzers={"bandit": res("bandit", *["critical"] * 5)})["dimensions"]["security"]["score"] == 0.0              # floors at 0
    lint = score.compute(**base, analyzers={"ruff": res("ruff", "low", "low", "low", "low")})["dimensions"]["lint"]["score"]
    worse = score.compute(**base, analyzers={"ruff": res("ruff", *["medium"] * 10)})["dimensions"]["lint"]["score"]
    assert 85 < lint < 100 and worse < lint
    types = score.compute(**base, analyzers={"mypy": res("mypy", *["medium"] * 5)})["dimensions"]["types"]["score"]
    assert types == 75.0                                                                    # 5 errors in 1 kLOC
    skipped = score.compute(**base, analyzers={"bandit": res("bandit", status="skipped")})
    assert "security" in skipped["not_measured"]                                            # a tool that did not run is not a clean bill of health


def test_maintainability_metrics(tmp_path):
    body = "\n".join(f"    if x == {i}:\n        y += {i}" for i in range(18))
    (tmp_path / "m.py").write_text(f"def tangled(x):\n    y = 0\n{body}\n    return y\n\n\ndef simple(a):\n    return a\n")
    m = score.maintainability(tmp_path)
    assert m["functions"] == 2 and m["too_complex_or_long"] == 1 and m["worst"][0]["name"] == "tangled" and m["worst"][0]["complexity"] == 19
    assert score.maintainability(tmp_path / "empty")["available"] is False


# ---- the run -----------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_a_quality_run_on_the_fixture():
    r = runner.run_quality(FIXTURE, test_timeout=120)
    assert r["frameworks"] == ["pytest (test_*.py files)"] or r["frameworks"][0].startswith("pytest")
    t = r["tests"][0]
    assert t["status"] == "failed" and t["counts"] == {"failed": 1, "passed": 2} and r["coverage"]["percent"] > 0
    assert r["score"]["dimensions"]["tests"]["score"] == pytest.approx(66.7, abs=0.1) and r["score"]["grade"] in "ABCDF" and r["sandbox"]["mode"] == "local"
    assert set(r["analyzers"]) >= {"ruff"} and r["findings"] is not None and r["maintainability"]["available"]
    assert any("pip-audit" in n for n in r["notes"]) or "pip-audit" not in r["analyzers"]


def test_a_quality_run_without_a_sandbox_executes_nothing(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    monkeypatch.setenv("PATH", "/nonexistent")
    sandbox_exec.reset_cache()
    r = runner.run_quality(FIXTURE, test_timeout=20)
    assert r["tests"][0]["status"] == "sandbox_unavailable" and r["coverage"] is None
    assert any("Docker is not available" in n for n in r["notes"])
    assert "tests" in r["score"]["not_measured"] and r["score"]["dimensions"].get("tests") is None          # unknown is not zero
    assert all(a["status"] in ("unavailable", "skipped", "ok", "issues") for a in r["analyzers"].values()) and r["analyzers"]["mypy"]["status"] == "unavailable"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = m._conversations = m._patch_store = m._actions = m._quality = None
    c = TestClient(m.app)
    return c, c.post("/repositories", json={"source": str(FIXTURE), "name": "delivery"}).json()["id"], m


def test_quality_api_runs_in_the_background_and_keeps_history(api):
    c, rid, m = api
    info = c.get("/quality/analyzers", params={"repo_id": rid}).json()
    assert info["frameworks"][0].startswith("pytest") and {a["name"] for a in info["analyzers"] if a["applies"]} >= {"ruff", "bandit"}
    assert c.post("/quality/run", json={"repo_id": rid, "tools": ["nope"]}).status_code == 400
    jid = c.post("/quality/run", json={"repo_id": rid, "tools": ["ruff"], "coverage": True}).json()["id"]
    for _ in range(120):
        job = c.get(f"/quality/jobs/{jid}").json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done" and job["progress"] and job["report"]["score"]["overall"] is not None and list(job["report"]["analyzers"]) == ["ruff"]
    assert c.get("/quality/latest", params={"repo_id": rid}).json()["id"] == job["report"]["id"]
    assert c.get("/quality/history", params={"repo_id": rid}).json()[0]["grade"] in "ABCDF" and c.get("/quality/jobs/nope").status_code == 404
