"""Git hosting providers. GitHub supports OAuth; GitLab and Bitbucket work by URL (public repos, or private with a token in .env).
Adding OAuth for another provider means adding a login/callback pair in app/auth.py and a branch in `auth_header` here."""
from __future__ import annotations
import base64
import re
from urllib.parse import urlparse

from .config import Settings

HOSTS = {"github.com": "github", "gitlab.com": "gitlab", "bitbucket.org": "bitbucket"}
_URL = re.compile(r"^https://[\w.-]+(:\d+)?/[\w.\-]+(/[\w.\-]+)+?(\.git)?/?$")


def validate_url(url: str) -> str:
    url = url.strip()
    if not _URL.match(url):
        raise ValueError("enter a repository URL like https://github.com/owner/repo (GitLab and Bitbucket URLs work too)")
    return url


def provider_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host in HOSTS:
        return HOSTS[host]
    if host.startswith("gitlab."):
        return "gitlab"
    return "git"


def display_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def basic(user: str, secret: str) -> str:
    return "Authorization: Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


def auth_header(provider: str, settings: Settings, oauth_token: str | None = None) -> str | None:
    """HTTP auth header for git over https, or None for anonymous access."""
    if provider == "github":
        tok = oauth_token or settings.github_token
        return basic("x-access-token", tok) if tok else None
    if provider == "gitlab":
        return basic("oauth2", settings.gitlab_token) if settings.gitlab_token else None
    if provider == "bitbucket":
        if settings.bitbucket_username and settings.bitbucket_app_password:
            return basic(settings.bitbucket_username, settings.bitbucket_app_password)
    return None
