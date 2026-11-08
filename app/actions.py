"""Human approval for destructive or externally visible operations.

Pushing, opening a pull request and posting a review change something OUTSIDE this machine and cannot be taken back cleanly; a force push
or a hard reset destroys work. So each of them is a two-step ticket:

  1. PROPOSE  (the AI, an endpoint or the UI): the server computes exactly what would happen (remote, branch, the commits, the files,
              the full review text) and stores it as a pending action. Nothing external happens.
  2. APPROVE  (a person, in the UI): only `POST /actions/{id}/approve {"approved": true}` executes it, with a check that the world still
              matches what was shown (branch tip, PR head). Risky variants (force push, pushing the default branch) also need the branch name typed.

No agent tool can approve or execute an action: the tool registry has none (tests assert it). Credentials are used only here, at execution
time, and never appear in a preview, a record or a log."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import git_intel, gitops, providers
from .github_api import GitHub, GitHubError, parse_remote

EXPIRY_SECONDS = 1800
_ID = re.compile(r"^[a-f0-9]{8,32}$")
EXTERNAL = {"push", "force_push", "create_pr", "post_review"}


class ActionError(ValueError):
    """The action cannot be proposed or executed as asked."""


class ApprovalRequired(ActionError):
    pass


class ActionStale(ActionError):
    """What the user was shown no longer matches reality; propose again."""


class ActionStore:
    def __init__(self, base: Path) -> None:
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, aid: str) -> Path:
        if not _ID.match(aid or ""):
            raise KeyError(aid)
        return self.base / f"{aid}.json"

    def get(self, aid: str) -> dict:
        p = self._path(aid)
        if not p.is_file():
            raise KeyError(aid)
        rec = json.loads(p.read_text())
        if rec["status"] == "pending" and time.time() - rec["created"] > EXPIRY_SECONDS:
            rec["status"] = "expired"
        return rec

    def save(self, rec: dict) -> dict:
        rec["updated"] = time.time()
        with self._lock:
            tmp = self._path(rec["id"]).with_suffix(".tmp")
            tmp.write_text(json.dumps(rec))
            tmp.replace(self._path(rec["id"]))
        return rec

    def create(self, repo_id: str, kind: str, params: dict, preview: dict, state: dict | None = None) -> dict:
        rec = {"id": uuid.uuid4().hex[:12], "repo_id": repo_id, "kind": kind, "params": params, "preview": preview, "state": state or {}, "status": "pending",
               "external": kind in EXTERNAL, "destructive": bool(preview.get("destructive")), "created": time.time(), "history": [{"ts": time.time(), "event": "proposed"}], "result": None}
        return self.save(rec)

    def list(self, repo_id: str | None = None, status: str | None = None) -> list[dict]:
        out = []
        for f in sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]:
            try:
                rec = self.get(f.stem)
            except (KeyError, ValueError, OSError):
                continue
            if (repo_id is None or rec["repo_id"] == repo_id) and (status is None or rec["status"] == status):
                out.append(public(rec))
        return out


def public(rec: dict) -> dict:
    return {k: rec[k] for k in ("id", "repo_id", "kind", "preview", "status", "external", "destructive", "created", "history", "result")}


def _clean_url(url: str) -> str:
    return re.sub(r"//[^/@\s]+@", "//", url or "")


def remote_url(root: Path, remote: str = "origin") -> str:
    r = gitops._git(root, "remote", "get-url", remote, check=False)
    if r.returncode != 0:
        raise ActionError(f"this project has no remote named {remote!r}: it was uploaded or copied, so there is nowhere to push to")
    return r.stdout.strip()


def validate_remote(url: str, source: str, owner_repo_only: bool = True) -> tuple[str, str]:
    """The push target must be the GitHub repository this project was added from; a rewritten remote never receives the user's token."""
    o, r = parse_remote(url)
    if owner_repo_only and source:
        so, sr = parse_remote(source)
        if (o.lower(), r.lower()) != (so.lower(), sr.lower()):
            raise ActionError(f"the remote points at {o}/{r} but this project is {so}/{sr}; refusing to send credentials there")
    return o, r


