"""Verification of a patch: did the problem go away, and did anything else break?

`verify_patch` runs everything in throw-away copies of the repository: the baseline (tests + lint of the files the patch touches), a
*reproduction* (new regression tests alone against the ORIGINAL code: they should fail there), and the result with the patch applied.
`judge` turns those runs into one honest verdict. A green suite is not proof of a fix when nothing was failing before, and the verdict says so."""
from __future__ import annotations
import re
from pathlib import Path

from . import lint, patching, sandbox
from .patchset import PatchSpec, build_patchset

from .quality.frameworks import is_test_path as is_test_file  # noqa: E402,F401  (pytest, Jest/Vitest/Mocha, Go, Rust, Maven/Gradle conventions)


def _failed_ids(run: dict | None) -> set[str]:
    return {t["id"] for t in (run or {}).get("failed_tests", [])}


def judge(test_before: dict | None, test_after: dict | None, *, regression: dict | None = None, lint_new: list[dict] | None = None,
          intent: str = "debug") -> dict:
    """-> {status: resolved | partial | no_regressions | unverified | not_resolved, summary, reasons, fixed_tests, new_failures, ...}"""
    reasons: list[str] = []
    before_failed, after_failed = _failed_ids(test_before), _failed_ids(test_after)
    fixed, new, remaining = sorted(before_failed - after_failed), sorted(after_failed - before_failed), sorted(after_failed & before_failed)
    if (test_after or {}).get("scope") == "selected":
        fixed = []      # only the tests covering the change ran: a test that is absent from this run was not fixed, it was not run
    blocking = [i for i in (lint_new or []) if i.get("blocking")]
    a = (test_after or {}).get("status", "not_run")
    b = (test_before or {}).get("status", "not_run")
    reproduced = None
    if regression:
        reproduced = bool(regression.get("failed_before"))
    out = {"fixed_tests": fixed, "new_failures": new, "remaining_failures": remaining, "reproduced": reproduced,
           "lint_new": len(lint_new or []), "lint_new_blocking": len(blocking), "reasons": reasons}

    def done(status: str, summary: str) -> dict:
        return {**out, "status": status, "summary": summary}

    if blocking:
        reasons += [f"{i['file']}:{i['line']} {i['code']} {i['message']}" for i in blocking[:3]]
        return done("not_resolved", f"the change introduced {len(blocking)} blocking lint error(s)")
    if a == "sandbox_unavailable":
        reasons.append((test_after or {}).get("summary", "")[:200])
        return done("unverified", "the sandbox is not available, so no repository code was executed and the change could not be verified")
    if a == "timeout":
        return done("unverified", "the test run timed out, so the change could not be verified")
    if a == "not_run":
        return done("unverified", "tests were not run")
    if a == "no_tests":
        return done("unverified", "the project has no tests to run")
    if a == "error":
        reasons.append((test_after or {}).get("summary", ""))
        return done("not_resolved", "the test run errored after the change (collection or import failure)")
    if new:
        reasons += new[:5]
        return done("not_resolved", f"{len(new)} test(s) fail after the change that did not fail before")
    if regression and reproduced and regression.get("passed_after"):
        extra = f" ({len(remaining)} unrelated failure(s) remain)" if remaining else ""
        return done("resolved", "a regression test that reproduces the problem fails on the original code and passes with the fix" + extra)
    if a == "failed" and not after_failed:           # a non-pytest runner: we only know it failed
        return done("not_resolved" if b != "failed" or intent == "debug" else "unverified", "tests still fail after the change")
    if fixed:
        if remaining:
            reasons += remaining[:5]
            return done("partial", f"{len(fixed)} failing test(s) now pass; {len(remaining)} other failure(s) remain")
        return done("resolved", f"{len(fixed)} test(s) that failed before now pass and nothing else broke")
    if a == "passed" and b == "failed":
        return done("resolved", "the test suite failed before the change and passes now")
    if intent != "debug":
        extra = f"; {len(remaining)} pre-existing failure(s) are unchanged" if remaining else ""
        return done("no_regressions", "no new test failures and no new blocking lint errors" + extra)
    if a == "passed":
        if regression and regression.get("missing_symbol"):
            reasons.append("the regression test fails on the original code only because it references something the patch adds, so it does not demonstrate the bug")
        elif regression and not reproduced:
            reasons.append("the regression test also passes on the original code, so it does not demonstrate the bug")
        return done("unverified", "the tests pass, but they also passed before the change, so nothing demonstrated that the reported problem is fixed")
    reasons += remaining[:5]
    return done("not_resolved", "the failing tests still fail after the change")


def baseline_checks(root: Path, paths: list[str], timeout: int, lint_timeout: int = 60, coverage: bool = False) -> dict:
    work = sandbox.copy_repo(root)
    try:
        return {"tests": sandbox.run_tests(work, timeout, coverage=coverage), "lint": lint.run_linter(work, [p for p in paths if (work / p).is_file()] or None, lint_timeout)}
    finally:
        sandbox.cleanup(work)


def coverage_delta(before: dict | None, after: dict | None, files: list[str]) -> dict | None:
    """Overall and per-file coverage before / after a patch (None if it could not be measured on both sides)."""
    if not before or not after:
        return None
    b = {f["path"]: f for f in before.get("files", [])}
    a = {f["path"]: f for f in after.get("files", [])}
    paths = [p for p in files if p in a] or [p for p in sorted(a, key=lambda q: a[q]["percent"] - b.get(q, {}).get("percent", 0.0), reverse=True)
                                              if a[p]["percent"] != b.get(p, {}).get("percent", 0.0)][:5]     # no named target: the files whose coverage actually moved
    rows = [{"path": p, "before": b.get(p, {}).get("percent", 0.0), "after": a[p]["percent"], "missing": a[p].get("missing", [])} for p in paths]
    return {"before": before["percent"], "after": after["percent"], "files": rows}


