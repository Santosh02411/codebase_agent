from __future__ import annotations
import argparse
import json
from pathlib import Path

from .agent.tools import RepoTools
from .ingest import build_index


def evaluate_retrieval(tools: RepoTools, dataset: list[dict], k: int = 5) -> dict:
    """File-level retrieval metrics: recall@k, precision@k, MRR."""
    rows, rec, prec, mrr = [], [], [], []
    for item in dataset:
        files = list(dict.fromkeys(h["file"] for h in tools.search_code(item["question"], k=k)))
        exp = set(item["expected_files"])
        hit = exp & set(files)
        r, p = len(hit) / len(exp), len(hit) / max(len(files), 1)
        rr = next((1 / (i + 1) for i, f in enumerate(files) if f in exp), 0.0)
        rec.append(r); prec.append(p); mrr.append(rr)
        rows.append({"question": item["question"], "expected": sorted(exp), "retrieved": files, "recall": r, "rr": rr})
    n = len(dataset) or 1
    return {"k": k, "n": len(dataset), "recall@k": sum(rec) / n, "precision@k": sum(prec) / n, "mrr": sum(mrr) / n, "rows": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Evaluate code retrieval on a labelled dataset")
    ap.add_argument("--repo", required=True, help="path to repository root")
    ap.add_argument("--dataset", default="eval/dataset.json")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    root = Path(a.repo).resolve()
    res = evaluate_retrieval(RepoTools(root, build_index(root)), json.loads(Path(a.dataset).read_text()), a.k)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2))
    for r in res["rows"]:
        print(("OK  " if r["recall"] == 1 else "MISS"), r["question"], "->", r["retrieved"])
