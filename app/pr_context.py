"""Everything the agent needs to understand a pull request or an issue: the metadata and diff from GitHub, the commits and earlier comments,
which lines each file's patch actually adds, and (best effort) the PR's head files fetched into the local clone so analyzers can run on them."""
from __future__ import annotations
import re
from pathlib import Path

from . import git_intel, gitops, providers, sandbox_exec
from .github_api import GitHub

MAX_DIFF = 60_000
MAX_FILE_PATCH = 6_000
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(patch: str) -> set[int]:
    """Line numbers (in the NEW file) that a unified-diff patch adds or changes. Review comments can only attach to these (or to context lines)."""
    out: set[int] = set()
    n = 0
    for line in patch.splitlines():
        m = _HUNK.match(line)
        if m:
            n = int(m.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            out.add(n); n += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif line.startswith("\\"):
            continue
        else:
            n += 1
    return out


def context_lines(patch: str) -> set[int]:
    """New-file line numbers visible in the diff (added + unchanged context): the valid anchors for inline review comments."""
    out: set[int] = set()
    n = 0
    for line in patch.splitlines():
        m = _HUNK.match(line)
        if m:
            n = int(m.group(1))
            continue
        if line.startswith("-") and not line.startswith("---") or line.startswith("\\"):
            continue
        out.add(n); n += 1
    return out


def split_diff(diff: str) -> dict[str, str]:
    """A multi-file unified diff → {path: patch text of that file}."""
    files: dict[str, str] = {}
    cur, buf = None, []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur:
                files[cur] = "".join(buf)
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line.strip())
            cur, buf = (m.group(2) if m else None), []
        elif cur:
            buf.append(line)
    if cur:
        files[cur] = "".join(buf)
    return files


def fetch_head(root: Path, number: int, token: str, settings) -> bool:
    """Fetch the PR's head commit into a private ref (refs/agent/pr/N) so its files can be read and analysed. Best effort: needs network + the origin remote."""
    try:
        header = providers.auth_header("github", settings, token)
        r = gitops._git(root, "fetch", "--no-tags", "--depth=50", "origin", f"pull/{int(number)}/head:refs/agent/pr/{int(number)}", check=False, timeout=180, extra_env=gitops.net_env(header))
        return r.returncode == 0
    except (gitops.GitError, OSError):
        return False


def head_files(root: Path, number: int, paths: list[str], max_files: int = 40) -> dict[str, str]:
    """Contents of changed files at the PR head (from the fetched ref), capped."""
    out: dict[str, str] = {}
    for p in paths[:max_files]:
        try:
            out[p] = git_intel.file_at(root, p, f"refs/agent/pr/{int(number)}")["text"]
        except gitops.GitError:
            continue
    return out


def build_pr(gh: GitHub, owner: str, repo: str, number: int, root: Path | None = None, token: str = "", settings=None) -> dict:
    pr = gh.pull(owner, repo, number)
    files = gh.pull_files(owner, repo, number)
    commits = gh.pull_commits(owner, repo, number)
    feedback = gh.pull_feedback(owner, repo, number)
    patches = {f["path"]: (f["patch"] or "") for f in files}
    diff = ""
    for f in files:
        patch = patches[f["path"]]
        head = f"diff --git a/{f.get('old_path') or f['path']} b/{f['path']}\n--- a/{f.get('old_path') or f['path']}\n+++ b/{f['path']}\n"
        diff += head + (patch[:MAX_FILE_PATCH] + ("\n... (patch truncated)\n" if len(patch) > MAX_FILE_PATCH else "\n") if patch else "(binary or too large to show)\n")
        if len(diff) > MAX_DIFF:
            diff = diff[:MAX_DIFF] + "\n... (diff truncated)\n"
            break
    local = bool(root and token and fetch_head(root, number, token, settings))
    reviewers: list[dict] = []
    if root:
        seen: dict[str, int] = {}
        for f in files[:12]:
            try:
                for a in git_intel.authors(root, f["path"], limit=3):
                    if a["author"].lower() != pr["author"].lower():
                        seen[a["author"]] = seen.get(a["author"], 0) + a["commits"]
            except gitops.GitError:
                pass
        reviewers = [{"author": a, "commits": n} for a, n in sorted(seen.items(), key=lambda x: -x[1])[:3]]
    return {"owner": owner, "repo": repo, "pr": pr, "files": files, "commits": commits, "feedback": feedback, "diff": diff, "head_fetched": local,
            "valid_lines": {p: sorted(context_lines(t)) for p, t in patches.items() if t}, "added_lines": {p: sorted(added_lines(t)) for p, t in patches.items() if t},
            "suggested_reviewers": reviewers, "truncated": len(files) >= 300}


def render_pr(c: dict, max_chars: int = 14_000) -> str:
    pr = c["pr"]
    lines = [f"Pull request #{pr['number']}: {pr['title']}  (by {pr['author']}, {pr['head']} → {pr['base']}{', DRAFT' if pr['draft'] else ''})",
             f"{len(c['files'])} file(s) changed, +{sum(f['additions'] for f in c['files'])}/-{sum(f['deletions'] for f in c['files'])}; {len(c['commits'])} commit(s)",
             f"Description:\n{(pr['body'] or '(none)')[:1500]}", "Commits:\n" + "\n".join(f"- {x['sha'][:8]} {x['message'].splitlines()[0][:100]}" for x in c["commits"][:15]),
             "Files:\n" + "\n".join(f"- {f['status']:>9} {f['path']} (+{f['additions']}/-{f['deletions']})" for f in c["files"][:60])]
    if c["feedback"]:
        lines.append("Existing discussion (do not repeat it):\n" + "\n".join(f"- {x['author']}{' on ' + x['path'] + ':' + str(x['line']) if x['path'] else ''}: {x['body'][:200]}" for x in c["feedback"][:12]))
    text = "\n".join(lines) + f"\n\nDiff:\n{c['diff']}"
    return text[:max_chars] + ("\n... (truncated)" if len(text) > max_chars else "")


def render_issue(issue: dict) -> str:
    comments = "\n".join(f"- {c['author']}: {c['body'][:600]}" for c in issue["comments"][:10])
    return (f"GitHub issue #{issue['number']}: {issue['title']}  (by {issue['author']}; labels: {', '.join(issue['labels']) or 'none'})\n\n{issue['body'][:5000]}"
            + (f"\n\nDiscussion:\n{comments}" if comments else ""))
