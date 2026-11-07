"""Detect a repository's test framework(s), build the command to run them (whole suite or specific tests) and parse the output into one shape:
{"counts": {passed, failed, skipped, errors}, "failed_tests": [{id, kind, message}], "total": n}.

pytest · unittest-style (run by pytest) · Jest · Vitest · Mocha · `npm test` · Go · Cargo · Maven · Gradle."""
from __future__ import annotations
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# -v prints one line per test (so every outcome is known), -rfEsxX lists failures, errors, skips and xfails with reasons, --tb=short keeps tracebacks readable
PYTEST = ["python", "-m", "pytest", "-v", "--tb=short", "-rfEsxX", "--maxfail=10", "-p", "no:cacheprovider"]


@dataclass
class Framework:
    name: str          # pytest | jest | vitest | mocha | npm | go | cargo | maven | gradle
    language: str      # python | node | go | rust | java
    command: list[str]
    parser: str
    evidence: str = ""  # why it was chosen

    def describe(self) -> str:
        return f"{self.name} ({self.evidence})" if self.evidence else self.name


def is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (path.startswith(("tests/", "test/", "__tests__/")) or "/tests/" in path or "/test/" in path or "/__tests__/" in path or name.startswith(("test_", "conftest"))
            or name.endswith(("_test.py", "_test.go", "_test.rs", "Test.java", "Tests.java", "Test.kt")) or ".test." in name or ".spec." in name or "src/test/" in path)


def _pkg(root: Path) -> dict:
    try:
        return json.loads((root / "package.json").read_text())
    except (OSError, ValueError):
        return {}


def detect_all(root: Path) -> list[Framework]:
    """Every test framework the repository appears to use, most likely primary first."""
    out: list[Framework] = []
    has_py = (root / "pytest.ini").exists() or (root / "tox.ini").exists() or (root / "conftest.py").exists() or (root / "tests").is_dir() \
        or any(root.glob("test_*.py")) or any(root.glob("**/test_*.py")) or any(root.glob("**/*_test.py"))
    toml = (root / "pyproject.toml").read_text(errors="ignore") if (root / "pyproject.toml").is_file() else ""
    if has_py or "[tool.pytest" in toml:
        ev = "pytest.ini" if (root / "pytest.ini").exists() else "[tool.pytest] in pyproject.toml" if "[tool.pytest" in toml else "test_*.py files"
        out.append(Framework("pytest", "python", list(PYTEST), "pytest", ev))
    pkg = _pkg(root)
    if pkg:
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        script = (pkg.get("scripts") or {}).get("test", "")
        if script and "no test specified" in script:
            script = ""
        if "vitest" in deps:
            out.append(Framework("vitest", "node", ["npx", "--no-install", "vitest", "run", "--reporter=json"], "vitest", "vitest in package.json"))
        elif "jest" in deps or "jest" in script:
            out.append(Framework("jest", "node", ["npx", "--no-install", "jest", "--ci", "--json"], "jest", "jest in package.json"))
        elif "mocha" in deps or "mocha" in script:
            out.append(Framework("mocha", "node", ["npx", "--no-install", "mocha", "--reporter", "json"], "mocha", "mocha in package.json"))
        elif script:
            out.append(Framework("npm", "node", ["npm", "test", "--silent"], "generic", f"scripts.test = {script[:40]!r}"))
    if (root / "go.mod").is_file():
        out.append(Framework("go", "go", ["go", "test", "-json", "./..."], "go", "go.mod"))
    if (root / "Cargo.toml").is_file():
        out.append(Framework("cargo", "rust", ["cargo", "test", "--no-fail-fast"], "cargo", "Cargo.toml"))
    if (root / "pom.xml").is_file():
        out.append(Framework("maven", "java", ["mvn", "-B", "-ntp", "test"], "maven", "pom.xml"))
    elif (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        out.append(Framework("gradle", "java", ["gradle", "test", "--no-daemon", "--console=plain"], "gradle", "build.gradle"))
    return out


def detect(root: Path) -> Framework | None:
    found = detect_all(root)
    return found[0] if found else None


def command_for(fw: Framework, targets: list[str] | None = None, local_python: bool = False) -> list[str]:
    """The argv for the whole suite, or narrowed to `targets` (files / test ids)."""
    cmd = list(fw.command)
    if local_python and cmd[:1] == ["python"]:
        cmd[0] = sys.executable
    targets = [t for t in (targets or []) if t and not t.startswith("-")]
    if not targets:
        return cmd
    if fw.name == "pytest":
        return cmd + targets
    if fw.name in ("jest", "vitest"):
        return cmd + (["--runTestsByPath"] if fw.name == "jest" else []) + targets
    if fw.name == "mocha":
        return cmd + targets
    if fw.name == "go":
        def pkg(t: str) -> str:
            path = t.split("::")[0]
            return "./" + (path.rsplit("/", 1)[0] if path.endswith(".go") and "/" in path else "" if path.endswith(".go") else path).lstrip("./")
        pkgs = sorted({pkg(t) for t in targets})
        run = [t.split("::")[1] for t in targets if "::" in t]
        return ["go", "test", "-json", *pkgs] + (["-run", "^(" + "|".join(run) + ")$"] if run else [])
    if fw.name == "cargo":
        return cmd + [targets[0].split("::", 1)[-1]] if "::" in targets[0] or "/" not in targets[0] else cmd
    if fw.name == "maven":
        return ["mvn", "-B", "-ntp", "test", "-Dtest=" + ",".join(t.replace("::", "#") for t in targets), "-DfailIfNoTests=false"]
    return cmd


# ---- parsing ---------------------------------------------------------------------------------------------------------------
def _empty() -> dict:
    return {"counts": {}, "failed_tests": [], "total": 0}


_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
_PYFAIL = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - (.*))?$", re.M)