# ---- proposals -------------------------------------------------------------------------------------------------------------------------
def propose_push(store: ActionStore, repo_id: str, root: Path, source: str, *, branch: str | None = None, remote: str = "origin", force: bool = False,
                 remote_check=None) -> dict:
    remote_check = remote_check or validate_remote
    gitops.ensure_repo(root)
    info = gitops.branches(root)
    branch = gitops._check_ref(branch or info["current"] or "")
    if not branch or branch not in [b["name"] for b in info["branches"] if not b["remote"]]:
        raise ActionError(f"there is no local branch named {branch!r}")
    url = remote_url(root, remote)
    owner, repo = remote_check(url, source)
    head = gitops._git(root, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    tracking = gitops._git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False)
    default = info["default"]
    base_ref = f"{remote}/{branch}" if tracking.returncode == 0 else (f"{remote}/{default}" if default else "")
    commits, files, behind = [], [], 0
    if base_ref and gitops._git(root, "rev-parse", "--verify", "--quiet", base_ref, check=False).returncode == 0:
        comp = git_intel.compare(root, base_ref, branch)
        commits, files, behind = comp["commits"], comp["files"], comp["behind"] if tracking.returncode == 0 else 0
    warnings = []
    is_default = branch == default
    if not commits:
        warnings.append("There are no new commits to push.")
    if tracking.returncode != 0:
        warnings.append(f"This creates the branch '{branch}' on GitHub.")
    if behind and not force:
        warnings.append(f"GitHub has {behind} commit(s) this branch does not; the push will be rejected unless you integrate them first.")
    if is_default:
        warnings.append(f"'{branch}' is the repository's default branch: this publishes directly to it, bypassing a pull request.")
    if force:
        warnings.append("FORCE PUSH: this overwrites the remote branch's history and can destroy other people's commits.")
    kind = "force_push" if force else "push"
    preview = {"title": f"{'Force-push' if force else 'Push'} '{branch}' to {owner}/{repo}", "destructive": force, "remote": remote, "url": _clean_url(url), "branch": branch,
               "creates_remote_branch": tracking.returncode != 0, "commits": commits[:30], "commit_count": len(commits), "files": files[:60], "warnings": warnings,
               "confirm_text": branch if (force or is_default) else None, "default_branch": is_default}
    return store.create(repo_id, kind, {"branch": branch, "remote": remote, "force": force}, preview, {"head": head, "source": source})


def propose_pr(store: ActionStore, repo_id: str, gh: GitHub, owner: str, repo: str, *, title: str, body: str, base: str, head: str, draft: bool = False) -> dict:
    if not title.strip() or len(title) > 256:
        raise ActionError("a pull request title (up to 256 characters) is required")
    gitops._check_ref(base), gitops._check_ref(head)
    if base == head:
        raise ActionError("the head and base branches are the same")
    warnings = []
    try:
        if not gh.branch_exists(owner, repo, head):
            warnings.append(f"The branch '{head}' is not on GitHub yet: push it first (approving this will fail until you do).")
        if not gh.branch_exists(owner, repo, base):
            raise ActionError(f"the base branch '{base}' does not exist on GitHub")
    except GitHubError as e:
        raise ActionError(str(e))
    preview = {"title": f"Open a pull request: {title.strip()}", "destructive": False, "repo": f"{owner}/{repo}", "pr_title": title.strip(), "body": body, "base": base, "head": head, "draft": draft,
               "warnings": warnings, "confirm_text": None}
    return store.create(repo_id, "create_pr", {"title": title.strip(), "body": body, "base": base, "head": head, "draft": draft}, preview, {"owner": owner, "repo": repo})


REVIEW_EVENTS = ("COMMENT", "APPROVE", "REQUEST_CHANGES")


def propose_review(store: ActionStore, repo_id: str, owner: str, repo: str, pr: dict, *, body: str, event: str, comments: list[dict]) -> dict:
    if event not in REVIEW_EVENTS:
        raise ActionError(f"event must be one of {', '.join(REVIEW_EVENTS)}")
    clean = []
    for c in comments[:50]:
        if not (isinstance(c, dict) and c.get("path") and isinstance(c.get("line"), int) and c["line"] > 0 and str(c.get("body", "")).strip()):
            raise ActionError("every inline comment needs a path, a positive line number and a body")
        clean.append({"path": c["path"], "line": c["line"], "side": c.get("side", "RIGHT"), "body": str(c["body"])[:4000], "severity": c.get("severity", "")})
    if not body.strip() and not clean:
        raise ActionError("a review needs a summary or at least one comment")
    warnings = []
    if event != "COMMENT":
        warnings.append(f"This will {'approve' if event == 'APPROVE' else 'request changes on'} the pull request on GitHub. Others will see your verdict.")
    if pr.get("author"):
        warnings.append(f"Posted as the signed-in GitHub user. The pull request is by {pr['author']}.")
    preview = {"title": f"Post a review on {owner}/{repo}#{pr['number']} ({event.lower().replace('_', ' ')})", "destructive": False, "repo": f"{owner}/{repo}", "number": pr["number"],
               "pr_title": pr.get("title", ""), "event": event, "body": body, "comments": clean, "comment_count": len(clean), "warnings": warnings, "confirm_text": None}
    return store.create(repo_id, "post_review", {"body": body, "event": event, "comments": clean, "number": pr["number"]}, preview,
                        {"owner": owner, "repo": repo, "head_sha": pr.get("head_sha", "")})


