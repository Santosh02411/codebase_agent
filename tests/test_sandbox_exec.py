"""The execution sandbox: the exact Docker flags, limits, timeouts and what happens when Docker is missing."""
import os
import sys
import time
from pathlib import Path

import pytest

from app import sandbox, sandbox_exec
from app.sandbox_exec import Limits, SandboxUnavailable, build_docker_cmd
from tests import fakedocker


@pytest.fixture
def docker(tmp_path, monkeypatch):
    log = tmp_path / "docker.log"
    fakedocker.install(tmp_path / "bin", log)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    sandbox_exec.reset_cache()
    yield log
    sandbox_exec.reset_cache()


def flag_values(cmd, name):
    return [cmd[i + 1] for i, c in enumerate(cmd) if c == name]


# ---- the command line itself ----------------------------------------------------------------------------------------------------------
def test_docker_command_is_locked_down(tmp_path):
    cmd = build_docker_cmd(tmp_path, ["python", "-m", "pytest"], image="img:1", name="n1", limits=Limits(cpus=1.5, memory_mb=512, pids=100, tmpfs_mb=64), uid=1000)
    assert cmd[:3] == ["docker", "run", "--rm"] and cmd[-4:] == ["img:1", "python", "-m", "pytest"]
    assert flag_values(cmd, "--network") == ["none"]                                                    # no network by default
    assert flag_values(cmd, "--cpus") == ["1.5"] and flag_values(cmd, "--memory") == ["512m"] and flag_values(cmd, "--memory-swap") == ["512m"]   # no swap past the limit
    assert flag_values(cmd, "--pids-limit") == ["100"]
    assert "--read-only" in cmd and "--init" in cmd
    assert flag_values(cmd, "--cap-drop") == ["ALL"] and "no-new-privileges" in flag_values(cmd, "--security-opt")
    assert flag_values(cmd, "--user")[0].startswith("1000:")                                           # never root
    tmpfs = flag_values(cmd, "--tmpfs")
    assert any(t.startswith("/tmp:") and "noexec" in t and "nosuid" in t and "size=64m" in t for t in tmpfs)
    assert flag_values(cmd, "-v") == [f"{tmp_path}:/work:rw"]                                          # the ONE mount: the throw-away copy
    assert "--privileged" not in cmd and not [c for c in cmd if "docker.sock" in c]


def test_docker_command_variants(tmp_path):
    ro = build_docker_cmd(tmp_path, ["ruff"], image="i", name="n", limits=Limits(), readonly=True, uid=1000)
    assert flag_values(ro, "-v") == [f"{tmp_path}:/work:ro"]
    net = build_docker_cmd(tmp_path, ["pip"], image="i", name="n", limits=Limits(), network=True, uid=1000)
    assert flag_values(net, "--network") == ["bridge"]
    go = build_docker_cmd(tmp_path, ["go"], image="i", name="n", limits=Limits(), language="go", uid=1000)
    assert not any("noexec" in t for t in flag_values(go, "--tmpfs"))                                   # compiled test binaries run from $TMPDIR
    root = build_docker_cmd(tmp_path, ["x"], image="i", name="n", limits=Limits(), uid=0)
    assert flag_values(root, "--user") == ["65534:65534"]                                              # a root server still runs the container as nobody


