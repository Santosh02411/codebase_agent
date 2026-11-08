"""Read-only git intelligence: history, authorship, previous versions, comparisons. Used by the AI's tools and the API.
Everything goes through gitops._git (hardened against untrusted repository config), takes validated refs and paths, and bounds its output."""
from __future__ import annotations
import re
from pathlib import Path

from . import gitops
from .gitops import GitError, _check_ref, _git
from .utils import safe_path

MAX_TEXT = 120_000
SEP = "\x1f"


def _repo(root: Path) -> None:
    if not gitops.ensure_repo(root):
        raise GitError("git is not available on this server")


def _ref(ref: str | None) -> str:
    return _check_ref(ref) if ref else "HEAD"


def _path(root: Path, path: str | None) -> list[str]:
    if not path:
        return []
    safe_path(root, path)
    return ["--", path]


def _range(base: str, head: str | None, three_dot: bool = True) -> str:
    """`base...head` (changes on head since it diverged from base: what a PR shows) or `base..head`."""
    b, h = _ref(base), _ref(head)
    return f"{b}{'...' if three_dot else '..'}{h}"


def commit_meta(root: Path, rev: str) -> dict:
    _repo(root)
    r = _git(root, "show", "-s", "--date=iso-strict", f"--format=%H{SEP}%an{SEP}%ae{SEP}%ad{SEP}%cn{SEP}%P{SEP}%s{SEP}%b", _ref(rev), check=False)
    if r.returncode != 0:
        raise GitError(f"unknown commit: {rev}")
    p = (r.stdout.rstrip("\n").split(SEP) + [""] * 8)[:8]
    return {"sha": p[0], "short": p[0][:8], "author": p[1], "email": p[2], "date": p[3], "committer": p[4], "parents": p[5].split(), "subject": p[6], "body": p[7].strip()}


def numstat(root: Path, range_or_rev: list[str], path: str | None = None) -> list[dict]:
    r = _git(root, *range_or_rev, "--numstat", "--no-ext-diff", "--no-textconv", "-M", "--format=", *_path(root, path), check=False)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            a, d, name = parts
            out.append({"path": name.split(" => ")[-1].strip("{} ") if " => " in name else name, "additions": int(a) if a.isdigit() else 0, "deletions": int(d) if d.isdigit() else 0,
                        "binary": a == "-"})
    return out


def show(root: Path, rev: str = "HEAD", path: str | None = None, diff: bool = True, max_chars: int = 20_000) -> dict:
    """One commit: metadata, files touched with line counts, and (optionally) its diff."""
    meta = commit_meta(root, rev)
    files = numstat(root, ["show", meta["sha"]], path)
    text = ""
    if diff:
        r = _git(root, "show", "--no-color", "--no-ext-diff", "--no-textconv", "--format=", meta["sha"], *_path(root, path), check=False)
        text = r.stdout[:max_chars] + (f"\n... (diff truncated, {len(r.stdout) - max_chars} more characters)" if len(r.stdout) > max_chars else "")
    return {**meta, "files": files, "diff": text}


def log(root: Path, *, path: str | None = None, author: str | None = None, since: str | None = None, grep: str | None = None, ref: str | None = None,
        limit: int = 20) -> list[dict]:
    _repo(root)
    args = ["log", f"--max-count={max(1, min(limit, 100))}", "--date=iso-strict", f"--format=%H{SEP}%an{SEP}%ad{SEP}%s"]
    if author:
        args.append(f"--author={author[:80]}")
    if since:
        if not re.fullmatch(r"[\w .:/-]{1,40}", since):
            raise GitError("invalid date")
        args.append(f"--since={since}")
    if grep:
        args.append(f"--grep={grep[:80]}")
    args.append(_ref(ref))
    r = _git(root, *args, *_path(root, path), check=False)
    if r.returncode != 0:
        raise GitError((r.stderr or "git log failed").strip()[:200])
    out = []
    for line in r.stdout.splitlines():
        p = line.split(SEP)
        if len(p) == 4:
            out.append({"sha": p[0], "short": p[0][:8], "author": p[1], "date": p[2], "subject": p[3]})
    return out


def blame(root: Path, path: str, start: int | None = None, end: int | None = None, ref: str | None = None) -> dict:
    """Who last changed each line (and in which commit), plus a per-author summary."""
    _repo(root)
    safe_path(root, path)
    args = ["blame", "--porcelain", "-w"]
    if start:
        args += ["-L", f"{max(1, int(start))},{max(int(end or start), int(start))}"]
    if ref:
        args.append(_ref(ref))
    r = _git(root, *args, "--", path, check=False)
    if r.returncode != 0:
        raise GitError((r.stderr or "git blame failed").strip()[:200])
    commits: dict[str, dict] = {}
    lines, cur = [], None
    for raw in r.stdout.splitlines():
        if raw.startswith("\t"):
            if cur:
                c = commits[cur["sha"]]
                lines.append({"line": cur["line"], "sha": cur["sha"][:8], "author": c.get("author", ""), "date": c.get("date", ""), "summary": c.get("summary", ""), "text": raw[1:]})
            continue
        m = re.match(r"^([0-9a-f]{40}) (\d+) (\d+)", raw)
        if m:
            cur = {"sha": m.group(1), "line": int(m.group(3))}
            commits.setdefault(cur["sha"], {})
        elif cur and raw.startswith("author "):
            commits[cur["sha"]]["author"] = raw[7:]
        elif cur and raw.startswith("author-time "):
            import datetime
            commits[cur["sha"]]["date"] = datetime.datetime.fromtimestamp(int(raw[12:]), datetime.timezone.utc).date().isoformat()
        elif cur and raw.startswith("summary "):
            commits[cur["sha"]]["summary"] = raw[8:]
    by_author: dict[str, int] = {}
    for l in lines:
        by_author[l["author"]] = by_author.get(l["author"], 0) + 1
    return {"path": path, "lines": lines[:400], "authors": sorted(({"author": a, "lines": n} for a, n in by_author.items()), key=lambda x: -x["lines"])}


