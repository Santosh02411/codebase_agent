"""Small git wrapper for the project copy: status, per-file diff sources, discard, commit.
Repositories without a .git folder (zip uploads, local copies) get a baseline commit so changes can be shown."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

from .utils import safe_path

IDENT = ["-c", "user.name=Codebase Agent", "-c", "user.email=agent@localhost", "-c", "core.quotepath=off"]
# A repository's own .git/config and .gitattributes are untrusted input (zip uploads, cloned repos): they can name programs git will run
# (fsmonitor, hooks, filters, textconv, ssh command, credential helpers) or rewrite URLs. These flags + sanitize_config() take that away.
HARDEN = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat", "-c", "core.editor=true", "-c", "core.sshCommand=false",
          "-c", "protocol.ext.allow=never", "-c", "credential.helper=", "-c", "commit.gpgsign=false", "-c", "gc.auto=0"]
HARD_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ASKPASS": "false", "GIT_ATTR_NOSYSTEM": "1"}
SAFE_KEYS = {"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase", "core.symlinks"}
_SAFE_PATTERNS = [__import__("re").compile(p) for p in (r"remote\.[^.\s]+\.url", r"remote\.[^.\s]+\.fetch", r"branch\.[^.\s]+\.(remote|merge)")]
EXCLUDES = ["node_modules/", "venv/", ".venv/", "__pycache__/", "dist/", "build/", ".next/", ".pytest_cache/", "*.pyc"]


class GitError(ValueError):
    pass


def net_env(auth_header: str | None) -> dict[str, str]:
    """Pass an HTTP auth header to git through the environment (never on the command line or in .git/config)."""
    if not auth_header:
        return {}
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": auth_header}


def _git(root: Path, *args: str, timeout: int = 60, check: bool = True, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        env = {k: v for k, v in os.environ.items() if k != "GIT_EXTERNAL_DIFF"}
        env.update({"GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0", **HARD_ENV, **(extra_env or {})})
        r = subprocess.run(["git", *IDENT, *HARDEN, "-C", str(root), *args], capture_output=True, text=True, timeout=timeout, env=env)
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


def sanitize_config(root: Path) -> None:
    """Rewrite an imported repository's .git/config keeping only inert settings (remote urls over https/ssh, branch tracking). Run once per project.
    Drops everything that can execute programs or redirect traffic: filters, hooks path, fsmonitor, aliases, credential helpers, url rewrites, includes."""
    git_dir = root / ".git"
    if git_dir.is_file():                       # a `gitdir: /somewhere/else` pointer: never follow it
        git_dir.unlink()
        return
    cfg, marker = git_dir / "config", git_dir / "agent-sanitized"
    if not cfg.is_file() or marker.exists():
        return
    try:
        r = subprocess.run(["git", "config", "--file", str(cfg), "--no-includes", "--list", "-z"], capture_output=True, text=True, timeout=20,
                           env={**os.environ, **HARD_ENV})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
    keep = []
    for item in r.stdout.split("\0"):
        key, _, val = item.partition("\n")
        if not key:
            continue
        ok = key in SAFE_KEYS or any(p.fullmatch(key) for p in _SAFE_PATTERNS)
        if ok and key.endswith(".url") and not (val.startswith("https://") or __import__("re").match(r"^[\w.-]+@[\w.-]+:[\w./-]+$", val)):
            ok = False
        if ok:
            keep.append((key, val))
    tmp = git_dir / "config.sanitized"
    tmp.write_text("")
    for key, val in keep:
        subprocess.run(["git", "config", "--file", str(tmp), "--add", key, val], capture_output=True, timeout=20, env={**os.environ, **HARD_ENV})
    tmp.replace(cfg)
    for hook in (git_dir / "hooks").glob("*") if (git_dir / "hooks").is_dir() else []:
        if hook.is_file() and not hook.name.endswith(".sample"):
            hook.unlink()
    marker.write_text("1")


def ensure_repo(root: Path) -> bool:
    """Make sure `root` is its own git repository with a baseline commit. Returns False if git is unavailable."""
    if not available():
        return False
    sanitize_config(root)
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


def create_branch(root: Path, name: str, from_ref: str | None = None, checkout: bool = True) -> dict:
    """A new LOCAL branch (nothing leaves this machine). Fails if the name is taken or invalid."""
    ensure_repo(root)
    if not name or name.startswith("-") or _git(root, "check-ref-format", "--branch", name, check=False).returncode != 0:
        raise GitError(f"'{name}' is not a valid branch name")
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0:
        raise GitError(f"a branch named '{name}' already exists")
    start = _check_ref(from_ref) if from_ref else "HEAD"
    r = _git(root, "branch", name, start, check=False)
    if r.returncode != 0:
        raise GitError((r.stderr or "could not create the branch").strip()[:200])
    if checkout:
        c = _git(root, "checkout", "-q", name, check=False)
        if c.returncode != 0:
            raise GitError((c.stderr or "could not switch to the new branch").strip()[:200])
    return {"branch": name, "from": start, "checked_out": checkout, "commit": _git(root, "rev-parse", "--short", name).stdout.strip()}


def commit(root: Path, message: str, paths: list[str] | None = None) -> dict:
    """Commit `paths` (default: every changed file). Files that look like secrets (.env, keys) are never staged; they are reported in `skipped`."""
    if not message.strip():
        raise GitError("commit message is required")
    ensure_repo(root)
    from .agent.extras import is_secret_file
    changed = [f["path"] for f in status(root)["files"]]
    wanted = [p for p in (paths or changed) if p in changed]
    skipped = [p for p in wanted if is_secret_file(p)]
    stage = [p for p in wanted if p not in skipped]
    if not stage:
        raise GitError("nothing to commit" + (f" (skipped secret-looking files: {', '.join(skipped)})" if skipped else ""))
    _git(root, "add", "-A", "--", *stage)
    r = _git(root, "commit", "-q", "-m", message.strip(), "--", *stage, check=False)
    if r.returncode != 0:
        raise GitError((r.stdout + r.stderr).strip()[:300] or "nothing to commit")
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"sha": sha, "files": stage, "skipped": skipped}


# ---- branches, commits, checkout ---------------------------------------------------------------------
_REF = __import__("re").compile(r"^[A-Za-z0-9_][A-Za-z0-9_./~^@{}\-]*$")


def _check_ref(ref: str) -> str:
    if not ref or not _REF.match(ref) or ".." in ref or ref.endswith(".lock"):
        raise GitError(f"invalid branch or commit: {ref!r}")
    return ref


def head_info(root: Path) -> dict:
    if not available() or not (root / ".git").exists():
        return {"branch": "", "commit": "", "detached": False}
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    sha = _git(root, "rev-parse", "--short", "HEAD", check=False).stdout.strip()
    return {"branch": "" if branch == "HEAD" else branch, "commit": sha, "detached": branch == "HEAD"}


def is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository", check=False).stdout.strip() == "true"


def branches(root: Path) -> dict:
    """Local and remote branches (remote ones can be checked out; they become local tracking branches)."""
    ensure_repo(root)
    fmt = "%(refname)|%(objectname:short)|%(committerdate:iso8601-strict)|%(subject)"
    out = _git(root, "for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes").stdout
    head = head_info(root)
    local: dict[str, dict] = {}
    remote: dict[str, dict] = {}
    for line in out.splitlines():
        ref, sha, date, subject = (line.split("|", 3) + ["", "", ""])[:4]
        if ref.startswith("refs/heads/"):
            name = ref[len("refs/heads/"):]
            local[name] = {"name": name, "sha": sha, "date": date, "subject": subject, "current": name == head["branch"], "remote": False}
        elif ref.startswith("refs/remotes/"):
            full = ref[len("refs/remotes/"):]
            remote_name, _, name = full.partition("/")
            if name and name != "HEAD":
                remote[name] = {"name": name, "sha": sha, "date": date, "subject": subject, "current": False, "remote": True, "origin": remote_name}
    items = list(local.values()) + [r for n, r in remote.items() if n not in local]
    default = ""
    r = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if r.returncode == 0:
        default = r.stdout.strip().split("/", 1)[-1]
    if not default:
        default = next((n for n in ("main", "master", "develop") if any(i["name"] == n for i in items)), "")
    return {"current": head["branch"], "commit": head["commit"], "detached": head["detached"], "default": default,
            "branches": sorted(items, key=lambda b: (not b["current"], b["name"] != default, b["name"])), "shallow": is_shallow(root)}


def commits(root: Path, ref: str | None = None, limit: int = 30, skip: int = 0) -> list[dict]:
    ensure_repo(root)
    args = ["log", f"--max-count={min(max(limit, 1), 200)}", f"--skip={max(skip, 0)}", "--date=iso-strict",
            "--format=%H%x1f%h%x1f%an%x1f%ad%x1f%s"]
    if ref:
        args.append(_check_ref(ref))
    r = _git(root, *args, check=False)
    if r.returncode != 0:
        raise GitError((r.stderr or "git log failed").strip()[:300])
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            out.append({"sha": parts[0], "short": parts[1], "author": parts[2], "date": parts[3], "subject": parts[4]})
    return out


def checkout(root: Path, ref: str, force: bool = False) -> dict:
    """Switch the working copy to a branch (remote branches get a local tracking branch) or a commit (detached)."""
    _check_ref(ref)
    ensure_repo(root)
    dirty = status(root)["files"]
    if dirty and not force:
        raise GitError(f"{len(dirty)} file(s) have uncommitted changes. Commit or discard them first, or switch with discard enabled.")
    if force and dirty:
        _git(root, "reset", "--hard", "-q")
        _git(root, "clean", "-fdq")
    if _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{ref}", check=False).returncode == 0:
        _git(root, "checkout", "-q", ref)
    elif _git(root, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{ref}", check=False).returncode == 0:
        _git(root, "checkout", "-q", "-B", ref, f"origin/{ref}")
    else:
        sha = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if sha.returncode != 0:
            raise GitError(f"unknown branch or commit: {ref}")
        _git(root, "checkout", "-q", "--detach", sha.stdout.strip())
    return head_info(root)


def fetch(root: Path, deepen: int = 50, auth_header: str | None = None) -> dict:
    """Download more history (shallow clones) or new remote branches."""
    ensure_repo(root)
    env = net_env(auth_header)
    if not (root / ".git").exists() or _git(root, "remote", check=False).stdout.strip() == "":
        raise GitError("this project has no remote to fetch from (it was uploaded or copied)")
    args = ["fetch", "--prune", "-q"]
    if is_shallow(root):
        args.append(f"--deepen={min(max(deepen, 1), 1000)}")
    r = _git(root, *args, "origin", check=False, timeout=300, extra_env=env)
    if r.returncode != 0:
        raise GitError((r.stderr or "git fetch failed").strip()[:300])
    return {"shallow": is_shallow(root)}


def ls_remote_heads(url: str, auth_header: str | None = None) -> dict:
    """Branch names of a remote repository, without cloning it."""
    try:
        r = subprocess.run(["git", "ls-remote", "--symref", url, "HEAD", "refs/heads/*"], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **net_env(auth_header)})
    except FileNotFoundError:
        raise GitError("git is not installed on the server")
    except subprocess.TimeoutExpired:
        raise GitError("timed out contacting the repository host")
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()[-1:] or ["could not reach repository"]
        raise GitError(msg[0][:200])
    names, default = [], ""
    for line in r.stdout.splitlines():
        if line.startswith("ref: refs/heads/"):
            default = line.split()[1][len("refs/heads/"):]
        elif "\trefs/heads/" in line:
            names.append(line.split("\trefs/heads/", 1)[1])
    return {"branches": sorted(names, key=lambda n: (n != default, n)), "default": default or (names[0] if names else "")}
