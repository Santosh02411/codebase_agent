from __future__ import annotations
import time
import shutil
import sys
import tempfile
from pathlib import Path

from . import sandbox_exec
from .config import get_settings
from .ingest import SKIP_DIRS
from .quality import coverage as coverage_mod
from .quality import frameworks
from .quality.frameworks import parse_pytest  # noqa: F401  (re-exported)


def copy_repo(src: Path) -> Path:
    work = Path(tempfile.mkdtemp(prefix="agent-sandbox-"))
    shutil.copytree(src, work / "repo", ignore=shutil.ignore_patterns(*SKIP_DIRS), symlinks=True, ignore_dangling_symlinks=True)   # symlinks stay links: nothing outside the repo is copied in
    return work / "repo"


def cleanup(work: Path) -> None:
    shutil.rmtree(work.parent, ignore_errors=True)


def detect_command(root: Path) -> list[str]:
    """The command that runs this project's tests (pytest, npm/Jest/Vitest/Mocha, go, cargo, mvn, gradle)."""
    fw = frameworks.detect(root)
    return frameworks.command_for(fw, None, local_python=sandbox_exec.mode() == "local") if fw else frameworks.command_for(frameworks.Framework("pytest", "python", list(frameworks.PYTEST), "pytest"), None, sandbox_exec.mode() == "local")


def _result(status: str, summary: str, fw_name: str, shown: str, **kw) -> dict:
    return {"status": status, "passed": status == "passed", "summary": summary, "output": kw.pop("output", ""), "command": shown, "failed_tests": [], "counts": {}, "total": 0,
            "duration_ms": 0, "framework": fw_name, "coverage": None, "coverage_supported": False, "executed": False, "exit_code": None, "tests": [], "sandbox": kw.pop("sandbox", {"mode": sandbox_exec.mode()}), **kw}


def prepare_dependencies(workdir: Path, fw: frameworks.Framework, timeout: int = 300) -> str:
    """Optional (SANDBOX_INSTALL_DEPS): install the project's dependencies in ONE separate networked container so the test run itself can stay offline.
    No install scripts run: pip refuses source builds (--only-binary), npm gets --ignore-scripts. Returns a note, or '' when nothing was done."""
    plans = {"python": (["pip", "install", "--no-input", "--disable-pip-version-check", "--only-binary=:all:", "--target", "/work/.sandbox-deps", "-r", "requirements.txt"], "requirements.txt"),
             "node": (["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"] if (workdir / "package-lock.json").exists() else ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], "package.json"),
             "go": (["go", "mod", "download"], "go.mod"), "rust": (["cargo", "fetch"], "Cargo.toml"), "java": (["mvn", "-B", "-ntp", "dependency:go-offline"], "pom.xml")}
    cmd, marker = plans.get(fw.language, (None, ""))
    if not cmd or not (workdir / marker).exists():
        return ""
    try:
        r = sandbox_exec.run(workdir, cmd, language=fw.language, timeout=timeout, network=True)
    except sandbox_exec.SandboxUnavailable:
        return ""
    return f"dependencies installed (exit {r.returncode}, {r.duration_ms // 1000}s)" if r.returncode == 0 else f"dependency install failed (exit {r.returncode}): {r.output[-200:]}"


def run_tests(workdir: Path, timeout: int = 120, command: list[str] | None = None, targets: list[str] | None = None,
              framework: frameworks.Framework | None = None, coverage: bool = False) -> dict:
    """Run the repo's tests inside the sandbox (app/sandbox_exec.py) and return one normalised result, whatever the framework."""
    fw = framework or frameworks.detect(workdir)
    local = sandbox_exec.mode() == "local"
    if command:
        argv = list(command)
        if not local and argv[0] == sys.executable:
            argv[0] = "python"
        fw = fw or frameworks.Framework("pytest", "python", argv, "pytest")
        if targets and "pytest" in " ".join(argv):
            argv += [t for t in targets if t and not t.startswith("-")]
    elif fw is None:
        return _result("no_tests", "no test framework detected (looked for pytest, Jest/Vitest/Mocha, go.mod, Cargo.toml, pom.xml, build.gradle)", "none", "")
    else:
        argv = frameworks.command_for(fw, targets, local_python=local)
    want_cov = coverage and not command and coverage_mod.supported(fw)
    if want_cov:
        argv = coverage_mod.command(fw, argv)
    shown = " ".join(argv).replace(sys.executable, "python")
    note = ""
    if get_settings().sandbox_install_deps and not command:
        note = prepare_dependencies(workdir, fw)
    env = {"PYTHONPATH": "/work:/work/.sandbox-deps" if not local else str(workdir)} if fw.language == "python" else {}
    try:
        res = sandbox_exec.run(workdir, argv, language=fw.language, timeout=timeout, env=env)
    except sandbox_exec.SandboxUnavailable as e:
        return _result("sandbox_unavailable", str(e), fw.name, shown, sandbox={"mode": sandbox_exec.mode()})
    sbx = {"mode": res.mode, "image": res.image}
    if res.timed_out:
        return _result("timeout", f"timed out after {timeout}s", fw.name, shown, sandbox=sbx, duration_ms=timeout * 1000, output=res.output[-20000:], exit_code=res.returncode, executed=True, executed_at=time.time())
    out = res.output
    parsed = frameworks.parse(fw, res.stdout if fw.parser in ("jest", "vitest", "mocha", "go") else out)
    if fw.parser in ("jest", "vitest", "mocha", "go") and not parsed["total"] and not parsed["failed_tests"]:
        parsed = frameworks.parse(fw, out)
    if fw.parser == "pytest":
        parsed = frameworks.enrich_pytest(parsed, res.output)     # per-test outcomes + tracebacks, from pytest's own output
    failed = bool(parsed["failed_tests"] or parsed["counts"].get("failed"))
    if fw.parser == "pytest":
        status = {0: "passed", 1: "failed", 5: "no_tests"}.get(res.returncode, "error")
    elif res.returncode == 0:
        status = "passed" if parsed["total"] or not parsed["counts"] else "no_tests"
        if fw.name in ("npm", "gradle") and not parsed["total"]:
            status = "passed"
    else:
        status = "failed" if failed else "error"
    if status == "error" and any(x in out.lower() for x in ("no tests found", "no test files", "no tests to run")):
        status = "no_tests"
    summary = frameworks.summarize(fw, parsed, out)
    cov = coverage_mod.collect(workdir, fw) if want_cov else None
    return {"coverage": cov, "coverage_supported": coverage_mod.supported(fw), "status": status, "passed": status == "passed", "summary": (summary + (f" [{note}]" if note else ""))[:300], "output": out[-60000:], "command": shown,
            "duration_ms": res.duration_ms, "framework": fw.name, "sandbox": sbx, "truncated": res.truncated or len(out) > 60000, "exit_code": res.returncode, "stderr": (res.stderr or "")[-8000:],
            "executed": True, "executed_at": time.time(), "tests": parsed.get("tests", []), "skipped_reasons": parsed.get("skipped_reasons", {}),
            **{k: parsed[k] for k in ("counts", "failed_tests", "total")}}
