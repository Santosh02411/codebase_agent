"""How to invoke an analysis tool: on the host (local mode, wherever it is installed) or by name inside the sandbox image."""
from __future__ import annotations
import shutil
import sys

from .. import sandbox_exec

MODULES = {"ruff": "ruff", "pylint": "pylint", "mypy": "mypy", "bandit": "bandit", "pip-audit": "pip_audit", "semgrep": "semgrep", "coverage": "coverage", "pytest": "pytest"}


def argv(tool: str, *args: str) -> list[str]:
    if sandbox_exec.mode() == "docker":
        return [tool, *args]                      # the sandbox image ships these tools (sandbox/Dockerfile.*)
    exe = shutil.which(tool)
    if exe:
        return [exe, *args]
    mod = MODULES.get(tool)
    if mod:
        import importlib.util
        if importlib.util.find_spec(mod):
            return [sys.executable, "-m", mod, *args]
    return [tool, *args]


def missing(res: sandbox_exec.ExecResult) -> bool:
    """True when the run failed because the tool is not installed (so the result says nothing about the code)."""
    err = (res.stderr + res.stdout)[:600].lower()
    return res.returncode in (126, 127) or "no module named" in err or "executable file not found" in err or "command not found" in err
