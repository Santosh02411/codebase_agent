"""One quality run: tests (+coverage), every applicable analyzer, maintainability metrics, then the score. Executed as a background job so the UI can poll progress.
Tests run on a throw-away copy of the project; analyzers read the project through a read-only mount. Both inside the sandbox."""
from __future__ import annotations
import json
import threading
import time
import uuid
from pathlib import Path

from .. import sandbox, sandbox_exec
from . import analyzers, frameworks, score

SEV_ORDER = ["critical", "high", "medium", "low", "info"]


def summarize_findings(results: dict[str, dict]) -> dict:
    by_cat: dict[str, dict[str, int]] = {}
    for r in results.values():
        for f in r["findings"]:
            c = by_cat.setdefault(f["category"], {})
            c[f["severity"]] = c.get(f["severity"], 0) + 1
    return {cat: {"total": sum(v.values()), **{s: v.get(s, 0) for s in SEV_ORDER}} for cat, v in by_cat.items()}


def run_quality(root: Path, *, tools: list[str] | None = None, coverage: bool = True, test_timeout: int = 300, progress=None) -> dict:
    say = progress or (lambda _m: None)
    t0 = time.time()
    notes: list[str] = []
    fws = frameworks.detect_all(root)
    tests: list[dict] = []
    cov = None
    if not fws:
        notes.append("No test framework was detected (looked for pytest, Jest/Vitest/Mocha, go.mod, Cargo.toml, pom.xml, build.gradle).")
    for fw in fws[:3]:
        say(f"Running {fw.name} tests{' with coverage' if coverage else ''}…")
        work = sandbox.copy_repo(root)
        try:
            res = sandbox.run_tests(work, test_timeout, framework=fw, coverage=coverage)
        finally:
            sandbox.cleanup(work)
        tests.append(res)
        if res.get("coverage") and cov is None:
            cov = res["coverage"]
        elif coverage and res["status"] in ("passed", "failed") and not res.get("coverage"):
            notes.append(f"Coverage is not collected for {fw.name} projects." if not res.get("coverage_supported") else f"{fw.name} ran but produced no coverage data (is pytest-cov / the coverage reporter installed in the sandbox image?).")
        if res["status"] == "sandbox_unavailable":
            notes.append(res["summary"])
            break
    wanted = tools or analyzers.applicable(root)
    results: dict[str, dict] = {}
    for name in wanted:
        if name not in analyzers.ANALYZERS:
            notes.append(f"unknown analyzer {name!r} ignored")
            continue
        say(f"Running {analyzers.ANALYZERS[name].label or name}…")
        try:
            results[name] = analyzers.run(root, name).to_dict()
        except Exception as e:  # noqa: BLE001 - one broken tool must not cost the whole report
            results[name] = analyzers.AnalyzerResult(name, analyzers.ANALYZERS[name].category, "error", [], f"{type(e).__name__}: {e}"[:200]).to_dict()
    say("Measuring maintainability and scoring…")
    maint = score.maintainability(root)
    primary = next((t for t in tests if t["status"] in ("passed", "failed")), tests[0] if tests else None)
    sc = score.compute(tests=primary, coverage=cov, analyzers=results, loc=score.count_lines(root), maint=maint)
    for r in results.values():
        if r["status"] in ("unavailable", "skipped", "error", "timeout"):
            notes.append(f"{r['tool']}: {r['status']} — {r['summary']}")
    return {"id": uuid.uuid4().hex[:12], "created": time.time(), "duration_s": round(time.time() - t0, 1), "sandbox": sandbox_exec.status(),
            "frameworks": [f.describe() for f in fws], "tests": tests, "coverage": cov, "analyzers": results, "findings": summarize_findings(results),
            "maintainability": maint, "score": sc, "notes": notes}


class QualityJobs:
    """Background runs with pollable progress; finished reports are kept on disk per repository."""

    def __init__(self, base: Path) -> None:
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, repo_id: str, root: Path, **kw) -> dict:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "repo_id": repo_id, "status": "running", "progress": [], "started": time.time(), "report": None, "error": None}
        with self._lock:
            self.jobs[jid] = job

        def work():
            try:
                rep = run_quality(root, progress=lambda m: job["progress"].append({"ts": time.time(), "message": m}), **kw)
                rep["repo_id"] = repo_id
                d = self.base / repo_id
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{rep['id']}.json").write_text(json.dumps(rep))
                job["report"], job["status"] = rep, "done"
            except Exception as e:  # noqa: BLE001
                job["error"], job["status"] = f"{type(e).__name__}: {e}"[:300], "error"
        threading.Thread(target=work, daemon=True).start()
        return job

    def get(self, jid: str) -> dict:
        with self._lock:
            return self.jobs[jid]

    def latest(self, repo_id: str) -> dict | None:
        d = self.base / repo_id
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
        return json.loads(files[0].read_text()) if files else None

    def history(self, repo_id: str, limit: int = 20) -> list[dict]:
        d = self.base / repo_id
        out = []
        for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit] if d.is_dir() else []:
            try:
                r = json.loads(f.read_text())
                out.append({"id": r["id"], "created": r["created"], "score": r["score"]["overall"], "grade": r["score"]["grade"]})
            except (OSError, ValueError, KeyError):
                continue
        return out
