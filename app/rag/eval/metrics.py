"""Retrieval and context metrics.

A retrieved chunk is *relevant* when it matches an expected item: same file and (if the item names a symbol) the same symbol,
or (if it names a line range) an overlapping range. Level "file" ignores symbols and line ranges.

  Recall@K     fraction of expected items found among the top-K chunks
  Precision@K  fraction of the top-K chunks that match any expected item
  Hit@K        1 if at least one expected item is found in the top-K
  MRR          1 / rank of the first relevant chunk (0 if none)
  NDCG@K       DCG with binary gain, counting each expected item once (a second chunk of an already-found item gains nothing),
               normalised by the ideal ordering of min(#items, K) hits

  Context Precision  RAGAS definition applied to the chunks actually placed in the LLM context, in order:
                     Σ_k (precision@k · relevant_k) / (number of relevant chunks)   -> rewards putting relevant code first
  Context Recall     fraction of expected items present anywhere in the packed context (after token-budget trimming)"""
from __future__ import annotations
import math
import random
from typing import NamedTuple, Sequence

from .dataset import Expected


class Ref(NamedTuple):
    file: str
    qualname: str
    start: int
    end: int


def matches(r: Ref, e: Expected, level: str = "symbol") -> bool:
    if r.file != e.file:
        return False
    if level == "file" or (e.symbol is None and e.lines is None):
        return True
    if e.symbol is not None:
        return r.qualname == e.symbol
    return r.start <= e.lines[1] and r.end >= e.lines[0]


def relevance(refs: Sequence[Ref], items: Sequence[Expected], level: str = "symbol") -> tuple[list[bool], list[int]]:
    """(is the chunk relevant?, gain) per rank. gain is 1 only the first time an expected item is found."""
    found: set[int] = set()
    rel, gain = [], []
    for r in refs:
        hit = [i for i, e in enumerate(items) if matches(r, e, level)]
        rel.append(bool(hit))
        new = [i for i in hit if i not in found]
        found.update(new)
        gain.append(1 if new else 0)
    return rel, gain


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def retrieval_metrics(refs: Sequence[Ref], items: Sequence[Expected], ks: Sequence[int], level: str = "symbol") -> dict[str, float]:
    rel, gain = relevance(refs, items, level)
    n_items = max(len(items), 1)
    out: dict[str, float] = {}
    for k in ks:
        top_rel, top_gain = rel[:k], gain[:k]
        out[f"recall@{k}"] = sum(top_gain) / n_items
        out[f"precision@{k}"] = sum(top_rel) / k
        out[f"hit@{k}"] = 1.0 if any(top_rel) else 0.0
        ideal = _dcg([1] * min(len(items), k))
        out[f"ndcg@{k}"] = _dcg(top_gain) / ideal if ideal else 0.0
    first = next((i for i, r in enumerate(rel) if r), None)
    out["mrr"] = 1.0 / (first + 1) if first is not None else 0.0
    return out


def context_metrics(refs: Sequence[Ref], items: Sequence[Expected], level: str = "symbol") -> dict[str, float]:
    rel, gain = relevance(refs, items, level)
    n_rel = sum(rel)
    if n_rel:
        hits, total = 0, 0.0
        for k, r in enumerate(rel, 1):
            if r:
                hits += 1
                total += hits / k
        precision = total / n_rel
    else:
        precision = 0.0
    return {"context_precision": precision, "context_recall": sum(gain) / max(len(items), 1)}


# ---- statistics -----------------------------------------------------------------------------------------------
def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(xs: Sequence[float], n: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of the mean (deterministic for a given seed)."""
    if len(xs) < 2:
        m = mean(xs)
        return m, m
    rng = random.Random(seed)
    k = len(xs)
    means = sorted(mean([xs[rng.randrange(k)] for _ in range(k)]) for _ in range(n))
    return means[int(n * alpha / 2)], means[min(n - 1, int(n * (1 - alpha / 2)))]


def paired_bootstrap_p(a: Sequence[float], b: Sequence[float], n: int = 2000, seed: int = 0) -> float:
    """Two-sided p-value for 'configs A and B have the same mean', resampling questions jointly (paired). Small = real difference."""
    assert len(a) == len(b)
    if not a or all(x == y for x, y in zip(a, b)):
        return 1.0
    diffs = [x - y for x, y in zip(a, b)]
    obs = mean(diffs)
    rng = random.Random(seed)
    k = len(diffs)
    centred = [d - obs for d in diffs]        # null hypothesis: the true mean difference is 0
    extreme = sum(abs(mean([centred[rng.randrange(k)] for _ in range(k)])) >= abs(obs) for _ in range(n))
    return (extreme + 1) / (n + 1)
