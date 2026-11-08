"""The one place repository code is executed.

Repositories (and the tools an agent runs on them) are untrusted: a test file, a conftest.py, a build script or a linter plugin is
arbitrary code. So nothing in this application runs it on the host unless the operator explicitly chose SANDBOX_MODE=local.

docker mode (default) starts a throw-away container per run with:
  --network none                no network (a separate, explicitly enabled step exists for dependency install / audits)
  --cpus / --memory / --pids    resource ceilings (memory-swap = memory, so no swapping past the limit)
  --read-only + --tmpfs         read-only root filesystem; /tmp and $HOME are small RAM-backed scratch space (noexec where the toolchain allows)
  --cap-drop ALL, no-new-privileges, non-root user, default seccomp/AppArmor profiles
  a bind mount of ONE throw-away copy of the project (or the project read-only for pure analysis), nothing else from the host
  a wall-clock timeout enforced from outside the container (docker kill), bounded captured output, no host environment variables

local mode runs the command with rlimits (CPU, address space, file size, processes) in its own process group. It is NOT isolation."""
from __future__ import annotations
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_settings

SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "CI": "true", "NO_COLOR": "1"}
EXEC_TMPFS = {"go", "rust", "java", "node"}        # these toolchains compile / unpack executables into $TMPDIR
_CACHE: dict[str, tuple[float, object]] = {}


class SandboxUnavailable(RuntimeError):
    """The configured sandbox cannot run (Docker missing / image not built). Nothing was executed."""


class SandboxBusy(SandboxUnavailable):
    """Every sandbox slot stayed taken for the whole queue timeout. Nothing was executed; try again shortly."""


_slots: tuple[int, threading.BoundedSemaphore] | None = None
_slots_lock = threading.Lock()


def _slot_semaphore() -> threading.BoundedSemaphore:
    """One server-wide semaphore (rebuilt if SANDBOX_MAX_CONCURRENT changes): the cap on simultaneous containers."""
    global _slots
    n = max(1, get_settings().sandbox_max_concurrent)
    with _slots_lock:
        if _slots is None or _slots[0] != n:
            _slots = (n, threading.BoundedSemaphore(n))
        return _slots[1]


@dataclass
class Limits:
    cpus: float = 1.0
    memory_mb: int = 1024
    pids: int = 256
    tmpfs_mb: int = 256
    output_bytes: int = 1_000_000


@dataclass
class ExecResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = 0
    truncated: bool = False
    mode: str = "docker"
    image: str = ""
    command: list[str] = field(default_factory=list)

    @property
    def output(self) -> str:
        return (self.stdout + ("\n" if self.stdout and self.stderr else "") + self.stderr).strip()


def default_limits() -> Limits:
    s = get_settings()
    return Limits(s.sandbox_cpus, s.sandbox_memory_mb, s.sandbox_pids, s.sandbox_tmpfs_mb, s.sandbox_output_limit)


def mode() -> str:
    m = get_settings().sandbox_mode
    return m if m in ("docker", "local") else "docker"


def _cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def docker_ok() -> bool:
    def probe() -> bool:
        if not shutil.which("docker"):
            return False
        try:
            return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return bool(_cached("docker", 30.0, probe))


def image_ok(image: str) -> bool:
    def probe() -> bool:
        try:
            return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return bool(_cached(f"image:{image}", 30.0, probe))


def reset_cache() -> None:
    _CACHE.clear()


def status() -> dict:
    s = get_settings()
    m = mode()
    out = {"mode": m, "isolated": m == "docker", "network": s.sandbox_network, "limits": {"cpus": s.sandbox_cpus, "memory_mb": s.sandbox_memory_mb, "pids": s.sandbox_pids,
           "tmpfs_mb": s.sandbox_tmpfs_mb}, "install_deps": s.sandbox_install_deps, "audit_network": s.sandbox_audit_network}
    if m == "docker":
        ok = docker_ok()
        out.update(docker_available=ok, images={lang: ok and image_ok(img) for lang, img in s.sandbox_images.items()})
        if not ok:
            out["problem"] = "Docker is not available: tests, linters and other code execution are disabled until it is. (SANDBOX_MODE=local runs on the host without isolation: development only.)"
    else:
        out["warning"] = "SANDBOX_MODE=local: repository code runs directly on this machine with no isolation. Never use this on a server that processes untrusted repositories."
    return out


def build_docker_cmd(workdir: Path, argv: list[str], *, image: str, name: str, limits: Limits, language: str = "python", readonly: bool = False,
                     network: bool = False, env: dict[str, str] | None = None, uid: int | None = None, extra_mounts: list[tuple[str, str, str]] | None = None) -> list[str]:
    """The exact `docker run` command line. Pure function: the security-relevant part, unit-tested."""
    uid = os.getuid() if uid is None else uid
    user = f"{uid}:{os.getgid() if uid == os.getuid() else uid}" if uid != 0 else "65534:65534"
    tmp_opts = "rw,nosuid,nodev,size=%dm" % limits.tmpfs_mb + ("" if language in EXEC_TMPFS else ",noexec")
    cmd = ["docker", "run", "--rm", "--init", "--name", name, "--label", "codebase-agent=1",
           "--network", "bridge" if network else "none",
           "--cpus", f"{limits.cpus:g}", "--memory", f"{limits.memory_mb}m", "--memory-swap", f"{limits.memory_mb}m", "--pids-limit", str(limits.pids),
           "--ulimit", "nofile=2048:2048", "--ulimit", "core=0",
           "--read-only", "--tmpfs", f"/tmp:{tmp_opts}", "--tmpfs", "/home/sandbox:rw,nosuid,nodev,size=128m",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", user,
           "--workdir", "/work", "-v", f"{workdir}:/work:{'ro' if readonly else 'rw'}"]
    for src, dst, mode_ in extra_mounts or []:
        cmd += ["-v", f"{src}:{dst}:{mode_}"]
    full_env = {**SAFE_ENV, "HOME": "/home/sandbox", "TMPDIR": "/tmp", **(env or {})}
    for k, v in sorted(full_env.items()):
        cmd += ["-e", f"{k}={v}"]
    return cmd + [image, *argv]