def file_at(root: Path, path: str, ref: str) -> dict:
    """A previous version of a file."""
    _repo(root)
    safe_path(root, path)
    r = _git(root, "show", f"{_ref(ref)}:{path}", check=False)
    if r.returncode != 0:
        raise GitError(f"{path} does not exist at {ref}")
    return {"path": path, "ref": ref, "text": r.stdout[:MAX_TEXT], "truncated": len(r.stdout) > MAX_TEXT}


def changed_files(root: Path, base: str, head: str | None = None, three_dot: bool = True) -> list[dict]:
    _repo(root)
    rng = _range(base, head, three_dot)
    st = _git(root, "diff", "--name-status", "-M", "--no-ext-diff", rng, check=False)
    if st.returncode != 0:
        raise GitError((st.stderr or "cannot compare").strip()[:200])
    stats = {f["path"]: f for f in numstat(root, ["diff", rng])}
    out = []
    for line in st.stdout.splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        path = parts[-1]
        out.append({"path": path, "status": {"A": "added", "D": "deleted", "M": "modified", "R": "renamed", "C": "copied"}.get(code, "modified"), "old_path": parts[1] if code == "R" else None,
                    "additions": stats.get(path, {}).get("additions", 0), "deletions": stats.get(path, {}).get("deletions", 0)})
    return out


def diff(root: Path, base: str, head: str | None = None, path: str | None = None, three_dot: bool = True, max_chars: int = 60_000) -> str:
    _repo(root)
    r = _git(root, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", _range(base, head, three_dot), *_path(root, path), check=False)
    if r.returncode != 0:
        raise GitError((r.stderr or "cannot diff").strip()[:200])
    return r.stdout[:max_chars] + (f"\n... (diff truncated, {len(r.stdout) - max_chars} more characters)" if len(r.stdout) > max_chars else "")


def authors(root: Path, path: str | None = None, since: str | None = None, limit: int = 10) -> list[dict]:
    """Contributors ranked by commits (for a file, or the whole repository): who knows this code."""
    _repo(root)
    args = ["shortlog", "-sne", "HEAD"]
    if since:
        if not re.fullmatch(r"[\w .:/-]{1,40}", since):
            raise GitError("invalid date")
        args.insert(1, f"--since={since}")
    r = _git(root, *args, *_path(root, path), check=False)
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*?)\s+<(.*)>", line)
        if m:
            out.append({"commits": int(m.group(1)), "author": m.group(2), "email": m.group(3)})
    return out[:max(1, min(limit, 50))]


def merge_base(root: Path, a: str, b: str) -> str:
    _repo(root)
    r = _git(root, "merge-base", _ref(a), _ref(b), check=False)
    return r.stdout.strip()


def compare(root: Path, base: str, head: str) -> dict:
    """How `head` relates to `base`: commits ahead / behind and what it changes (the shape of a pull request)."""
    _repo(root)
    ahead = _git(root, "rev-list", "--count", f"{_ref(base)}..{_ref(head)}", check=False).stdout.strip()
    behind = _git(root, "rev-list", "--count", f"{_ref(head)}..{_ref(base)}", check=False).stdout.strip()
    r = _git(root, "log", "--date=iso-strict", f"--format=%H{SEP}%an{SEP}%ad{SEP}%s", "--max-count=50", f"{_ref(base)}..{_ref(head)}", check=False)
    commits = [dict(zip(("sha", "author", "date", "subject"), l.split(SEP))) for l in r.stdout.splitlines() if l.count(SEP) == 3]
    return {"base": base, "head": head, "ahead": int(ahead or 0), "behind": int(behind or 0), "commits": commits, "files": changed_files(root, base, head)}


def summary(root: Path) -> dict:
    """Orientation for the AI and the UI: branches, remotes, recent commits, top contributors."""
    _repo(root)
    b = gitops.branches(root)
    remotes = []
    for line in _git(root, "remote", "-v", check=False).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "(fetch)":
            remotes.append({"name": parts[0], "url": re.sub(r"//[^/@]+@", "//", parts[1])})       # never show credentials embedded in a URL
    return {"current": b["current"], "commit": b["commit"], "default": b["default"], "detached": b["detached"], "branches": [x["name"] for x in b["branches"]][:30],
            "remotes": remotes, "recent": log(root, limit=8), "contributors": authors(root, limit=5), "shallow": b["shallow"]}
