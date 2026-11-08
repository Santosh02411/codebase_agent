"""Patch proposals: stored, reviewable, applied only on explicit approval, checked after applying, revertible, repairable.

A proposal holds the exact before/after text of every file (what the diff editor shows), the unified diff, and the hashes of the files
it was built against. Nothing in here writes to the repository except `apply` / `revert`, which are reached only through approval."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import lint, sandbox, verify
from .patchset import FileChange, PatchError, PatchSet, PatchSpec, StaleError, apply_patchset, build_patchset, revert_patchset

MAX_RECORD_BYTES = 6_000_000
_ID = re.compile(r"^[a-f0-9]{8,32}$")


class ApprovalRequired(PatchError):
    """apply() was called without the user's explicit approval."""


class PatchStore:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.base.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, pid: str) -> Path:
        if not _ID.match(pid or ""):
            raise KeyError(pid)
        return self.base / f"{pid}.json"

    def get(self, pid: str) -> dict:
        p = self._path(pid)
        if not p.is_file():
            raise KeyError(pid)
        return json.loads(p.read_text())

    def save(self, rec: dict) -> dict:
        rec["updated"] = time.time()
        data = json.dumps(rec)
        with self._lock:
            tmp = self._path(rec["id"]).with_suffix(".tmp")
            tmp.write_text(data)
            tmp.replace(self._path(rec["id"]))
        return rec

    def list(self, repo_id: str | None = None) -> list[dict]:
        out = []
        for f in sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                rec = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if repo_id is None or rec.get("repo_id") == repo_id:
                out.append(summary(rec))
        return out[:200]

    def create(self, repo_id: str, root: Path, spec: dict | PatchSpec, *, title: str = "", explanation: str = "", origin: dict | None = None,
               parent_id: str | None = None, verification: dict | None = None, fuzzy: bool = True) -> dict:
        spec = spec if isinstance(spec, PatchSpec) else PatchSpec.from_dict(spec)
        ps = build_patchset(root, spec, fuzzy=fuzzy)
        files = [{"path": c.path, "op": c.op, "old": c.old, "new": c.new, "diff": c.diff, "additions": c.additions, "deletions": c.deletions,
                  "fuzzy": c.fuzzy, "notes": c.notes, "base_hash": c.base_hash, "eol": c.eol, "bom": c.bom} for c in ps.changes]
        rec = {"id": uuid.uuid4().hex[:12], "repo_id": repo_id, "title": (title or _title(ps))[:120], "explanation": explanation, "created": time.time(),
               "status": "proposed", "origin": origin or {}, "parent_id": parent_id, "spec": spec.to_dict(), "files": files, "diff": ps.diff,
               "stats": ps.stats(), "verification": verification, "checks": None, "applied": None, "history": [{"ts": time.time(), "event": "proposed"}]}
        if len(json.dumps(rec)) > MAX_RECORD_BYTES:
            raise PatchError("this patch is too large to review (over 6 MB of before/after text); split it into smaller patches")
        return self.save(rec)

    @staticmethod
    def patchset(rec: dict) -> PatchSet:
        return PatchSet([FileChange(f["path"], f["op"], f["old"], f["new"], f["base_hash"], f.get("eol", "\n"), f.get("bom", False), f.get("fuzzy", False),
                                    f.get("notes", []), f["diff"], f["additions"], f["deletions"]) for f in rec["files"]])


def _title(ps: PatchSet) -> str:
    s = ps.stats()
    names = ", ".join(c.path for c in ps.changes[:2]) + ("…" if len(ps.changes) > 2 else "")
    return f"{s['files']} file{'s' * (s['files'] != 1)}: {names}"


def summary(rec: dict) -> dict:
    """The record without the file texts (those are fetched per file for the diff editor)."""
    return {k: rec.get(k) for k in ("id", "repo_id", "title", "explanation", "created", "updated", "status", "origin", "parent_id", "stats", "verification",
                                    "checks", "history", "diff")} | {
        "files": [{k: f[k] for k in ("path", "op", "additions", "deletions", "fuzzy", "notes")} for f in rec["files"]],
        "applied_files": (rec.get("applied") or {}).get("files", [])}


def file_versions(rec: dict, path: str) -> dict:
    f = next((x for x in rec["files"] if x["path"] == path), None)
    if f is None:
        raise KeyError(path)
    return {"path": path, "op": f["op"], "original": f["old"] or "", "modified": f["new"] or "", "diff": f["diff"]}


