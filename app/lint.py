"""Run the project's linter and report issues in one shape, whatever the tool.

Python: ruff (uses the project's own config), else flake8, else pyflakes; always plus a built-in syntax check so a broken file is
caught even with no linter installed. JavaScript / TypeScript: the project's own ESLint if it is installed in node_modules.
Only a small set of findings is *blocking* (syntax errors, undefined names, invalid comparisons): style findings are reported but never
fail a patch. `new_issues(before, after)` is what a patch is judged on: findings the patch introduced, not ones that were already there."""
from __future__ import annotations
import ast
import json
import os
import re
import sys
from pathlib import Path

from . import sandbox_exec
from .quality import tools as tools_mod

BLOCKING = re.compile(r"^(E9|F63|F7|F82|invalid-syntax)")
PY_EXT, JS_EXT = (".py",), (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next"}
MAX_ISSUES = 200


class _Out:
    def __init__(self, r: sandbox_exec.ExecResult) -> None:
        self.returncode, self.stdout, self.stderr = r.returncode, r.stdout, r.stderr


UNAVAILABLE: list[str] = []      # why linting could not run (sandbox down); surfaced in the result


def _run(cmd: list[str], cwd: Path, timeout: int, language: str = "python") -> "_Out | None":
    """Linters execute project config (ESLint configs and plugins are code), so they run in the sandbox like everything else, on a read-only mount."""
    try:
        r = sandbox_exec.run(cwd, cmd, language=language, timeout=timeout, readonly=True)
    except sandbox_exec.SandboxUnavailable as e:
        UNAVAILABLE[:] = [str(e)]
        return None
    return None if tools_mod.missing(r) else _Out(r)


def _issue(file: str, line: int, col: int, code: str | None, message: str, severity: str = "error") -> dict:
    code = code or "E999"
    return {"file": file, "line": line or 0, "col": col or 0, "code": code, "message": message.strip()[:300], "severity": severity,
            "blocking": bool(BLOCKING.match(code))}


def _builtin(root: Path, files: list[str]) -> list[dict]:
    out = []
    for f in files:
        p = root / f
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if f.endswith(".py"):
            try:
                ast.parse(text)
            except SyntaxError as e:
                out.append(_issue(f, e.lineno or 0, e.offset or 0, "E999", f"SyntaxError: {e.msg}"))
        elif f.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as e:
                out.append(_issue(f, getattr(e, "lineno", 0), getattr(e, "colno", 0), "E999", f"invalid JSON: {str(e)[:120]}"))
    return out


def _python(root: Path, targets: list[str], timeout: int) -> tuple[str, list[dict], str] | None:
    """-> (tool, issues, command) or None when no Python linter is available."""
    for tool, cmd in (("ruff", tools_mod.argv("ruff", "check", "--no-cache", "--output-format", "json", "--exit-zero")),
                      ("flake8", tools_mod.argv("flake8", "--format", "%(path)s:%(row)d:%(col)d:%(code)s:%(text)s", "--exit-zero")),
                      ("pyflakes", tools_mod.argv("pyflakes"))):
        r = _run(cmd + targets, root, timeout)
        if r is None or (r.returncode not in (0, 1) or "No module named" in r.stderr):
            continue
        shown = " ".join(cmd[2:] if cmd[0] == sys.executable else [Path(cmd[0]).name, *cmd[1:]]) + " " + " ".join(targets[:3])
        issues = []
        if tool == "ruff":
            try:
                for d in json.loads(r.stdout or "[]"):
                    rel = os.path.relpath(d["filename"], root) if os.path.isabs(d["filename"]) else d["filename"]
                    loc = d.get("location") or {}
                    issues.append(_issue(rel, loc.get("row", 0), loc.get("column", 0), d.get("code"), d.get("message", "")))
            except (ValueError, KeyError):
                continue
        elif tool == "flake8":
            for line in r.stdout.splitlines():
                m = re.match(r"(.+?):(\d+):(\d+):(\w+):(.*)", line)
                if m:
                    issues.append(_issue(m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5)))
        else:
            for line in (r.stdout + r.stderr).splitlines():
                m = re.match(r"(.+?):(\d+):(?:(\d+):?)? (.*)", line)
                if m:
                    msg = m.group(4)
                    code = "F821" if "undefined name" in msg else "F401" if "imported but unused" in msg else "F841" if "never used" in msg else "F000"
                    issues.append(_issue(m.group(1), int(m.group(2)), int(m.group(3) or 0), code, msg))
        return tool, issues, shown.strip()
    return None


