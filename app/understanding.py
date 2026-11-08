"""AI project understanding, test discovery and recorded test runs: the parts of the web app that need more than the raw graph.

Everything here is built on data the parser/sandbox produced. The AI explanations run through the normal agent (retrieval, citations), receive the
detected facts as context, and are cached with the commit/index they were made for. With the offline mock model no explanation is generated at all
(the mock cannot reason), and the API says so instead of returning something that looks like an answer."""
from __future__ import annotations
import json
import time
from pathlib import Path

from .config import get_settings

OVERVIEW_QUESTION = (
    "Explain this project to an engineer who has never seen it. Cover, in this order and only as far as the code supports: what the project does; "
    "its main components; its entry points; the backend and frontend structure; the main execution flows (follow one concrete request or command "
    "from start to finish); the most important modules and why; how the components interact; external services and packages it depends on; "
    "and any architectural patterns you can see. Ground every claim in the retrieved code and cite snippets with [n]. If something is not "
    "visible in the code, say so instead of guessing. Do not just list file names; explain how it works.\n\nFacts detected by the parser (reliable):\n{facts}"
)


def _dir(repo_id: str, kind: str) -> Path:
    d = get_settings().data_dir / kind / repo_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- overview cache ----------------------------------------------------------------------------------------------------------------
def load_overview(repo_id: str) -> dict | None:
    p = _dir(repo_id, "overviews") / "latest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def save_overview(repo_id: str, data: dict) -> dict:
    data = {**data, "created": time.time()}
    (_dir(repo_id, "overviews") / "latest.json").write_text(json.dumps(data), encoding="utf-8")
    return data


# ---- recorded test runs ------------------------------------------------------------------------------------------------------------
def record_run(repo_id: str, run: dict, targets: list[str] | None = None, source: str = "manual") -> dict:
    """Stores a test run exactly as the sandbox returned it. Only executed runs are recorded: a run that never started (sandbox unavailable) is not history."""
    rid = f"{int(time.time() * 1000)}"
    rec = {"id": rid, "recorded_at": time.time(), "source": source, "targets": targets or [], "run": run}
    d = _dir(repo_id, "test_runs")
    (d / f"{rid}.json").write_text(json.dumps(rec), encoding="utf-8")
    for old in sorted(d.glob("*.json"))[:-40]:        # keep the 40 most recent
        old.unlink(missing_ok=True)
    return rec


def list_runs(repo_id: str, limit: int = 20, full: bool = False) -> list[dict]:
    d = _dir(repo_id, "test_runs")
    out = []
    for p in sorted(d.glob("*.json"), reverse=True)[:limit]:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not full:
            r = rec["run"]
            rec = {**rec, "run": {k: r.get(k) for k in ("status", "passed", "summary", "command", "counts", "total", "duration_ms", "framework", "sandbox", "exit_code", "executed")}}
        out.append(rec)
    return out


def discover_tests(root: Path, graph, sandbox_status: dict, framework) -> dict:
    """What tests EXIST (parsed from source) and how they would be run, before anything is executed."""
    from .intel.system_graph import _stem, _test_stem
    facts = graph.facts
    files = []
    sources = {p: _stem(p).lower() for p, f in facts.items() if not f.is_test and f.symbols}
    for p, f in sorted(facts.items()):
        if not (f.is_test or f.tests):
            continue
        imported = sorted(d for d in graph.imports_of.get(p, ()) if d in facts and not facts[d].is_test)
        named = sorted(src for src, st in sources.items() if st == _test_stem(p) and src not in imported)
        files.append({"file": p, "language": f.language, "cases": [{"name": t.get("name", ""), "line": t.get("line", 0)} for t in f.tests],
                      "covers_verified": imported, "covers_inferred": named})
    cmd = None
    if framework:
        from .quality import frameworks as fw_mod
        cmd = " ".join(fw_mod.command_for(framework, None, local_python=sandbox_status.get("mode") == "local"))
    can_run = bool(framework) and (sandbox_status.get("mode") == "local" or bool(sandbox_status.get("docker_available")))
    return {"framework": framework.name if framework else None, "language": framework.language if framework else None, "command": cmd,
            "files": files, "file_count": len(files), "case_count": sum(len(f["cases"]) for f in files),
            "can_execute": can_run, "sandbox": sandbox_status,
            "note": None if framework else "No test framework was detected for this project."}