# ---- apply / checks / revert -----------------------------------------------------------------------------------------
def run_checks(root: Path, changed: list[str], deleted: list[str], baseline: dict | None, timeout: int, intent: str = "change") -> dict:
    """Tests + lint on a copy of the repository as it is NOW (after the patch was applied), judged against the pre-patch baseline."""
    work = sandbox.copy_repo(root)
    try:
        tests = sandbox.run_tests(work, timeout)
        lint_after = lint.run_linter(work, changed or None, 60) if changed else {"issues": [], "counts": {"total": 0, "errors": 0, "warnings": 0, "blocking": 0},
                                                                                  "tool": "none", "status": "clean", "summary": "nothing to lint"}
    finally:
        sandbox.cleanup(work)
    base = baseline or {}
    new_lint = lint.new_issues(base.get("lint"), lint_after)
    verdict = verify.judge(base.get("tests"), tests, lint_new=new_lint, intent=intent)
    ok = verdict["status"] in ("resolved", "partial", "no_regressions")
    status = "passed" if ok else "failed" if verdict["status"] == "not_resolved" else "inconclusive"
    return {"status": status, "tests_before": base.get("tests"), "tests_after": tests, "lint_before": base.get("lint"), "lint_after": lint_after,
            "lint_new": new_lint, "verdict": verdict, "ran_at": time.time()}


def apply(store: PatchStore, rec: dict, root: Path, *, approved: bool, files: list[str] | None = None, checks: bool = True,
          timeout: int = 120) -> dict:
    if approved is not True:
        raise ApprovalRequired("applying a patch needs the user's explicit approval (approved: true)")
    if rec["status"] != "proposed":
        raise PatchError(f"this patch is {rec['status']}; only a proposed patch can be applied")
    ps = store.patchset(rec)
    only = set(files) if files else None
    if only and not only <= set(ps.paths):
        raise PatchError(f"not in this patch: {', '.join(sorted(only - set(ps.paths)))}")
    selected = [c for c in ps.changes if only is None or c.path in only]
    baseline = None
    if checks:                                     # baseline BEFORE touching the repository, so the verdict compares like with like
        v = rec.get("verification") or {}
        existing = [c.path for c in selected if c.op != "create"]
        baseline = v.get("baseline") if v.get("baseline", {}).get("tests") and v.get("baseline", {}).get("lint") else verify.baseline_checks(root, existing, timeout)
    undo = apply_patchset(root, ps, only)
    rec["status"] = "applied"
    rec["applied"] = {"files": [c.path for c in selected], "at": time.time(), "undo": undo}
    rec["history"].append({"ts": time.time(), "event": "applied", "files": [c.path for c in selected]})
    if checks:
        rec["checks"] = run_checks(root, [c.path for c in selected if c.op != "delete"], [c.path for c in selected if c.op == "delete"], baseline, timeout,
                                   intent=(rec.get("origin") or {}).get("intent") or "change")
        rec["history"].append({"ts": time.time(), "event": f"checks {rec['checks']['status']}"})
    return store.save(rec)


def revert(store: PatchStore, rec: dict, root: Path, force: bool = False) -> dict:
    if rec["status"] != "applied":
        raise PatchError(f"this patch is {rec['status']}; only an applied patch can be reverted")
    revert_patchset(root, rec["applied"]["undo"], force)
    rec["status"] = "reverted"
    rec["history"].append({"ts": time.time(), "event": "reverted"})
    return store.save(rec)


def reject(store: PatchStore, rec: dict) -> dict:
    if rec["status"] != "proposed":
        raise PatchError(f"this patch is {rec['status']}")
    rec["status"] = "rejected"
    rec["history"].append({"ts": time.time(), "event": "rejected"})
    return store.save(rec)


def repair_request(rec: dict) -> str:
    """The briefing the agent gets to correct an applied patch whose checks failed."""
    c = rec.get("checks") or {}
    v = c.get("verdict") or {}
    t = c.get("tests_after") or {}
    lines = [f"A change was applied to the repository and its automatic checks FAILED. Diagnose why and produce a corrective change relative to the CURRENT code "
             f"(the patch below is already applied).", "", f"Original request: {(rec.get('origin') or {}).get('question', '')[:1500]}",
             f"Why it failed: {v.get('summary', 'checks failed')}"]
    if v.get("new_failures"):
        lines.append("Tests that now fail: " + ", ".join(v["new_failures"][:8]))
    if t.get("output") and t.get("status") not in ("passed",):
        lines += ["", "Test output:", t["output"][-1800:]]
    blocking = [i for i in c.get("lint_new", []) if i.get("blocking")]
    if blocking:
        lines += ["", "New blocking lint errors:"] + [f"- {i['file']}:{i['line']} {i['code']} {i['message']}" for i in blocking[:6]]
    lines += ["", "The applied patch:", rec.get("diff", "")[:3500]]
    return "\n".join(lines)
