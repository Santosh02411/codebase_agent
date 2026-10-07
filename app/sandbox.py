from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .ingest import SKIP_DIRS


def copy_repo(src: Path) -> Path:
    work = Path(tempfile.mkdtemp(prefix="agent-sandbox-"))
    shutil.copytree(src, work / "repo", ignore=shutil.ignore_patterns(*SKIP_DIRS))
    return work / "repo"


def cleanup(work: Path) -> None:
    shutil.rmtree(work.parent, ignore_errors=True)


def run_tests(workdir: Path, timeout: int = 120, command: list[str] | None = None) -> dict:
    """Run the repo's tests in an isolated copy with secrets stripped from the environment.
    v1 = subprocess isolation (timeout, scrubbed env). Docker-based sandbox is a Phase 6 item."""
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update({"PYTHONPATH": str(workdir), "PYTHONDONTWRITEBYTECODE": "1"})
    cmd = command or [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    try:
        r = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "passed": False, "summary": f"timed out after {timeout}s", "output": ""}
    out = (r.stdout + r.stderr).strip()
    lines = [l for l in out.splitlines() if l.strip()]
    summary = lines[-1] if lines else ""
    status = {0: "passed", 1: "failed", 5: "no_tests"}.get(r.returncode, "error")
    return {"status": status, "passed": status == "passed", "summary": summary, "output": out[-3000:]}
