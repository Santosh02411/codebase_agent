"""GitHub REST client for pull requests, issues and reviews (the parts of GitHub the platform acts on).
Reads are free. Anything that writes to GitHub (create_pull, create_review) is only ever called from app/actions.py after a human approved the exact content."""
from __future__ import annotations
import re

import httpx

API = "https://api.github.com"
MAX_PAGES = 6


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub {status}: {message}")
        self.status, self.message = status, message


def parse_remote(url: str) -> tuple[str, str]:
    """owner, repo from an https or ssh GitHub remote URL."""
    m = re.fullmatch(r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?", (url or "").strip())
    if not m:
        raise ValueError("this project is not a GitHub repository (add it from a GitHub URL or the GitHub repository list)")
    return m.group(1), m.group(2)


class GitHub:
    def __init__(self, token: str, client: httpx.Client | None = None, api: str = API) -> None:
        if not token:
            raise PermissionError("GitHub is not connected: sign in with GitHub, or set GITHUB_TOKEN on the server")
        self.token, self.api = token, api
        self.c = client or httpx.Client(timeout=30, follow_redirects=False)

    def _req(self, method: str, path: str, *, accept: str = "application/vnd.github+json", **kw):
        r = self.c.request(method, f"{self.api}{path}", headers={"Authorization": f"Bearer {self.token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}, **kw)
        if r.status_code == 401:
            raise PermissionError("GitHub rejected the saved token: reconnect GitHub")
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", "request failed")
            except ValueError:
                msg = "request failed"
            if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
                msg = "rate limit reached; try again later"
            elif r.status_code == 404:
                msg = "not found, or the token has no access to it"
            raise GitHubError(r.status_code, msg)
        return r

    def _paged(self, path: str, limit: int, **params) -> list[dict]:
        out: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            rows = self._req("GET", path, params={**params, "per_page": min(100, limit), "page": page}).json()
            out += rows
            if len(rows) < min(100, limit) or len(out) >= limit:
                break
        return out[:limit]

    # ---- reads ---------------------------------------------------------------------------------------------------------------------
    def repo(self, owner: str, repo: str) -> dict:
        d = self._req("GET", f"/repos/{owner}/{repo}").json()
        return {"full_name": d["full_name"], "default_branch": d.get("default_branch", "main"), "private": d.get("private", False), "url": d.get("html_url", ""),
                "permissions": d.get("permissions") or {}, "fork": d.get("fork", False)}

    @staticmethod
    def _pr(d: dict) -> dict:
        return {"number": d["number"], "title": d.get("title", ""), "state": d.get("state", ""), "draft": d.get("draft", False), "author": (d.get("user") or {}).get("login", ""),
                "base": (d.get("base") or {}).get("ref", ""), "head": (d.get("head") or {}).get("ref", ""), "head_sha": (d.get("head") or {}).get("sha", ""),
                "base_sha": (d.get("base") or {}).get("sha", ""), "head_repo": ((d.get("head") or {}).get("repo") or {}).get("full_name", ""), "url": d.get("html_url", ""),
                "labels": [l.get("name", "") for l in d.get("labels", [])], "updated_at": d.get("updated_at", ""), "created_at": d.get("created_at", ""),
                "body": d.get("body") or "", "changed_files": d.get("changed_files"), "additions": d.get("additions"), "deletions": d.get("deletions"),
                "commits": d.get("commits"), "mergeable": d.get("mergeable"), "merged": d.get("merged", False)}

    def pulls(self, owner: str, repo: str, state: str = "open", limit: int = 30) -> list[dict]:
        return [self._pr(d) for d in self._paged(f"/repos/{owner}/{repo}/pulls", limit, state=state, sort="updated", direction="desc")]

    def pull(self, owner: str, repo: str, number: int) -> dict:
        return self._pr(self._req("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}").json())

    def pull_files(self, owner: str, repo: str, number: int, limit: int = 300) -> list[dict]:
        rows = self._paged(f"/repos/{owner}/{repo}/pulls/{int(number)}/files", limit)
        return [{"path": f["filename"], "status": f.get("status", "modified"), "additions": f.get("additions", 0), "deletions": f.get("deletions", 0), "patch": f.get("patch", ""),
                 "old_path": f.get("previous_filename")} for f in rows]

    def pull_commits(self, owner: str, repo: str, number: int, limit: int = 100) -> list[dict]:
        return [{"sha": c["sha"], "message": c["commit"]["message"], "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]}
                for c in self._paged(f"/repos/{owner}/{repo}/pulls/{int(number)}/commits", limit)]

    def pull_diff(self, owner: str, repo: str, number: int) -> str:
        return self._req("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}", accept="application/vnd.github.v3.diff").text

    def pull_feedback(self, owner: str, repo: str, number: int, limit: int = 40) -> list[dict]:
        """Existing review comments and conversation, so the AI does not repeat what was already said."""
        out = []
        for c in self._paged(f"/repos/{owner}/{repo}/pulls/{int(number)}/comments", limit):
            out.append({"author": (c.get("user") or {}).get("login", ""), "path": c.get("path"), "line": c.get("line"), "body": (c.get("body") or "")[:600]})
        for c in self._paged(f"/repos/{owner}/{repo}/issues/{int(number)}/comments", limit):
            out.append({"author": (c.get("user") or {}).get("login", ""), "path": None, "line": None, "body": (c.get("body") or "")[:600]})
        return out

    def issues(self, owner: str, repo: str, state: str = "open", limit: int = 30) -> list[dict]:
        rows = self._paged(f"/repos/{owner}/{repo}/issues", limit * 2, state=state, sort="updated", direction="desc")
        return [{"number": d["number"], "title": d.get("title", ""), "state": d.get("state", ""), "author": (d.get("user") or {}).get("login", ""), "labels": [l.get("name", "") for l in d.get("labels", [])],
                 "comments": d.get("comments", 0), "updated_at": d.get("updated_at", ""), "url": d.get("html_url", "")} for d in rows if "pull_request" not in d][:limit]

    def issue(self, owner: str, repo: str, number: int) -> dict:
        d = self._req("GET", f"/repos/{owner}/{repo}/issues/{int(number)}").json()
        if "pull_request" in d:
            raise GitHubError(422, f"#{number} is a pull request, not an issue")
        comments = [{"author": (c.get("user") or {}).get("login", ""), "body": (c.get("body") or "")[:1500]} for c in self._paged(f"/repos/{owner}/{repo}/issues/{int(number)}/comments", 20)]
        return {"number": d["number"], "title": d.get("title", ""), "body": d.get("body") or "", "state": d.get("state", ""), "author": (d.get("user") or {}).get("login", ""),
                "labels": [l.get("name", "") for l in d.get("labels", [])], "url": d.get("html_url", ""), "comments": comments}

    def branch_exists(self, owner: str, repo: str, branch: str) -> bool:
        try:
            self._req("GET", f"/repos/{owner}/{repo}/branches/{branch}")
            return True
        except GitHubError as e:
            if e.status == 404:
                return False
            raise

    # ---- writes: reached only through an approved action (app/actions.py) --------------------------------------------------------------
    def create_pull(self, owner: str, repo: str, *, title: str, body: str, head: str, base: str, draft: bool = False) -> dict:
        d = self._req("POST", f"/repos/{owner}/{repo}/pulls", json={"title": title, "body": body, "head": head, "base": base, "draft": draft}).json()
        return {"number": d["number"], "url": d["html_url"]}

    def create_review(self, owner: str, repo: str, number: int, *, body: str, event: str, comments: list[dict], commit_id: str | None = None) -> dict:
        payload: dict = {"body": body, "event": event, "comments": [{"path": c["path"], "line": c["line"], "side": c.get("side", "RIGHT"), "body": c["body"]} for c in comments]}
        if commit_id:
            payload["commit_id"] = commit_id
        d = self._req("POST", f"/repos/{owner}/{repo}/pulls/{int(number)}/reviews", json=payload).json()
        return {"id": d.get("id"), "url": d.get("html_url", "")}
