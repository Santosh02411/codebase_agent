"""A stand-in `docker` CLI for tests. It understands just enough of `docker run` to execute the command in the mounted directory,
and records every invocation so tests can assert on the exact flags the sandbox used. It enforces NOTHING: real isolation is Docker's job;
these tests verify that we ask for it correctly."""
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

SCRIPT = textwrap.dedent('''\
    #!%(python)s
    import json, os, subprocess, sys, time
    LOG = %(log)r
    args = sys.argv[1:]
    def log(rec):
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\\n")
    cmd = args[0] if args else ""
    if cmd == "info":
        print("27.0.0"); sys.exit(0)
    if cmd == "image":
        sys.exit(0 if %(image_ok)r else 1)
    if cmd in ("kill", "rm"):
        log({"cmd": cmd, "args": args[1:]}); sys.exit(0)
    if cmd != "run":
        sys.exit(1)
    flags, i, env, mount, workdir = [], 1, {}, None, "/work"
    while i < len(args):
        a = args[i]
        if a in ("--rm", "--init", "--read-only"):
            flags.append(a); i += 1
        elif a in ("--name", "--label", "--network", "--cpus", "--memory", "--memory-swap", "--pids-limit", "--ulimit", "--tmpfs", "--cap-drop", "--security-opt", "--user", "--workdir"):
            flags.append([a, args[i + 1]]); workdir = args[i + 1] if a == "--workdir" else workdir; i += 2
        elif a == "-v":
            flags.append([a, args[i + 1]]); mount = args[i + 1]; i += 2
        elif a == "-e":
            k, _, v = args[i + 1].partition("="); env[k] = v; i += 2
        else:
            break
    image, argv = args[i], args[i + 1:]
    log({"cmd": "run", "flags": flags, "env": env, "image": image, "argv": argv})
    src = mount.split(":")[0]
    penv = {"PATH": os.environ.get("PATH", ""), **{k: v for k, v in env.items()}}
    penv["PYTHONPATH"] = env.get("PYTHONPATH", "").replace("/work", src)
    penv["HOME"] = src
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    try:
        r = subprocess.run(argv, cwd=src, env=penv)
    except FileNotFoundError:
        sys.stderr.write('docker: Error response from daemon: exec: "%%s": executable file not found in $PATH\\n' %% argv[0]); sys.exit(127)
    sys.exit(r.returncode)
''')


def install(bin_dir: Path, log: Path, image_ok: bool = True) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "docker"
    exe.write_text(SCRIPT % {"python": sys.executable, "log": str(log), "image_ok": image_ok})
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def calls(log: Path) -> list[dict]:
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