def _bounded_run(cmd: list[str], *, cwd: Path | None, env: dict[str, str] | None, timeout: int, limit: int, preexec=None, on_timeout=None) -> ExecResult:
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True, preexec_fn=preexec)
    except FileNotFoundError as e:
        return ExecResult(127, stderr=f"command not found: {e.filename}", duration_ms=0, command=cmd)
    bufs: dict[str, bytearray] = {"out": bytearray(), "err": bytearray()}
    trunc = {"v": False}

    def pump(stream, key):
        for chunk in iter(lambda: stream.read(8192), b""):
            if len(bufs[key]) < limit:
                bufs[key].extend(chunk[: limit - len(bufs[key])])
            else:
                trunc["v"] = True     # keep draining so the child never blocks on a full pipe, but keep nothing
    threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True), threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    for t in threads:
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if on_timeout:
            on_timeout()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()
    for t in threads:
        t.join(timeout=5)
    dec = lambda b: bytes(b).decode("utf-8", "replace")  # noqa: E731
    return ExecResult(-9 if timed_out else proc.returncode, dec(bufs["out"]), dec(bufs["err"]), timed_out, int((time.time() - t0) * 1000), trunc["v"] or len(bufs["out"]) >= limit, command=cmd)


def _local_limits(l: Limits, timeout: int):
    def apply():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
            resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if l.memory_mb:
                resource.setrlimit(resource.RLIMIT_AS, (l.memory_mb * 4 * 1024 * 1024, l.memory_mb * 4 * 1024 * 1024))   # generous: interpreters map a lot
        except (ImportError, ValueError, OSError):
            pass
    return apply


def run(workdir: Path, argv: list[str], *, language: str = "python", timeout: int = 120, readonly: bool = False, network: bool | None = None,
        env: dict[str, str] | None = None, limits: Limits | None = None, extra_mounts: list[tuple[str, str, str]] | None = None) -> ExecResult:
    """Run `argv` with `workdir` as the working directory, isolated according to SANDBOX_MODE. Raises SandboxUnavailable if it cannot."""
    s = get_settings()
    sem = _slot_semaphore()
    if not sem.acquire(timeout=s.sandbox_queue_timeout):
        raise SandboxBusy(f"The sandbox is busy ({s.sandbox_max_concurrent} runs are already in progress). Nothing was executed; try again in a moment.")
    try:
        return _run(workdir, argv, s, language=language, timeout=timeout, readonly=readonly, network=network, env=env, limits=limits, extra_mounts=extra_mounts)
    finally:
        sem.release()


def _run(workdir: Path, argv: list[str], s, *, language: str, timeout: int, readonly: bool, network: bool | None, env: dict[str, str] | None, limits: Limits | None,
         extra_mounts: list[tuple[str, str, str]] | None) -> ExecResult:
    limits = limits or default_limits()
    workdir = workdir.resolve()
    use_net = (s.sandbox_network == "bridge") if network is None else network
    if mode() == "local":
        host_env = {**SAFE_ENV, "PATH": os.environ.get("PATH", SAFE_ENV["PATH"]), "HOME": str(workdir), "PYTHONPATH": str(workdir), **(env or {})}
        for k in ("VIRTUAL_ENV", "SYSTEMROOT", "LD_LIBRARY_PATH"):
            if k in os.environ:
                host_env[k] = os.environ[k]
        res = _bounded_run(argv, cwd=workdir, env=host_env, timeout=timeout, limit=limits.output_bytes, preexec=_local_limits(limits, timeout))
        res.mode, res.command = "local", argv
        return res
    if not docker_ok():
        raise SandboxUnavailable("Docker is not available, so repository code was not executed. Install/start Docker (the sandbox runs every test and analysis in a "
                                 "locked-down container), or set SANDBOX_MODE=local on a development machine to run without isolation.")
    image = s.sandbox_images.get(language) or s.sandbox_images["python"]
    if not image_ok(image):
        raise SandboxUnavailable(f"The sandbox image {image!r} is not built. Run scripts/build_sandbox.sh (or set SANDBOX_IMAGE_{language.upper()}).")
    if os.getuid() == 0 and not readonly:
        _open_perms(workdir)                                  # the container runs as nobody: let it write into the throw-away copy
    name = f"agent-sbx-{uuid.uuid4().hex[:12]}"
    cmd = build_docker_cmd(workdir, argv, image=image, name=name, limits=limits, language=language, readonly=readonly, network=use_net, env=env, extra_mounts=extra_mounts)

    def kill():
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=20)
    try:
        res = _bounded_run(cmd, cwd=None, env=None, timeout=timeout, limit=limits.output_bytes, on_timeout=kill)     # env=None: the docker CLI itself needs DOCKER_HOST etc.
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
    res.mode, res.image, res.command = "docker", image, argv
    return res


def _open_perms(path: Path) -> None:
    for dp, dirs, files in os.walk(path):
        for n in dirs + files:
            try:
                p = os.path.join(dp, n)
                if not os.path.islink(p):
                    os.chmod(p, os.stat(p).st_mode | 0o666 | (0o111 if os.path.isdir(p) else 0))
            except OSError:
                pass
    os.chmod(path, 0o777)
