from __future__ import annotations


def rrf(rankings: dict[str, list[int]], k: int = 60, weights: dict[str, float] | None = None) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion (Cormack et al., 2009): score(d) = Σ_r w_r / (k + rank_r(d)), rank starting at 1.
    Rank-based, so BM25 scores and cosine similarities (different scales) can be combined without tuning.
    Ties break by the best rank achieved in any list, then by id, so the result is deterministic."""
    weights = weights or {}
    score: dict[int, float] = {}
    best: dict[int, int] = {}
    for name, ranking in rankings.items():
        w = weights.get(name, 1.0)
        for rank, doc in enumerate(ranking, 1):
            score[doc] = score.get(doc, 0.0) + w / (k + rank)
            best[doc] = min(best.get(doc, rank), rank)
    return sorted(score.items(), key=lambda x: (-x[1], best[x[0]], x[0]))


def max_score(n_lists: int, k: int = 60, weights: list[float] | None = None) -> float:
    """Best possible fused score (rank 1 in every list), used to scale fused scores into [0, 1]."""
    return sum(weights) / (k + 1) if weights else n_lists / (k + 1)
