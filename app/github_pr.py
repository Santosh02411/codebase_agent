from __future__ import annotations
import base64
import re
import time
from urllib.parse import quote

import httpx

API = "https://api.github.com"


def parse_repo(source: str) -> tuple[str, str]:
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?", source or "")
    if not m:
        raise ValueError("pull requests need a project that was added from a GitHub URL")
    return m.group(1), m.group(2)


def create_pr(source: str, token: str, files: dict[str, str], title: str, body: str = "",
              client: httpx.Client | None = None) -> dict:
    """Branch from the default branch, commit each file through the contents API, open a PR.
    No local git or push needed; the token never leaves the server."""
    if not token:
        raise ValueError("GITHUB_TOKEN is not set on the server")
    if not files:
        raise ValueError("no files to commit")
    owner, repo = parse_repo(source)
    c = client or httpx.Client(timeout=30)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def call(method: str, path: str, ok404: bool = False, **kw) -> dict | None:
        r = c.request(method, f"{API}/repos/{owner}/{repo}{path}", headers=headers, **kw)
        if r.status_code == 404 and ok404:
            return None
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", "request failed")
            except Exception:
                msg = "request failed"
            raise ValueError(f"GitHub {r.status_code}: {msg}")
        return r.json()

    base = call("GET", "")["default_branch"]
    sha = call("GET", f"/git/ref/heads/{base}")["object"]["sha"]
    branch = f"agent/change-{int(time.time())}"
    call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
    for path, content in files.items():
        existing = call("GET", f"/contents/{quote(path)}?ref={branch}", ok404=True)
        payload = {"message": title, "branch": branch, "content": base64.b64encode(content.encode()).decode()}
        if existing and existing.get("sha"):
            payload["sha"] = existing["sha"]
        call("PUT", f"/contents/{quote(path)}", json=payload)
    pr = call("POST", "/pulls", json={"title": title, "body": body, "head": branch, "base": base})
    return {"url": pr["html_url"], "number": pr["number"], "branch": branch}
