from __future__ import annotations

COLUMNS = [("mrr", "MRR"), ("ndcg@10", "NDCG@10"), ("recall@1", "R@1"), ("recall@5", "R@5"), ("recall@10", "R@10"), ("precision@5", "P@5"),
           ("context_precision", "CtxPrec"), ("context_recall", "CtxRecall")]


def _col(result: dict, metric: str) -> str:
    ks = result["ks"]
    return metric if metric in ("mrr", "context_precision", "context_recall") or int(metric.split("@")[1]) in ks else ""


def to_markdown(result: dict, level: str = "symbol") -> str:
    cols = [(m, h) for m, h in COLUMNS if _col(result, m)]
    ok = [c for c in result["configs"] if c["status"] == "ok"]
    best = {m: max((c["summary"][level][m]["mean"] for c in ok), default=None) for m, _ in cols}
    sig = result.get("comparisons", {})
    lines = [f"## {result['dataset']['name']} — {result['dataset']['questions']} questions · {result['store']} · {level}-level labels",
             "", "| config | " + " | ".join(h for _, h in cols) + " | p50 ms |", "|---|" + "---|" * (len(cols) + 1)]
    for c in result["configs"]:
        name = c["config"]["name"]
        if c["status"] != "ok":
            lines.append(f"| {name} | " + f"*{c['status']}: {c.get('reason', '')[:70]}* |" + " |" * len(cols))
            continue
        cells = []
        for m, _ in cols:
            v = c["summary"][level][m]["mean"]
            s = f"{v:.3f}"
            cells.append(f"**{s}**" if best[m] is not None and abs(v - best[m]) < 1e-9 else s)
        mark = ""
        cmp = sig.get(name, {}).get("mrr")
        if cmp and cmp["p"] < 0.05:
            mark = " ▲" if cmp["delta"] > 0 else " ▼"
        lines.append(f"| {name}{mark} | " + " | ".join(cells) + f" | {c['latency_ms']['p50']} |")
    lines += ["", f"Baseline: `{result.get('baseline')}`. ▲/▼ = MRR differs from the baseline with p < 0.05 (paired bootstrap over questions). Bold = best in column.",
              "Metric definitions: see app/rag/eval/metrics.py. Context metrics are computed on the token-budgeted context actually given to the LLM."]
    if result.get("indexes"):
        lines += ["", "| embedding model | dim | chunks | index time | API calls | tokens |", "|---|---|---|---|---|---|"]
        for spec, i in result["indexes"].items():
            lines.append(f"| {i['embedder']} | {i['dim']} | {i['chunks']} | {i['seconds']} s | {i['embed_calls']} | {i['embed_tokens'] or '–'} |")
    for spec, why in result.get("skipped_embedders", {}).items():
        lines.append(f"\n⚠ skipped `{spec}`: {why}")
    if result.get("label_problems"):
        lines.append(f"\n⚠ {len(result['label_problems'])} label problem(s): " + "; ".join(result["label_problems"][:3]))
    return "\n".join(lines) + "\n"


def to_csv(result: dict, level: str = "symbol") -> str:
    metrics = [m for m, _ in COLUMNS if _col(result, m)]
    rows = ["config,embedder,mode,reranker," + ",".join(metrics) + ",p50_ms,status"]
    for c in result["configs"]:
        cfg = c["config"]
        vals = [f"{c['summary'][level][m]['mean']:.4f}" for m in metrics] if c["status"] == "ok" else [""] * len(metrics)
        rows.append(",".join([cfg["name"].replace(",", ";"), cfg["embedder"], cfg["mode"], cfg["reranker"], *vals,
                              str(c.get("latency_ms", {}).get("p50", "")), c["status"]]))
    return "\n".join(rows) + "\n"