def selected_tests(root: Path, changed: list[str]) -> list[str] | None:
    """Test files that can be affected by `changed` (import graph + naming convention), or None to run everything."""
    try:
        from .ingest import iter_source_files
        from .intel import graph as _g   # noqa: F401  (graph module is the source of the import relationships)
        from .quality.select import select_tests
        tree = [rel for rel, _ in iter_source_files(root)]
        imported_by = _imported_by(root, tree)
        return select_tests(changed, tree, imported_by)
    except Exception:           # selection is an optimisation: any problem means "run the whole suite"
        return None


def _imported_by(root: Path, tree: list[str]) -> dict[str, set[str]]:
    """Internal-import map for Python / JS / TS files from import statements (cheap, no index needed)."""
    import ast
    mods: dict[str, str] = {}
    for f in tree:
        if f.endswith(".py"):
            mods[f[:-3].replace("/", ".")] = f
            if f.endswith("/__init__.py"):
                mods[f[: -len("/__init__.py")].replace("/", ".")] = f
    out: dict[str, set[str]] = {}
    for f in tree:
        if not f.endswith(".py"):
            continue
        try:
            t = ast.parse((root / f).read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for n in ast.walk(t):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    parts = f.split("/")[:-n.level]
                    base = ".".join(parts + ([base] if base else []))
                names = [base] + [f"{base}.{a.name}" if base else a.name for a in n.names]
            for name in names:
                tgt = mods.get(name)
                if tgt and tgt != f:
                    out.setdefault(tgt, set()).add(f)
    return out


def verify_patch(root: Path, spec: dict, *, timeout: int = 120, baseline: dict | None = None, intent: str = "debug", progress=None, coverage: bool = False, coverage_files: list[str] | None = None) -> dict:
    """Everything needed to judge a patch. `baseline` ({tests, lint}) is reused if the caller already has it for this repository state."""
    say = progress or (lambda _m: None)
    ps = build_patchset(root, PatchSpec.from_dict(spec), allow_noop=True)
    changed = [c.path for c in ps.changes if c.op != "delete"]
    existing = [c.path for c in ps.changes if c.op != "create"]
    need_cov = coverage and not (baseline or {}).get("tests", {}).get("coverage")
    if baseline is None or need_cov:
        say("Running the tests and linter on the original code…")
        baseline = baseline_checks(root, existing, timeout, coverage=coverage) if baseline is None or need_cov else baseline
    base = baseline
    if "lint" not in base:
        base = {**base, "lint": baseline_checks(root, existing, timeout)["lint"]}
    new_tests = [c.path for c in ps.changes if c.op == "create" and is_test_file(c.path)]
    regression = None
    if new_tests and intent != "tests":
        say("Checking that the new regression test fails on the original code…")
        work = sandbox.copy_repo(root)
        try:
            patching.apply_spec(work, {"new_files": [f for f in spec.get("new_files", []) if f.get("path") in new_tests]})
            before = sandbox.run_tests(work, timeout, targets=new_tests)
        finally:
            sandbox.cleanup(work)
        failed_before = before["status"] == "failed" and bool(before.get("failed_tests"))
        # a test that fails only because it imports / calls something the patch itself adds does not demonstrate the bug
        missing_symbol = failed_before and all(re.search(r"ImportError|ModuleNotFoundError|cannot import name|has no attribute|NameError|is not defined|is not a function|Cannot find module",
                                                         f.get("message", "")) for f in before["failed_tests"])
        regression = {"tests": new_tests, "before": before, "failed_before": failed_before and not missing_symbol, "missing_symbol": bool(missing_symbol)}
    say("Running the tests and linter with the patch applied…")
    work = sandbox.copy_repo(root)
    try:
        patching.apply_spec(work, spec)
        after = None
        targeted = selected_tests(root, changed)
        if targeted and not coverage:
            say(f"Running the {len(targeted)} test file(s) that cover the changed code first…")
            quick = sandbox.run_tests(work, timeout, targets=targeted)
            if quick["status"] == "failed" and quick.get("failed_tests"):
                after = dict(quick, selected=targeted, scope="selected")     # already failing: no need for the full run to know the patch is not good
        if after is None:
            after = sandbox.run_tests(work, timeout, coverage=coverage)
        lint_after = lint.run_linter(work, changed or None, 60) if changed else {"issues": [], "counts": {"total": 0, "errors": 0, "warnings": 0, "blocking": 0},
                                                                                  "tool": "none", "status": "clean", "summary": "nothing to lint"}
    finally:
        sandbox.cleanup(work)
    if regression:
        ids = {t for t in new_tests}
        ran = after["status"] in ("passed", "failed")      # error / timeout / sandbox_unavailable: the tests did not run, so they cannot have passed
        regression["passed_after"] = ran and (after["status"] == "passed" or not any(f["id"].split("::")[0] in ids for f in after.get("failed_tests", [])))
        regression["after_failed"] = [f["id"] for f in after.get("failed_tests", []) if f["id"].split("::")[0] in ids]
    new_lint = lint.new_issues(base.get("lint"), lint_after)
    verdict = judge(base["tests"], after, regression=regression, lint_new=new_lint, intent=intent)
    cov = coverage_delta(base["tests"].get("coverage"), after.get("coverage"),
                         coverage_files or [c.path for c in ps.changes if c.op != "delete" and not is_test_file(c.path)]) if coverage else None
    return {"coverage": cov, "test_before": base["tests"], "test_after": after, "lint_before": base.get("lint"), "lint_after": lint_after, "lint_new": new_lint,
            "regression": regression, "verification": verdict, "baseline": base}
