"""Agent-outcome metrics, added to the existing evaluation harness (retrieval metrics stay in metrics.py).

  localization       did the agent's root cause name the expected file (and function)?              needs a real LLM for the analysis
  retrieval_hit      was the expected file among the code the agent was shown? (Recall@K of the agent's own context)   works offline
  citation           share of file:line references and [n] citations that are valid; share of cases citing the expected file
  patch_success      cases whose patch the harness verified as `resolved` (or `no_regressions` for non-debug cases)
  regression_effect  of the patches that came with a regression test: how many failed before the fix and passed after

Nothing here is estimated. Every number is a count over the cases that were actually run, and every result carries a `provenance`
block: a run with the offline mock LLM measures retrieval only, and says so. Patch / root-cause numbers appear only for runs where a real
provider produced them; otherwise they are `null` (never 0, never invented).

Case file (JSONL, one case per line):
  {"id": "b1", "question": "...", "expected_file": "services/eta.py", "expected_function": "calculate_delivery_eta", "mode": "debug"}"""
from __future__ import annotations
import json
from pathlib import Path


def load_cases(path: str | Path) -> list[dict]:
    out = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("{\"_meta\""):
            d = json.loads(ln)
            if d.get("question") and d.get("expected_file"):
                out.append(d)
    return out


def provenance(llm_name: str, embedder: str, store: str = "memory") -> dict:
    mock = llm_name in ("mock", "scripted")
    return {"llm": llm_name, "embedder": embedder, "store": store, "kind": "offline-mock" if mock else "real-provider",
            "measures": "retrieval only (no root-cause analysis or patches were produced by a model)" if mock else "retrieval, root cause, citations and patches"}


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def score_case(case: dict, run: dict) -> dict:
    """One case -> flags. `run` is the agent's response dict (the same shape /debug returns)."""
    exp_file, exp_fn = case["expected_file"], case.get("expected_function") or ""
    shown = {s["file"] for s in run.get("sources", [])}
    analysis_file = (run.get("analysis") or {}).get("affected_file") or run.get("affected_file") or ""
    analysis_fn = (run.get("analysis") or {}).get("affected_function") or ""
    cites = run.get("citations") or {}
    refs = cites.get("references") or {}
    cited_files = {s["file"] for s in run.get("sources", []) if s.get("cited")}
    ver = (run.get("verification") or {}).get("status")
    reg = run.get("regression") or None
    has_analysis = bool(analysis_file)
    return {"id": case["id"],
            "retrieval_hit": exp_file in shown,
            "localized_file": (analysis_file == exp_file) if has_analysis else None,
            "localized_function": ((analysis_fn.split(".")[-1] == exp_fn.split(".")[-1]) if exp_fn else None) if has_analysis else None,
            "cited_expected": (exp_file in cited_files) if cited_files else None,
            "invalid_citations": len(cites.get("invalid", [])) + len(refs.get("invalid", [])),
            "total_citations": len(cites.get("cited", [])) + len(cites.get("invalid", [])) + sum(len(v) for v in refs.values()),
            "patch_produced": bool(run.get("patch_files")), "verification": ver,
            "patch_success": ((ver in ("resolved", "no_regressions") if case.get("mode", "debug") != "debug" else ver == "resolved") if run.get("patch_files") else None),
            "regression_present": bool(reg),
            "regression_effective": (bool(reg.get("failed_before")) and bool(reg.get("passed_after"))) if reg else None}


def aggregate(rows: list[dict], prov: dict) -> dict:
    def count(key: str, val=True) -> tuple[int, int]:
        vals = [r[key] for r in rows if r[key] is not None]
        return sum(1 for v in vals if v == val), len(vals)
    real = prov["kind"] == "real-provider"
    n_inv, n_tot = sum(r["invalid_citations"] for r in rows), sum(r["total_citations"] for r in rows)
    produced = sum(1 for r in rows if r["patch_produced"])
    ps = count("patch_success")
    ce = count("regression_effective")
    out = {"cases": len(rows), "provenance": prov,
           "retrieval_hit_rate": _rate(*count("retrieval_hit")),
           "root_cause_file_accuracy": _rate(*count("localized_file")) if real else None,
           "root_cause_function_accuracy": _rate(*count("localized_function")) if real else None,
           "citation_validity": _rate(n_tot - n_inv, n_tot) if n_tot else None,
           "expected_file_cited_rate": _rate(*count("cited_expected")),
           "patch_success_rate": _rate(ps[0], len(rows)) if real else None,
           "patches_produced": produced if real else None,
           "regression_effectiveness": _rate(*ce) if real else None,
           "regression_tests_written": sum(1 for r in rows if r["regression_present"]) if real else None}
    out["notes"] = ([] if real else ["offline/mock run: root-cause, patch and regression metrics are null because no model produced them"]) + \
                   (["no case produced a citation, so citation_validity is null"] if n_tot == 0 else [])
    return out


def to_markdown(agg: dict) -> str:
    p = agg["provenance"]
    f = lambda v: "n/a" if v is None else (f"{v:.1%}" if isinstance(v, float) else str(v))   # noqa: E731
    rows = [("Retrieval hit rate (expected file in agent context)", agg["retrieval_hit_rate"]), ("Root-cause file accuracy", agg["root_cause_file_accuracy"]),
            ("Root-cause function accuracy", agg["root_cause_function_accuracy"]), ("Citation validity", agg["citation_validity"]),
            ("Expected file cited", agg["expected_file_cited_rate"]), ("Patch success rate (verified)", agg["patch_success_rate"]),
            ("Regression-test effectiveness", agg["regression_effectiveness"])]
    out = [f"### Agent outcome metrics: {agg['cases']} case(s) · **{p['kind']}** · llm={p['llm']} · embedder={p['embedder']}", "", f"_Measures: {p['measures']}._", "",
           "| metric | value |", "|---|---|"] + [f"| {n} | {f(v)} |" for n, v in rows]
    return "\n".join(out + [""] + [f"> {x}" for x in agg["notes"]]) + "\n"
