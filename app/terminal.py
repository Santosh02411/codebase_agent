"""A deliberately restricted terminal: read-only repo commands plus pytest in the sandbox copy.
There is no shell, no pipes and no arbitrary executables, so a question box can't be turned into remote code execution."""
from __future__ import annotations
import re
import shlex
import sys
from pathlib import Path

from . import gitops, sandbox, textsearch
from .utils import safe_path

HELP = """Available commands (no shell, no pipes):
  ls [path]                 list a folder
  tree                      list every indexed file
  cat <file>                print a file
  grep [-i] [-E] <text>     search the whole repository
  git status|diff|log|branch|show [flags] [paths]
  pytest [-q] [-v] [-x] [-k expr] [paths]   run tests in a throwaway copy
  help                      this message"""

GIT_SUB = {"status", "diff", "log", "branch", "show"}
GIT_FLAGS = {"--stat", "--oneline", "--name-only", "--name-status", "--cached", "--staged", "--graph", "--decorate",
             "--short", "-s", "-a", "-v", "-vv", "-n", "--no-color"}
REF = re.compile(r"^[A-Za-z0-9_.~^/:@{}-]+$")


def _ok(output: str, code: int = 0) -> dict:
    return {"output": output, "exit_code": code}


def _bad_path(arg: str) -> bool:
    return arg.startswith("/") or ".." in Path(arg).parts or arg.startswith("-")


def _git(root: Path, args: list[str]) -> dict:
    if not args or args[0] not in GIT_SUB:
        return _ok("git: only status, diff, log, branch and show are allowed here", 2)
    clean = [args[0]]
    seen_dd = False
    for a in args[1:]:
        if a == "--":
            seen_dd = True
        elif seen_dd or not a.startswith("-"):
            if ".." in a and not REF.match(a.replace("..", "")):
                return _ok(f"git: argument not allowed: {a}", 2)
            if _bad_path(a) and not REF.match(a):
                return _ok(f"git: argument not allowed: {a}", 2)
        elif a not in GIT_FLAGS and not re.fullmatch(r"-\d+", a):
            return _ok(f"git: flag not allowed: {a}", 2)
        clean.append(a)
    gitops.ensure_repo(root)
    r = gitops._git(root, "--no-pager", *clean, check=False)
    return _ok((r.stdout + r.stderr)[-20_000:], r.returncode)


def _pytest(root: Path, args: list[str], timeout: int) -> dict:
    clean, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-q", "-v", "-x", "-vv", "-s", "--tb=short", "--tb=line", "--tb=no"):
            clean.append(a)
        elif a == "-k" and i + 1 < len(args):
            clean += [a, args[i + 1]]
            i += 1
        elif not a.startswith("-") and not _bad_path(a.split("::")[0]):
            clean.append(a)
        else:
            return _ok(f"pytest: argument not allowed: {a}", 2)
        i += 1
    work = sandbox.copy_repo(root)
    try:
        res = sandbox.run_tests(work, timeout, command=[sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *(clean or ["-q"])])
    finally:
        sandbox.cleanup(work)
    return {"output": res["output"] or res["summary"], "exit_code": 0 if res["passed"] else 1, "tests": res}


def execute(root: Path, index, command: str, timeout: int = 120) -> dict:
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return _ok(f"parse error: {e}", 2)
    if not argv:
        return _ok("")
    cmd, args = argv[0], argv[1:]
    if cmd == "help":
        return _ok(HELP)
    if cmd == "tree":
        return _ok("\n".join(index.tree))
    if cmd == "ls":
        target = args[0] if args else "."
        try:
            p = safe_path(root, target)
        except ValueError as e:
            return _ok(str(e), 1)
        if not p.is_dir():
            return _ok(f"ls: not a directory: {target}", 1)
        names = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir() if x.name != ".git")
        return _ok("\n".join(names))
    if cmd == "cat":
        if len(args) != 1:
            return _ok("usage: cat <file>", 2)
        try:
            text = safe_path(root, args[0]).read_text(encoding="utf-8")
        except (ValueError, OSError, UnicodeDecodeError):
            return _ok(f"cat: can't read {args[0]}", 1)
        return _ok(text[:100_000])
    if cmd == "grep":
        flags = {a for a in args if a in ("-i", "-E")}
        rest = [a for a in args if a not in flags]
        if not rest:
            return _ok("usage: grep [-i] [-E] <text>", 2)
        try:
            res = textsearch.grep(root, index.tree, rest[0], regex="-E" in flags, case="-i" not in flags, limit=200)
        except ValueError as e:
            return _ok(str(e), 2)
        lines = [f"{m['file']}:{m['line']}: {m['text']}" for m in res["matches"]]
        if res["truncated"]:
            lines.append("... (truncated)")
        return _ok("\n".join(lines), 0 if lines else 1)
    if cmd == "git":
        return _git(root, args)
    if cmd in ("pytest", "tests"):
        return _pytest(root, args, timeout)
    return _ok(f"{cmd}: command not found (type 'help')", 127)
