"""Experiment runner: build one index per embedding model, run every retrieval configuration over a labelled dataset, and
report metrics with confidence intervals, latency and embedding cost."""
from __future__ import annotations
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ...ingest import build_index
from ..context import build_pack
from ..embedders import EmbeddingError, get_embedder, parse_spec
from ..rerank import RerankError
from ..retriever import RetrievalConfig
from .dataset import Dataset, validate
from .metrics import Ref, bootstrap_ci, context_metrics, mean, paired_bootstrap_p, retrieval_metrics

Progress = Callable[[str, int, int], None]
LEVELS = ("symbol", "file")


@dataclass
class ExpConfig:
    name: str
    embedder: str = "hash"          # spec: hash | openai:text-embedding-3-small[:dim] | gemini:gemini-embedding-001[:dim] | bge:<model> | fastembed:<model>
    mode: str = "hybrid"            # hybrid | vector | keyword
    reranker: str = "none"          # none | heuristic | bge-reranker-base | cross-encoder:<model> | llm
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    candidates: int = 50            # per search leg
    pool: int = 30                  # fused candidates given to the reranker
    context_k: int = 8              # top chunks packed into the LLM context
    context_budget: int = 6000      # tokens

    @classmethod
    def from_dict(cls, d: dict) -> "ExpConfig":
        names = set(cls.__dataclass_fields__)
        unknown = set(d) - names
        if unknown:
            raise ValueError(f"unknown config field(s): {sorted(unknown)}")
        return cls(**d)


def preset_configs(embedders: list[str], rerankers: list[str]) -> list[ExpConfig]:
    """Every embedder × {vector, hybrid, hybrid + each reranker}, plus one embedder-independent BM25-only baseline."""
    out = [ExpConfig(f"bm25-only", embedder=embedders[0], mode="keyword")]
    for emb in embedders:
        provider, model, dim = parse_spec(emb)
        tag = "hash" if provider == "hash" else re.sub(r"[^A-Za-z0-9.:\-]+", "-", model.split("/")[-1] + (f":{dim}" if dim else ""))[:32]
        out.append(ExpConfig(f"{tag} · vector", embedder=emb, mode="vector"))
        out.append(ExpConfig(f"{tag} · hybrid", embedder=emb, mode="hybrid"))
        for rr in rerankers:
            out.append(ExpConfig(f"{tag} · hybrid + {rr.split(':')[-1]}", embedder=emb, mode="hybrid", reranker=rr))
    return out


def _pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))] if s else 0.0


def _usage(e) -> dict:
    return dict(e.usage)


