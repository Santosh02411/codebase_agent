# Execution sandbox and trust model

The platform analyses **untrusted repositories**, and its agent has tools that run code (tests, linters, scanners, patch checks). Anything that executes repository code goes through one function, `app/sandbox_exec.py: run()`. There is no other `subprocess` call on repository code in the application (audit: `grep -rn subprocess app/` finds only `sandbox_exec.py`, `gitops.py` and the initial clone, all hardened as below).

## What a run looks like (default, `SANDBOX_MODE=docker`)

One throw-away container per test run or analysis:

| Control | Flag / mechanism |
|---|---|
| No network | `--network none` (the only exceptions are two opt-in, read-only, non-executing steps: dependency audits and dependency install, see below) |
| CPU / memory / processes | `--cpus`, `--memory` = `--memory-swap` (no swapping past the limit), `--pids-limit`, `--ulimit nofile`, `core=0` |
| Wall-clock timeout | enforced **from outside** (`docker kill` + `docker rm -f`), independent of anything the code does |
| Read-only root filesystem | `--read-only`; writable scratch only in RAM-backed `--tmpfs` (`/tmp`: `nosuid,nodev`, `noexec` except for toolchains that compile there: go, rust, java, node; `/home/sandbox`) |
| No privileges | `--cap-drop ALL`, `--security-opt no-new-privileges`, non-root user (never uid 0, even if the server runs as root), default seccomp/AppArmor profiles, no `--privileged`, no Docker socket |
| Only the project is visible | one bind mount: a **throw-away copy** of the project (`rw`) or the project itself **read-only** for pure analysis; symlinks are copied as links, never followed |
| No host secrets | the container gets an explicit environment only (`PATH`, `HOME`, `TMPDIR`, `PYTHONPATH`…): no `OPENAI_API_KEY`, `GITHUB_TOKEN` or anything else from the server |
| Bounded output | stdout+stderr capped (`SANDBOX_OUTPUT_LIMIT`), drained so a chatty process cannot block or exhaust memory |

If Docker (or the image) is missing, **nothing runs** and every tool reports `sandbox_unavailable` with how to fix it; the run is shown as *not verified*, never as passed. An unrecognised `SANDBOX_MODE` falls back to `docker`, never to the host.

`SANDBOX_MODE=local` runs on the host with rlimits and its own process group. It is **not isolation** and is labelled as such in the UI (red badge) and in `/health`. It exists for a developer's own machine and for the project's test-suite.

## Images

`scripts/build_sandbox.sh [python node go rust java]` builds `codebase-agent/sandbox-<lang>` from `sandbox/Dockerfile.*` (pytest, pytest-cov, coverage, ruff, pylint, mypy, bandit, semgrep, pip-audit; eslint/jest/vitest/mocha; Go; Rust + clippy; Maven/Temurin). Semgrep uses the offline rule pack in `sandbox/semgrep-rules/` (the network-less container cannot reach the registry). Override images with `SANDBOX_IMAGE_<LANG>`.

## Dependencies

Tests need the project's dependencies, and the run is offline. `SANDBOX_INSTALL_DEPS=true` adds a **separate** networked container that installs them first, without running project code: `pip --only-binary=:all:` (no sdist builds), `npm ci --ignore-scripts`, `go mod download`, `cargo fetch`, `mvn dependency:go-offline`. Off by default.

`SANDBOX_AUDIT_NETWORK=true` lets `pip-audit` (`--disable-pip --no-deps`: reads pinned requirements, builds nothing) and `npm audit --package-lock-only` reach their advisory databases, on a read-only mount. Off by default: those two analyzers report "skipped" with the reason.

## Everything else that touches an untrusted repository

* **git**: a repository's `.git/config`, `.gitattributes` and hooks can name programs git will run. Every git call carries `-c core.fsmonitor=false -c core.hooksPath=/dev/null -c core.sshCommand=false -c credential.helper= …`, a scrubbed environment (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL=/dev/null`), and each project's `.git/config` is **rewritten once** keeping only inert settings (https/ssh remote URLs, branch tracking): filters, aliases, `url.*.insteadOf` (which could redirect a push, and your token, elsewhere), credential helpers and includes are dropped; hooks are deleted; a `.git` *file* pointing elsewhere is removed. Clones use `--no-recurse-submodules` and no `file`/`ext` transports.
* **credentials**: used only at the moment an approved action runs, sent as an HTTP header (never in a URL, config file, record or log), and only to the GitHub repository the project was added from: a rewritten remote is refused.
* **parsing** (tree-sitter, `ast.parse`, JSON/TOML/YAML validation) reads text and never executes it.
* **secrets in files**: `.env`, `*.pem`, `id_rsa`… are never read by the agent or committed; literal secret values are masked in everything the model sees.

## Honest limits

* A container shares the host kernel. A kernel or runtime escape would defeat all of the above. For a public service run Docker rootless or use gVisor/Kata/Firecracker (`--runtime=runsc`), and run the sandbox on a **separate machine or VM** from the web app.
* The web app must be able to start containers. Mounting `/var/run/docker.sock` into the app container gives it root-equivalent power over that host. Prefer rootless Docker, a socket proxy that allows only `run/kill/rm/image inspect`, or a remote `DOCKER_HOST`.
* **Capacity.** CPU/memory limits bound one run. Server-wide, at most `SANDBOX_MAX_CONCURRENT` (default 2) containers run at once; others queue for up to `SANDBOX_QUEUE_TIMEOUT` seconds and are then refused as *busy* (reported as not verified, never as a pass). `RATE_LIMIT_PER_MINUTE` (default 0 = off; try 30 for a public service) limits, per client address, the POST endpoints that start agents or run code. Both are in-memory and per process: for several workers or machines put a real gateway / queue in front. There are no user accounts or quotas.
* No network does not stop a process from burning its CPU quota until the timeout; that is bounded, not prevented.
* This was tested with a stand-in `docker` executable (`tests/fakedocker.py`) that checks the exact flags and the timeout / cleanup / output paths. **It has not been run against a real Docker daemon**: build the images and run `SANDBOX_MODE=docker` once before trusting it.