def test_only_an_explicit_environment_enters_the_container(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    cmd = build_docker_cmd(tmp_path, ["x"], image="i", name="n", limits=Limits(), env={"PYTHONPATH": "/work"}, uid=1000)
    flat = " ".join(cmd)
    assert "sk-secret" not in flat and "ghp_secret" not in flat and "OPENAI" not in flat
    assert "HOME=/home/sandbox" in cmd and "PYTHONPATH=/work" in cmd and "TMPDIR=/tmp" in cmd


# ---- running through a (fake) docker ------------------------------------------------------------------------------------------------------
def test_run_uses_docker_and_cleans_up(docker, tmp_path):
    (tmp_path / "w").mkdir()
    r = sandbox_exec.run(tmp_path / "w", [sys.executable, "-c", "print('hello from the sandbox')"], timeout=30)
    assert r.mode == "docker" and r.returncode == 0 and "hello from the sandbox" in r.stdout and r.image.startswith("codebase-agent/sandbox-python")
    calls = fakedocker.calls(docker)
    run = next(c for c in calls if c["cmd"] == "run")
    assert ["--network", "none"] in run["flags"] and "--read-only" in run["flags"]
    assert any(c["cmd"] == "rm" and c["args"][0] == "-f" for c in calls)                              # the container is always removed


def test_a_run_that_exceeds_its_timeout_is_killed_from_outside(docker, tmp_path):
    (tmp_path / "w").mkdir()
    t0 = time.time()
    r = sandbox_exec.run(tmp_path / "w", [sys.executable, "-c", "import time; time.sleep(30)"], timeout=2)
    assert r.timed_out and r.returncode == -9 and time.time() - t0 < 15
    names = [c["cmd"] for c in fakedocker.calls(docker)]
    assert "kill" in names and "rm" in names                                                            # docker kill + docker rm -f


def test_output_is_bounded_and_the_process_is_not_blocked_by_it(docker, tmp_path):
    (tmp_path / "w").mkdir()
    r = sandbox_exec.run(tmp_path / "w", [sys.executable, "-c", "print('x' * 3_000_000)"], timeout=60, limits=Limits(output_bytes=10_000))
    assert r.returncode == 0 and r.truncated and len(r.stdout) <= 10_000


def test_missing_docker_refuses_to_run_anything(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    monkeypatch.setenv("PATH", "/nonexistent")
    sandbox_exec.reset_cache()
    marker = tmp_path / "ran"
    with pytest.raises(SandboxUnavailable, match="Docker is not available"):
        sandbox_exec.run(tmp_path, [sys.executable, "-c", f"open({str(marker)!r}, 'w')"])
    assert not marker.exists()                                                                          # it did NOT fall back to the host
    assert sandbox_exec.status()["isolated"] and sandbox_exec.status()["docker_available"] is False and "problem" in sandbox_exec.status()


def test_missing_image_refuses_to_run(tmp_path, monkeypatch):
    fakedocker.install(tmp_path / "bin", tmp_path / "log", image_ok=False)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    sandbox_exec.reset_cache()
    with pytest.raises(SandboxUnavailable, match="not built"):
        sandbox_exec.run(tmp_path, ["true"], language="go")


def test_unknown_modes_fall_back_to_docker_never_to_the_host(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "yolo")
    assert sandbox_exec.mode() == "docker"


# ---- the test runner on top of it -------------------------------------------------------------------------------------------------------------
def test_run_tests_through_docker_and_without_it(docker, tmp_path, monkeypatch):
    work = tmp_path / "proj"
    work.mkdir()
    (work / "test_a.py").write_text("def test_ok():\n    assert True\n")
    r = sandbox.run_tests(work, 60)
    assert r["status"] == "passed" and r["sandbox"]["mode"] == "docker" and r["framework"] == "pytest"
    run = next(c for c in fakedocker.calls(docker) if c["cmd"] == "run")
    assert run["argv"][0] == "python" and run["env"]["PYTHONPATH"].startswith("/work")                  # the host interpreter path never leaks into the container
    monkeypatch.setenv("PATH", "/nonexistent")
    sandbox_exec.reset_cache()
    r = sandbox.run_tests(work, 60)
    assert r["status"] == "sandbox_unavailable" and "Docker is not available" in r["summary"] and r["passed"] is False


def test_local_mode_scrubs_secrets_and_is_labelled_unsafe(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    r = sandbox_exec.run(tmp_path, [sys.executable, "-c", "import os; print(os.environ.get('OPENAI_API_KEY', 'absent'))"])
    assert r.mode == "local" and r.stdout.strip() == "absent"
    st = sandbox_exec.status()
    assert st["isolated"] is False and "no isolation" in st["warning"]


def test_local_mode_enforces_timeout_and_kills_the_process_group(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "local")
    marker = tmp_path / "grandchild-survived"
    code = f"import subprocess, time; subprocess.Popen(['sh', '-c', 'sleep 3; touch {marker}']); time.sleep(30)"
    r = sandbox_exec.run(tmp_path, [sys.executable, "-c", code], timeout=1)
    assert r.timed_out
    time.sleep(4)
    assert not marker.exists()


def test_copies_do_not_pull_in_files_from_outside_the_repo(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("host secret")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    (repo / "link.txt").symlink_to(outside)
    work = sandbox.copy_repo(repo)
    try:
        assert (work / "link.txt").is_symlink()                      # still a link: the target's content was not copied into the sandbox
        assert "host secret" not in "".join(p.read_text() for p in work.rglob("*") if p.is_file() and not p.is_symlink())
    finally:
        sandbox.cleanup(work)


# ---- capacity: a public server must not start unlimited containers ------------------------------------------------------------------------------
def test_concurrent_runs_are_capped_and_queue(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("SANDBOX_MODE", "local")
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "1")
    monkeypatch.setenv("SANDBOX_QUEUE_TIMEOUT", "30")
    (tmp_path / "w").mkdir()
    code = "import time; time.sleep(1)"
    t0 = time.time()
    done = []
    threads = [threading.Thread(target=lambda: done.append(sandbox_exec.run(tmp_path / "w", [sys.executable, "-c", code], timeout=20))) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(done) == 3 and all(r.returncode == 0 for r in done) and time.time() - t0 >= 2.8       # one at a time, the rest waited in line


def test_a_full_sandbox_refuses_instead_of_waiting_forever(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("SANDBOX_MODE", "local")
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "1")
    monkeypatch.setenv("SANDBOX_QUEUE_TIMEOUT", "0.5")
    (tmp_path / "w").mkdir()
    t = threading.Thread(target=lambda: sandbox_exec.run(tmp_path / "w", [sys.executable, "-c", "import time; time.sleep(2)"], timeout=10))
    t.start()
    time.sleep(0.4)
    with pytest.raises(sandbox_exec.SandboxBusy, match="busy"):
        sandbox_exec.run(tmp_path / "w", ["true"], timeout=5)
    t.join()
    assert issubclass(sandbox_exec.SandboxBusy, SandboxUnavailable)                                   # callers already report this as "not verified", never as a pass
    r = sandbox.run_tests(tmp_path / "w", 5)
    assert r["status"] in ("no_tests", "passed", "failed")                                           # the slot was released: later runs work again


def test_the_rate_limit_applies_to_expensive_endpoints_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import ratelimit
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    import app.main as m
    ratelimit.reset()
    c = TestClient(m.app)
    codes = [c.post("/chat", json={"repo_id": "nope", "question": "q"}).status_code for _ in range(5)]
    assert codes[:3] == [404, 404, 404] and codes[3:] == [429, 429]                                   # the first three reached the handler, the rest were stopped
    r = c.post("/chat", json={"repo_id": "nope", "question": "q"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "Too many requests" in r.json()["detail"]
    assert all(c.get("/health").status_code == 200 for _ in range(10))                                # cheap reads are never limited
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    ratelimit.reset()
    assert c.post("/chat", json={"repo_id": "nope", "question": "q"}).status_code == 404               # 0 = off
    assert ratelimit.check("k", 2, now=0) == 0 and ratelimit.check("k", 2, now=1) == 0 and ratelimit.check("k", 2, now=2) > 0 and ratelimit.check("k", 2, now=61) == 0