def run_experiment(root: Path, dataset: Dataset, configs: list[ExpConfig], *, ks=(1, 3, 5, 10), store=None, repo_id: str | None = None,
                   baseline: str | None = None, progress: Progress | None = None, llm=None, strict: bool = False, keep: bool = False) -> dict:
    """`store` = a PgStore to run the same experiment against PostgreSQL/pgvector instead of in-memory indexes."""
    t_start = time.time()
    progress = progress or (lambda *_: None)
    ks = tuple(sorted(set(ks)))
    maxk = max(ks)
    rid = repo_id or f"eval-{re.sub(r'[^a-z0-9]+', '-', dataset.name.lower())}"

    # ---- one index per embedding model -------------------------------------------------------------------------
    indexes: dict[str, object] = {}
    index_info: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    embedders: dict[str, object] = {}
    specs = list(dict.fromkeys(c.embedder for c in configs))
    first_built = False
    for n, spec in enumerate(specs):
        progress("indexing", n, len(specs))
        try:
            emb = get_embedder(spec)
            u0, t0 = _usage(emb), time.time()
            if store is None:
                idx = build_index(root, emb)
            elif not first_built:
                idx = build_index(root, emb, None, None, pg=store, repo_id=rid, repo_info=(rid, str(root)))
            else:
                store.ensure_embeddings(rid, emb)       # same parsed chunks, new model: no re-parse
                idx = store.load_index(rid, emb)
            first_built = first_built or store is not None
        except (EmbeddingError, ImportError, ValueError) as e:
            skipped[spec] = f"{type(e).__name__}: {e}"[:300]
            continue
        u1 = _usage(emb)
        embedders[spec], indexes[spec] = emb, idx
        index_info[spec] = {"embedder": emb.name, "dim": int(emb.dim or 0), "chunks": len(idx.chunks), "seconds": round(time.time() - t0, 2),
                            "embed_calls": u1["calls"] - u0["calls"], "embed_texts": u1["texts"] - u0["texts"], "embed_tokens": u1["tokens"] - u0["tokens"]}
    any_index = next(iter(indexes.values()), None)
    problems = validate(dataset, any_index) if any_index is not None else ["no index could be built"]
    if problems and strict:
        raise ValueError("dataset labels do not match the repository:\n  " + "\n  ".join(problems[:20]))

    # ---- run every configuration ---------------------------------------------------------------------------------
    results = []
    for ci, cfg in enumerate(configs):
        progress("running", ci, len(configs))
        entry: dict = {"config": asdict(cfg)}
        if cfg.embedder in skipped:
            results.append({**entry, "status": "skipped", "reason": skipped[cfg.embedder]})
            continue
        idx, emb = indexes[cfg.embedder], embedders[cfg.embedder]
        try:
            retr = idx.retriever(reranker=cfg.reranker, config=RetrievalConfig(cfg.mode, cfg.rrf_k, cfg.vector_weight, cfg.keyword_weight, cfg.candidates, cfg.pool),
                                 llm=llm)
        except (RerankError, ImportError) as e:
            results.append({**entry, "status": "skipped", "reason": f"{type(e).__name__}: {e}"[:300]})
            continue
        u0 = _usage(emb)
        rows, lat = [], []
        for q in dataset.questions:
            t0 = time.perf_counter()
            try:
                r = retr.retrieve(q.question, k=maxk, pool=max(cfg.pool, maxk), candidates=cfg.candidates)
            except (EmbeddingError, RerankError) as e:
                results.append({**entry, "status": "failed", "reason": f"{type(e).__name__}: {e}"[:300]})
                rows = None
                break
            lat.append((time.perf_counter() - t0) * 1000)
            refs = [Ref(h.chunk.file, h.chunk.qualname, h.chunk.start, h.chunk.end) for h in r.hits]
            dicts = [{"id": h.chunk.id, "file": h.chunk.file, "qualname": h.chunk.qualname, "start": h.chunk.start, "end": h.chunk.end,
                      "kind": h.chunk.kind, "route": h.chunk.route, "via": "search", "text": h.chunk.text} for h in r.hits[:cfg.context_k]]
            pack = build_pack(dicts, cfg.context_budget)
            ctx_refs = [Ref(i.chunk["file"], i.chunk["qualname"], i.chunk["start"], i.chunk["end"]) for i in pack.items]
            m = {lv: {**retrieval_metrics(refs, q.relevant, ks, lv), **context_metrics(ctx_refs, q.relevant, lv)} for lv in LEVELS}
            rel0 = next((i + 1 for i, rf in enumerate(refs) if any(rf.file == e.file and (e.symbol is None or rf.qualname == e.symbol) for e in q.relevant)), None)
            rows.append({"id": q.id, "question": q.question, "tags": q.tags, "first_relevant_rank": rel0, "context_tokens": pack.tokens,
                         "expected": [f"{e.file}::{e.symbol}" if e.symbol else e.file for e in q.relevant],
                         "retrieved": [f"{rf.file}::{rf.qualname}" for rf in refs[:10]], "metrics": m})
        if rows is None:
            continue
        u1 = _usage(emb)
        summary = {}
        for lv in LEVELS:
            summary[lv] = {}
            for metric in rows[0]["metrics"][lv] if rows else []:
                xs = [r["metrics"][lv][metric] for r in rows]
                lo, hi = bootstrap_ci(xs)
                summary[lv][metric] = {"mean": mean(xs), "lo": lo, "hi": hi}
        results.append({**entry, "status": "ok", "summary": summary, "n": len(rows),
                        "latency_ms": {"mean": round(mean(lat), 2), "p50": round(_pct(lat, .5), 2), "p95": round(_pct(lat, .95), 2)},
                        "query_cost": {"embed_calls": u1["calls"] - u0["calls"], "embed_tokens": u1["tokens"] - u0["tokens"]},
                        "context_tokens_mean": round(mean([r["context_tokens"] for r in rows]), 1), "per_question": rows})

    # ---- paired significance against the baseline -------------------------------------------------------------------
    ok = [r for r in results if r["status"] == "ok"]
    base_name = baseline or (ok[0]["config"]["name"] if ok else None)
    base = next((r for r in ok if r["config"]["name"] == base_name), None)
    comparisons: dict = {}
    if base:
        for r in ok:
            if r is base:
                continue
            comparisons[r["config"]["name"]] = {
                metric: {"delta": r["summary"]["symbol"][metric]["mean"] - base["summary"]["symbol"][metric]["mean"],
                         "p": paired_bootstrap_p([x["metrics"]["symbol"][metric] for x in r["per_question"]],
                                                 [x["metrics"]["symbol"][metric] for x in base["per_question"]])}
                for metric in ("mrr", f"ndcg@{ks[-1]}", f"recall@{ks[min(2, len(ks) - 1)]}")}
    if store is not None and not keep:
        store.delete_repo(rid)
    rid_out = time.strftime("%Y%m%d-%H%M%S") + "-" + re.sub(r"[^a-z0-9]+", "-", dataset.name.lower())
    return {"id": rid_out, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": {"name": dataset.name, "questions": len(dataset.questions)},
            "repo": str(root), "store": "pgvector" if store is not None else "memory", "ks": list(ks), "baseline": base_name,
            "indexes": index_info, "skipped_embedders": skipped, "label_problems": problems, "configs": results, "comparisons": comparisons,
            "elapsed_s": round(time.time() - t_start, 1)}


def save_result(result: dict, out_dir: Path) -> Path:
    from .report import to_markdown
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{result['id']}.json"
    p.write_text(json.dumps(result, indent=1))
    (out_dir / f"{result['id']}.md").write_text(to_markdown(result))
    return p
