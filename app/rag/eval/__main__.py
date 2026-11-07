"""CLI:  python -m app.rag.eval <command>

  validate  --repo PATH --dataset FILE                   check that every label points at a real file/symbol
  run       --repo PATH --dataset FILE [options]          run an experiment and write JSON + Markdown under --out
  generate  --repo PATH -n 50 --out FILE                 synthesise questions with the configured LLM
  show      RESULT.json                                  print a saved result as a table
  agent     --repo PATH --cases FILE [--provider mock|gemini|openai]   run the agent on labelled bug cases and report outcome metrics
                                                         (root-cause accuracy, citation validity, patch success, regression effectiveness).
                                                         With the mock provider only retrieval is measured; the output says so.

run options:
  --preset offline                      hash embeddings × {BM25 only, vector, hybrid, hybrid + heuristic rerank}   (no network, no keys)
  --embedders hash,openai:text-embedding-3-small,gemini:gemini-embedding-001,bge:BAAI/bge-small-en-v1.5
  --rerankers heuristic,bge-reranker-base                 (with --embedders: every embedder × {vector, hybrid, hybrid + each reranker})
  --configs FILE.json                                     explicit list of configurations
  --store memory|pgvector                                 run against in-memory indexes or PostgreSQL (needs DATABASE_URL)
Models that can't be loaded (missing key / package) are reported as skipped; the rest still run."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from ...config import get_settings
from .dataset import load_dataset, validate
from .generate import generate_questions
from .report import to_markdown
from .runner import ExpConfig, preset_configs, run_experiment, save_result


def _index(repo: Path):
    from ...ingest import build_index
    from ..embedders import get_embedder
    return build_index(repo, get_embedder("hash"))


def _agent(repo: Path, a) -> int:
    """Run the agent (the /debug workflow, in a throw-away copy) over labelled cases and score the outcomes. Cost: one agent run per case."""
    from ...agent.run import run_task, run_summary
    from ...agent.tools import RepoTools
    from ...features import _sources
    from ...llm import get_llm
    from . import agent_metrics as am
    llm = get_llm(a.provider)
    cases = am.load_cases(a.cases)[: a.limit or None]
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2
    s = get_settings()
    index = _index(repo)
    tools = RepoTools(repo, index, s.test_timeout, llm=llm)
    rows = []
    for c in cases:
        print(f"\r{c['id']} ({len(rows) + 1}/{len(cases)})   ", end="", file=sys.stderr)
        try:
            st = run_task(llm, tools, s, mode=c.get("mode", "debug"), text=c["question"], allow_fix=llm.name != "mock", allow_verify=llm.name != "mock", engine="simple")
            run = {"sources": _sources(st["context"], str(st.get("analysis") or "")), "analysis": st.get("analysis") or {}, "citations": {},
                   "patch_files": st.get("patch_files") or [], "verification": st.get("verification"), "regression": st.get("regression")}
        except Exception as e:      # a failed run is a failed case, not a crash of the benchmark
            run = {"sources": [], "analysis": {}, "patch_files": [], "error": f"{type(e).__name__}: {e}"[:200]}
        rows.append(am.score_case(c, run))
    print(file=sys.stderr)
    prov = am.provenance(llm.name, "hash")
    agg = am.aggregate(rows, prov)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"agent_{prov['kind']}_{repo.name}.json"
    path.write_text(json.dumps({"aggregate": agg, "rows": rows}, indent=2))
    print(am.to_markdown(agg))
    print(f"saved: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.rag.eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--repo", required=True); v.add_argument("--dataset", required=True)
    r = sub.add_parser("run"); r.add_argument("--repo", required=True); r.add_argument("--dataset", required=True)
    r.add_argument("--preset", choices=["offline"]); r.add_argument("--embedders"); r.add_argument("--rerankers", default="")
    r.add_argument("--configs"); r.add_argument("--store", choices=["memory", "pgvector"], default="memory")
    r.add_argument("--out", default="data/experiments"); r.add_argument("--ks", default="1,3,5,10"); r.add_argument("--baseline")
    r.add_argument("--strict", action="store_true", help="fail if any label is stale")
    g = sub.add_parser("generate"); g.add_argument("--repo", required=True); g.add_argument("-n", type=int, default=30)
    g.add_argument("--out", required=True); g.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("show"); s.add_argument("result")
    ag = sub.add_parser("agent"); ag.add_argument("--repo", required=True); ag.add_argument("--cases", required=True)
    ag.add_argument("--provider", default=None); ag.add_argument("--out", default="data/experiments"); ag.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    if a.cmd == "show":
        print(to_markdown(json.loads(Path(a.result).read_text())))
        return 0
    repo = Path(a.repo).resolve()
    if a.cmd == "agent":
        return _agent(repo, a)
    if a.cmd == "validate":
        ds = load_dataset(a.dataset)
        problems = validate(ds, _index(repo))
        print(f"{ds.name}: {len(ds.questions)} questions, {len(problems)} problem(s)")
        for p in problems:
            print("  -", p)
        return 1 if problems else 0
    if a.cmd == "generate":
        from ...llm import get_llm
        ds = generate_questions(_index(repo), get_llm(), a.n, a.seed)
        ds.save(Path(a.out))
        print(f"wrote {len(ds.questions)} questions to {a.out} ({ds.meta.get('rejected_for_leaking_the_name', 0)} rejected for leaking the symbol name)")
        return 0

    ds = load_dataset(a.dataset)
    if a.configs:
        configs = [ExpConfig.from_dict(d) for d in json.loads(Path(a.configs).read_text())]
    elif a.embedders:
        configs = preset_configs([e.strip() for e in a.embedders.split(",") if e.strip()], [x.strip() for x in a.rerankers.split(",") if x.strip()])
    else:
        configs = preset_configs(["hash"], ["heuristic"])
    store = None
    if a.store == "pgvector":
        from ..pg import PgStore
        s_ = get_settings()
        if not s_.database_url:
            print("--store pgvector needs DATABASE_URL", file=sys.stderr)
            return 2
        store = PgStore(s_.database_url, s_.database_schema or None)
    res = run_experiment(repo, ds, configs, ks=tuple(int(x) for x in a.ks.split(",")), store=store, baseline=a.baseline, strict=a.strict,
                         progress=lambda p, i, n: print(f"\r{p} {i}/{n}   ", end="", file=sys.stderr))
    print(file=sys.stderr)
    path = save_result(res, Path(a.out))
    print(to_markdown(res))
    print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