# ---- approval and execution ------------------------------------------------------------------------------------------------------------------
def approve(store: ActionStore, rec: dict, *, approved: bool, confirm_text: str = "", root: Path | None = None, token: str = "", settings=None, gh_factory=None,
            remote_check=None, push_runner=None) -> dict:
    remote_check = remote_check or validate_remote
    if approved is not True:
        raise ApprovalRequired("this operation needs the user's explicit approval (approved: true)")
    if rec["status"] != "pending":
        raise ActionError(f"this action is {rec['status']}; propose it again if you still want it")
    need = rec["preview"].get("confirm_text")
    if need and confirm_text.strip() != need:
        raise ApprovalRequired(f"type the branch name '{need}' to confirm this operation")
    rec["history"].append({"ts": time.time(), "event": "approved"})
    try:
        if rec["kind"] in ("push", "force_push"):
            result = _do_push(rec, root, token, settings, remote_check, push_runner)
        elif rec["kind"] == "create_pr":
            gh = (gh_factory or GitHub)(token)
            st = rec["state"]
            if not gh.branch_exists(st["owner"], st["repo"], rec["params"]["head"]):
                raise ActionStale(f"the branch '{rec['params']['head']}' is not on GitHub yet: push it first")
            result = gh.create_pull(st["owner"], st["repo"], title=rec["params"]["title"], body=rec["params"]["body"], head=rec["params"]["head"], base=rec["params"]["base"], draft=rec["params"]["draft"])
        elif rec["kind"] == "post_review":
            gh = (gh_factory or GitHub)(token)
            st = rec["state"]
            current = gh.pull(st["owner"], st["repo"], rec["params"]["number"])
            if st.get("head_sha") and current["head_sha"] != st["head_sha"]:
                raise ActionStale("the pull request has new commits since you previewed this review; analyse it again")
            result = gh.create_review(st["owner"], st["repo"], rec["params"]["number"], body=rec["params"]["body"], event=rec["params"]["event"], comments=rec["params"]["comments"],
                                      commit_id=st.get("head_sha") or None)
        else:
            raise ActionError(f"unknown action kind {rec['kind']}")
    except ActionStale:
        rec["status"] = "stale"
        rec["history"].append({"ts": time.time(), "event": "stale"})
        store.save(rec)
        raise
    except (ActionError, GitHubError, PermissionError, gitops.GitError) as e:
        rec["status"] = "failed"
        rec["result"] = {"error": str(e)[:400]}
        rec["history"].append({"ts": time.time(), "event": "failed"})
        store.save(rec)
        raise
    rec["status"], rec["result"] = "executed", result
    rec["history"].append({"ts": time.time(), "event": "executed"})
    return store.save(rec)


def _do_push(rec: dict, root: Path | None, token: str, settings, remote_check, push_runner) -> dict:
    if root is None:
        raise ActionError("repository not available")
    p, st = rec["params"], rec["state"]
    head = gitops._git(root, "rev-parse", f"refs/heads/{p['branch']}", check=False).stdout.strip()
    if head != st["head"]:
        raise ActionStale(f"'{p['branch']}' has new commits since you previewed this push; review it again")
    url = remote_url(root, p["remote"])
    remote_check(url, st["source"])                         # re-check at execution time: the config could have changed since the preview
    header = providers.auth_header("github", settings, token) if settings is not None else None
    if not header and push_runner is None:
        raise PermissionError("GitHub is not connected: sign in with GitHub, or set GITHUB_TOKEN on the server")
    args = ["push", "--force-with-lease" if p["force"] else "--no-force-with-lease", "-u", p["remote"], f"refs/heads/{p['branch']}:refs/heads/{p['branch']}"]
    args = [a for a in args if a != "--no-force-with-lease"]
    r = (push_runner or gitops._git)(root, *args, check=False, timeout=300, extra_env=gitops.net_env(header))
    if r.returncode != 0:
        raise ActionError("git push failed: " + _scrub((r.stderr or r.stdout).strip(), token)[:300])
    return {"pushed": p["branch"], "head": head[:8], "remote": _clean_url(url), "output": _scrub((r.stderr or r.stdout).strip(), token)[-300:]}


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def reject(store: ActionStore, rec: dict) -> dict:
    if rec["status"] != "pending":
        raise ActionError(f"this action is {rec['status']}")
    rec["status"] = "rejected"
    rec["history"].append({"ts": time.time(), "event": "rejected"})
    return store.save(rec)