def parse_pytest(out: str) -> dict:
    counts: dict[str, int] = {}
    for n, kind in _COUNT.findall(out.splitlines()[-1] if out else ""):
        counts[kind.rstrip("s") if kind.startswith("error") else kind] = int(n)
    failed = [{"id": m.group(2), "kind": m.group(1).lower(), "message": (m.group(3) or "")[:200]} for m in _PYFAIL.finditer(out)]
    return {"counts": counts, "failed_tests": failed, "total": sum(v for k, v in counts.items() if k in ("passed", "failed", "error", "skipped"))}


_VERB = re.compile(r"^(\S+?::\S+?) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.M)
_SKIP = re.compile(r"^SKIPPED \[\d+\] (\S+?):(\d+): (.*)$", re.M)
_HEAD = re.compile(r"^_{2,} (.+?) _{2,}$", re.M)
_FRAME = re.compile(r"^(\S+\.\w+):(\d+): in (\S+)", re.M)


def enrich_pytest(parsed: dict, out: str) -> dict:
    """Adds what the plain summary lacks, straight from pytest's own output: the outcome of every test that ran (`tests`), and for each failure its
    traceback, call frames (file:line) and the final `E ...` error lines. Nothing here is inferred: if pytest did not print it, it is absent."""
    tests = [{"id": m.group(1), "outcome": m.group(2).lower()} for m in _VERB.finditer(out)]
    seen: set[str] = set()
    uniq = []
    for t in tests:
        if t["id"] not in seen:
            seen.add(t["id"]); uniq.append(t)
    skips = {f"{m.group(1)}:{m.group(2)}": m.group(3) for m in _SKIP.finditer(out)}
    heads = list(_HEAD.finditer(out))
    sections: dict[str, str] = {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(out)
        body = out[h.end():end]
        cut = re.search(r"^={3,} ", body, re.M)       # the next "=== section ===" banner ends the traceback
        sections[h.group(1)] = (body[: cut.start()] if cut else body).strip("\n")
    for f in parsed["failed_tests"]:
        short = f["id"].split("::", 1)[-1]
        key = next((k for k in sections if k == short or k.replace(".", "::") == short or f["id"].endswith("::" + k) or f["id"].endswith(k.replace(".", "::"))), None)
        if key:
            tb = sections[key]
            frames = [{"file": m.group(1), "line": int(m.group(2)), "func": m.group(3)} for m in _FRAME.finditer(tb)]
            err = [l[1:].strip() for l in tb.splitlines() if l.startswith("E ")]
            f["traceback"] = tb[:6000]
            f["frames"] = frames[:12]
            if frames:
                f["location"] = {"file": frames[-1]["file"], "line": frames[-1]["line"]}
            if err:
                f["error"] = "\n".join(err)[:600]
    parsed = dict(parsed)
    parsed["tests"] = uniq[:3000]
    parsed["skipped_reasons"] = skips
    return parsed


def _json_blob(text: str, key: str) -> dict | None:
    """The JSON object in `text` that contains `key` (test runners print banners around it)."""
    i = text.find("{")
    while i != -1:
        for j in range(text.rfind("}"), i, -1):
            try:
                d = json.loads(text[i:j + 1])
            except ValueError:
                continue
            if isinstance(d, dict) and key in d:
                return d
            break
        i = text.find("{", i + 1)
    return None


def parse_jest(out: str) -> dict:
    d = _json_blob(out, "numTotalTests")
    if not d:
        return _empty()
    failed = []
    for f in d.get("testResults", []):
        rows = f.get("assertionResults") or []
        for a in rows:
            if a.get("status") == "failed":
                failed.append({"id": f"{f.get('name', '')}::{a.get('fullName') or a.get('title')}", "kind": "failed", "message": " ".join(a.get("failureMessages") or [])[:200].replace("\n", " ")})
        if f.get("status") == "failed" and not rows:      # suite failed to run (syntax / import error)
            failed.append({"id": f.get("name", ""), "kind": "error", "message": (f.get("message") or "")[:200].replace("\n", " ")})
    return {"counts": {"passed": d.get("numPassedTests", 0), "failed": d.get("numFailedTests", 0), "skipped": d.get("numPendingTests", 0), "error": d.get("numRuntimeErrorTestSuites", 0)},
            "failed_tests": failed, "total": d.get("numTotalTests", 0)}


def parse_mocha(out: str) -> dict:
    d = _json_blob(out, "stats")
    if not d:
        return _empty()
    st = d["stats"]
    failed = [{"id": f.get("fullTitle", ""), "kind": "failed", "message": (f.get("err") or {}).get("message", "")[:200]} for f in d.get("failures", [])]
    return {"counts": {"passed": st.get("passes", 0), "failed": st.get("failures", 0), "skipped": st.get("pending", 0)}, "failed_tests": failed, "total": st.get("tests", 0)}


def parse_go(out: str) -> dict:
    tests: dict[tuple[str, str], dict] = {}
    pkg_fail: dict[str, list[str]] = {}
    pkg_output: dict[str, list[str]] = {}
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        pkg, test, act = e.get("Package", ""), e.get("Test"), e.get("Action")
        if test:
            t = tests.setdefault((pkg, test), {"status": "", "out": []})
            if act in ("pass", "fail", "skip"):
                t["status"] = act
            elif act == "output":
                t["out"].append(e.get("Output", ""))
        else:
            if act == "output":
                pkg_output.setdefault(pkg, []).append(e.get("Output", ""))
            elif act == "fail":
                pkg_fail[pkg] = pkg_output.get(pkg, [])
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    failed = []
    for (pkg, name), t in tests.items():
        if "/" in name and any(k[1] == name.split("/")[0] for k in tests if k[0] == pkg):
            continue                                   # subtests are summarised by their parent
        st = t["status"]
        counts["passed" if st == "pass" else "skipped" if st == "skip" else "failed"] += 1
        if st == "fail":
            msg = " ".join(l.strip() for l in t["out"] if l.strip() and not l.startswith(("=== ", "--- ")))[:200]
            failed.append({"id": f"{pkg}::{name}", "kind": "failed", "message": msg})
    for pkg, lines in pkg_fail.items():
        if not any(k[0] == pkg and v["status"] == "fail" for k, v in tests.items()):   # package failed without a failing test: build error
            failed.append({"id": pkg, "kind": "error", "message": " ".join(l.strip() for l in lines if l.strip())[:200]})
            counts["failed"] += 1
    return {"counts": counts, "failed_tests": failed, "total": counts["passed"] + counts["failed"] + counts["skipped"]}


_CARGO_RESULT = re.compile(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored")
_CARGO_FAIL = re.compile(r"^test (\S+) \.\.\. FAILED$", re.M)


def parse_cargo(out: str) -> dict:
    p = f = i = 0
    for a, b, c in _CARGO_RESULT.findall(out):
        p, f, i = p + int(a), f + int(b), i + int(c)
    failed = [{"id": n, "kind": "failed", "message": ""} for n in _CARGO_FAIL.findall(out)]
    for name in [x["id"] for x in failed]:
        m = re.search(r"---- " + re.escape(name) + r" stdout ----\n(.*?)(?:\n\n|\Z)", out, re.S)
        if m:
            next(x for x in failed if x["id"] == name)["message"] = " ".join(m.group(1).split())[:200]
    if re.search(r"error(\[E\d+\])?: ", out) and not (p or f):     # did not compile
        m = re.search(r"error(?:\[E\d+\])?: (.*)", out)
        failed.append({"id": "build", "kind": "error", "message": (m.group(1) if m else "")[:200]})
        f += 1
    return {"counts": {"passed": p, "failed": f, "skipped": i}, "failed_tests": failed, "total": p + f + i}


_MVN_RUN = re.compile(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)")
_MVN_FAIL = re.compile(r"^\[ERROR\]\s+((?:[\w.$]+)[.#][\w$\[\]]+(?::\d+)?)\s+(.*)$", re.M)


def parse_maven(out: str) -> dict:
    runs = _MVN_RUN.findall(out)
    t, f, e, s = (int(x) for x in runs[-1]) if runs else (0, 0, 0, 0)       # the last line is the grand total
    failed = [{"id": m.group(1), "kind": "failed", "message": m.group(2)[:200]} for m in _MVN_FAIL.finditer(out) if "Tests run" not in m.group(0)]
    if not runs and "COMPILATION ERROR" in out:
        failed.append({"id": "build", "kind": "error", "message": "compilation error"})
        e = 1
    return {"counts": {"passed": max(0, t - f - e - s), "failed": f + e, "skipped": s}, "failed_tests": failed, "total": t}


def parse_gradle(out: str) -> dict:
    m = re.search(r"(\d+) tests completed, (\d+) failed", out)
    failed = [{"id": x, "kind": "failed", "message": ""} for x in re.findall(r"^(\S+ > \S+.*) FAILED$", out, re.M)]
    if m:
        t, f = int(m.group(1)), int(m.group(2))
        return {"counts": {"passed": t - f, "failed": f}, "failed_tests": failed, "total": t}
    return {"counts": {}, "failed_tests": failed, "total": 0}


def parse_generic(out: str) -> dict:
    return _empty()


PARSERS = {"pytest": parse_pytest, "jest": parse_jest, "vitest": parse_jest, "mocha": parse_mocha, "go": parse_go, "cargo": parse_cargo, "maven": parse_maven,
           "gradle": parse_gradle, "generic": parse_generic}


def parse(fw: Framework, output: str) -> dict:
    return PARSERS.get(fw.parser, parse_generic)(output)


def summarize(fw: Framework, parsed: dict, output: str) -> str:
    c = parsed["counts"]
    if fw.name == "pytest" and output:
        return output.splitlines()[-1].strip("= ") if output.splitlines() else ""
    if c:
        bits = [f"{c[k]} {k}" for k in ("passed", "failed", "error", "skipped") if c.get(k)]
        return ", ".join(bits) or "no tests ran"
    lines = [l for l in output.splitlines() if l.strip()]
    return lines[-1][:200] if lines else ""
