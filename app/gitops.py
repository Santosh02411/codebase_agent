"""Small git wrapper for the project copy: status, per-file diff sources, discard, commit.
Repositories without a .git folder (zip uploads, local copies) get a baseline commit so changes can be shown."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

from .utils import safe_path

IDENT = ["-c", "user.name=Codebase Agent", "-c", "user.email=agent@localhost", "-c", "core.quotepath=off"]
EXCLUDES = ["node_modules/", "venv/", ".venv/", "__pycache__/", "dist/", "build/", ".next/", ".pytest_cache/", "*.pyc"]


class GitError(ValueError):
    pass


def _git(root: Path, *args: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    try:
        env = {**os.environ, "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(["git", *IDENT, "-C", str(root), *args], capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise GitError("git is not installed on the server")
    except subprocess.TimeoutExpired:
        raise GitError("git timed out")
    if check and r.returncode != 0:
        raise GitError((r.stderr or r.stdout).strip()[:300] or "git failed")
    return r


def available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_repo(root: Path) -> bool:
    """Make sure `root` is its own git repository with a baseline commit. Returns False if git is unavailable."""
    if not available():
        return False
    if (root / ".git").exists():
        return True
    _git(root, "init", "-q")
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(EXCLUDES) + "\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", "baseline (as imported)")
    return True


def status(root: Path) -> dict:
    if not ensure_repo(root):
        return {"available": False, "branch": "", "files": []}
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip() or "HEAD"
    out = _git(root, "status", "--porcelain=v1", "-uall").stdout
    files = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ")[-1]
        path = path.strip('"')
        kind = "untracked" if code == "??" else "deleted" if "D" in code else "added" if "A" in code else "modified"
        files.append({"path": path, "status": kind, "code": code.strip() or "M"})
    return {"available": True, "branch": branch, "files": files}


def file_versions(root: Path, path: str) -> dict:
    """Original (HEAD) and current text of a file, for the diff viewer."""
    p = safe_path(root, path)
    ensure_repo(root)
    head = _git(root, "show", f"HEAD:{path}", check=False)
    original = head.stdout if head.returncode == 0 else ""
    try:
        modified = p.read_text(encoding="utf-8") if p.is_file() else ""
    except UnicodeDecodeError:
        raise GitError("binary file")
    return {"path": path, "original": original[:200_000], "modified": modified[:200_000],
            "is_new": head.returncode != 0, "is_deleted": not p.is_file()}


def discard(root: Path, path: str) -> None:
    p = safe_path(root, path)
    ensure_repo(root)
    tracked = _git(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode == 0
    if tracked:
        _git(root, "checkout", "HEAD", "--", path)
    elif p.is_file():
        p.unlink()


def commit(root: Path, message: str) -> dict:
    if not message.strip():
        raise GitError("commit message is required")
    ensure_repo(root)
    _git(root, "add", "-A")
    r = _git(root, "commit", "-q", "-m", message.strip(), check=False)
    if r.returncode != 0:
        raise GitError((r.stdout + r.stderr).strip()[:300] or "nothing to commit")
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"sha": sha}