def _eslint(root: Path, targets: list[str], timeout: int) -> tuple[list[dict], str] | None:
    exe = root / "node_modules" / ".bin" / "eslint"
    if not exe.exists():
        return None
    r = _run(["node_modules/.bin/eslint", "-f", "json", *targets], root, timeout, "node")
    if r is None:
        return None
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    out = []
    for f in data:
        rel = os.path.relpath(f["filePath"], root) if os.path.isabs(f["filePath"]) else f["filePath"]
        for m in f.get("messages", []):
            code = m.get("ruleId") or "E999"
            iss = _issue(rel, m.get("line", 0), m.get("column", 0), code, m.get("message", ""), "error" if m.get("severity") == 2 else "warning")
            iss["blocking"] = bool(m.get("fatal")) or code == "no-undef" or code == "E999"
            out.append(iss)
    return out, "eslint -f json " + " ".join(targets[:3])


def _files(root: Path, paths: list[str] | None) -> list[str]:
    if paths:
        return [p for p in paths if (root / p).is_file()]
    found = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        found += [os.path.relpath(os.path.join(dp, f), root) for f in sorted(fs) if f.endswith(PY_EXT + JS_EXT + (".json",))]
    return found[:2000]


def run_linter(root: Path, paths: list[str] | None = None, timeout: int = 60) -> dict:
    UNAVAILABLE.clear()
    files = _files(root, paths)
    py = [f for f in files if f.endswith(PY_EXT)]
    js = [f for f in files if f.endswith(JS_EXT)]
    if not files:
        return {"tool": "none", "status": "clean", "issues": [], "counts": {"total": 0, "errors": 0, "warnings": 0, "blocking": 0},
                "summary": "no lintable files", "command": ""}
    issues = _builtin(root, files)
    tools, cmds = ["builtin syntax check"], []
    if py:
        res = _python(root, py if paths else ["."], timeout)
        if res:
            tool, found, cmd = res
            tools.append(tool); cmds.append(cmd)
            broken = {i["file"] for i in issues}
            issues += [i for i in found if not (i["code"] in ("E999", "invalid-syntax") and i["file"] in broken)]
    if js:
        res = _eslint(root, js, timeout)
        if res:
            tools.append("eslint"); cmds.append(res[1]); issues += res[0]
    issues = issues[:MAX_ISSUES]
    counts = {"total": len(issues), "errors": sum(i["severity"] == "error" for i in issues), "warnings": sum(i["severity"] == "warning" for i in issues),
              "blocking": sum(i["blocking"] for i in issues)}
    status = "issues" if issues else "clean"
    only_builtin = len(tools) == 1
    unavailable = list(UNAVAILABLE)
    UNAVAILABLE.clear()
    return {"tool": " + ".join(tools), "status": status, "issues": issues, "counts": counts, "command": "; ".join(cmds),
            "limited": only_builtin, **({"sandbox_problem": unavailable[0]} if unavailable else {}),
            "summary": (f"{counts['total']} finding(s), {counts['blocking']} blocking" if issues else "no findings")
                       + (" (no style linter installed: syntax check only)" if only_builtin and py else "")}


def _key(i: dict) -> tuple:
    return (i["file"], i["code"], re.sub(r"\d+", "N", i["message"]))


def new_issues(before: dict | None, after: dict) -> list[dict]:
    """Findings in `after` that `before` did not have (matched by file + rule + message, so line shifts do not count)."""
    pool: dict[tuple, int] = {}
    for i in (before or {}).get("issues", []):
        pool[_key(i)] = pool.get(_key(i), 0) + 1
    out = []
    for i in after.get("issues", []):
        k = _key(i)
        if pool.get(k, 0) > 0:
            pool[k] -= 1
        else:
            out.append(i)
    return out
