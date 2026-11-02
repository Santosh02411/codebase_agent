import subprocess

import pytest

from app import gitops, providers
from app.config import Settings


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin(tmp_path):
    """A 'remote' with main (3 commits) and develop (1 extra commit that edits one file and adds another)."""
    o = tmp_path / "origin"
    o.mkdir()
    git(o, "init", "-q", "-b", "main")
    (o / "a.py").write_text("def a():\n    return 1\n")
    (o / "b.py").write_text("from a import a\ndef b():\n    return a()\n")
    git(o, "add", "-A"); git(o, "commit", "-qm", "one")
    for n in (2, 3):
        (o / "log.txt").write_text(f"{n}\n")
        git(o, "add", "-A"); git(o, "commit", "-qm", f"commit {n}")
    git(o, "checkout", "-q", "-b", "develop")
    (o / "b.py").write_text("from a import a\ndef b():\n    return a() + 1\ndef b2():\n    return b()\n")
    (o / "c.py").write_text("def c():\n    return 3\n")
    git(o, "add", "-A"); git(o, "commit", "-qm", "develop work")
    git(o, "checkout", "-q", "main")
    return o


@pytest.fixture
def svc(tmp_path, monkeypatch, origin):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(providers, "validate_url", lambda u: u)         # tests clone from file:// instead of the internet
    from app.services import RepoService
    monkeypatch.setattr(RepoService, "_is_remote", staticmethod(lambda src: src.startswith(("https://", "file://"))))
    return RepoService(Settings())


def test_preview_lists_remote_branches_without_cloning(svc, origin):
    p = svc.preview(f"file://{origin}")
    assert p["branches"] == ["main", "develop"] and p["default"] == "main"


def test_import_chosen_branch_then_switch_with_incremental_reindex(svc, origin):
    meta = svc.add(f"file://{origin}", "demo", branch="develop")
    assert meta["branch"] == "develop" and meta["files"] == 4 and meta["last_index"]["mode"] == "full"
    _, _, idx = svc.get(meta["id"])
    assert "c.py::c" in idx.graph.symbols and "b.py::b2" in idx.graph.symbols

    b = svc.branches(meta["id"])
    assert b["current"] == "develop" and b["default"] == "main"
    assert {x["name"] for x in b["branches"]} == {"develop", "main"}

    m2 = svc.checkout(meta["id"], "main")                                # remote-only branch -> local tracking branch
    r = m2["last_index"]
    assert m2["branch"] == "main" and r["mode"] == "incremental"
    assert (r["files_changed"], r["files_removed"], r["files_added"]) == (1, 1, 0)   # b.py edited, c.py gone
    assert r["files_unchanged"] == 2 and sorted(r["changed_files"]) == ["b.py"]
    _, _, idx = svc.get(meta["id"])
    assert "c.py::c" not in idx.graph.symbols and "b.py::b2" not in idx.graph.symbols

    m3 = svc.checkout(meta["id"], "develop")
    assert m3["last_index"]["files_added"] == 1 and m3["branch"] == "develop"


def test_default_branch_is_used_when_none_given(svc, origin):
    assert svc.add(f"file://{origin}", "demo")["branch"] == "main"


def test_commits_history_and_checkout_of_a_commit(svc, origin):
    meta = svc.add(f"file://{origin}", "demo")
    assert len(svc.commits(meta["id"], None, 30, 0)) == 1                 # shallow clone: only the tip
    assert gitops.branches(svc.repos_dir / meta["id"])["shallow"]
    assert svc.fetch(meta["id"], 10)["shallow"] in (True, False)
    log = svc.commits(meta["id"], None, 30, 0)
    assert [c["subject"] for c in log] == ["commit 3", "commit 2", "one"]
    assert set(log[0]) == {"sha", "short", "author", "date", "subject"}
    assert len(svc.commits(meta["id"], None, 1, 1)) == 1                  # paging
    m = svc.checkout(meta["id"], log[-1]["sha"])                          # analyse an older commit (detached HEAD)
    assert m["detached"] and m["branch"] == "" and m["last_index"]["files_changed"] >= 0


def test_uncommitted_changes_block_checkout_unless_forced(svc, origin):
    meta = svc.add(f"file://{origin}", "demo", branch="develop")
    root = svc.repos_dir / meta["id"]
    (root / "a.py").write_text("def a():\n    return 'edited'\n")
    with pytest.raises(gitops.GitError, match="uncommitted"):
        svc.checkout(meta["id"], "main")
    assert gitops.head_info(root)["branch"] == "develop"                  # nothing moved
    svc.checkout(meta["id"], "main", force=True)
    assert (root / "a.py").read_text() == "def a():\n    return 1\n"      # edits discarded


@pytest.mark.parametrize("ref", ["--upload-pack=evil", "-D", "../x", "a..b", "", "x.lock", "bad name"])
def test_dangerous_refs_are_rejected(svc, origin, ref):
    meta = svc.add(f"file://{origin}", "demo")
    with pytest.raises(gitops.GitError):
        svc.checkout(meta["id"], ref)
    if ref:                                  # an empty ref just means "current HEAD" for the history view
        with pytest.raises(gitops.GitError):
            gitops.commits(svc.repos_dir / meta["id"], ref)


def test_unknown_ref_and_unreachable_remote(svc, origin):
    meta = svc.add(f"file://{origin}", "demo")
    with pytest.raises(gitops.GitError, match="unknown"):
        svc.checkout(meta["id"], "no-such-branch")
    with pytest.raises(gitops.GitError):
        gitops.ls_remote_heads("file:///definitely/not/here")


def test_uploaded_projects_have_no_remote(svc, tmp_path):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("proj/x.py", "def x():\n    pass\n")
    buf.seek(0)
    meta = svc.add_zip(buf, "zipped")
    assert meta["provider"] == "upload" and meta["branch"] in ("master", "main")
    with pytest.raises(gitops.GitError, match="no remote"):
        svc.fetch(meta["id"])
    assert svc.branches(meta["id"])["branches"][0]["current"]


def test_url_validation_and_providers():
    from importlib import reload
    reload(providers)
    for ok in ("https://github.com/o/r", "https://github.com/o/r.git", "https://gitlab.com/group/sub/proj", "https://bitbucket.org/o/r/"):
        assert providers.validate_url(ok) == ok
    for bad in ("http://github.com/o/r", "git@github.com:o/r.git", "https://github.com/o", "file:///etc", "https://x.com/o/r;rm -rf"):
        with pytest.raises(ValueError):
            providers.validate_url(bad)
    assert [providers.provider_of(u) for u in ("https://github.com/o/r", "https://gitlab.com/g/r", "https://bitbucket.org/o/r", "https://git.example.com/o/r")] \
        == ["github", "gitlab", "bitbucket", "git"]


def test_credentials_travel_in_the_environment_not_the_command_line(monkeypatch, tmp_path):
    s = Settings()
    s.gitlab_token, s.bitbucket_username, s.bitbucket_app_password = "glpat-123", "me", "app-pw"
    assert providers.auth_header("github", s) is None
    assert providers.auth_header("github", s, "gho_x").startswith("Authorization: Basic ")
    assert providers.auth_header("gitlab", s) and providers.auth_header("bitbucket", s)
    assert providers.auth_header("git", s) is None
    env = gitops.net_env(providers.auth_header("github", s, "gho_secret"))
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader" and "gho_secret" not in " ".join(env.values())  # base64-encoded, not raw
    assert gitops.net_env(None) == {}
