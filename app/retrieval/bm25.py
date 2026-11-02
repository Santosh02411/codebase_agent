"""Okapi BM25 (Lucene-style idf). The same formula is evaluated inside PostgreSQL by app/rag/pg.py, so the in-memory and
production keyword searches rank identically."""
from __future__ import annotations
import math
from collections import Counter
from typing import Callable

import numpy as np

K1, B = 1.5, 0.75
MAX_QUERY_TERMS = 32


def bm25_idf(n: int, df: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def query_terms(tokens: list[str], idf_of: Callable[[str], float | None], max_terms: int = MAX_QUERY_TERMS) -> list[tuple[str, float]]:
    """Distinct query terms that exist in the corpus, strongest (highest idf) first, capped so long questions stay cheap."""
    scored = [(t, i) for t in dict.fromkeys(tokens) if (i := idf_of(t)) is not None]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:max_terms]


def top_n(scores: np.ndarray, n: int, positive_only: bool = False) -> list[int]:
    """Indices of the n best scores; ties break by lower index so results are deterministic everywhere."""
    if not len(scores):
        return []
    order = np.lexsort((np.arange(len(scores)), -scores))[:n]
    return [int(i) for i in order if not positive_only or scores[i] > 0]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = K1, b: float = B) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lens = np.array([len(d) for d in docs], dtype=np.float64)
        self.avg = float(self.lens.mean()) if self.n else 1.0
        post: dict[str, tuple[list[int], list[int]]] = {}
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                ids, fs = post.setdefault(t, ([], []))
                ids.append(i); fs.append(f)
        self.postings = {t: (np.array(ids, dtype=np.int64), np.array(fs, dtype=np.float64)) for t, (ids, fs) in post.items()}
        self.idf = {t: bm25_idf(self.n, len(ids)) for t, (ids, _) in self.postings.items()}

    def terms(self, query_tokens: list[str]) -> list[tuple[str, float]]:
        return query_terms(query_tokens, self.idf.get)

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float64)
        for t, idf in self.terms(query_tokens):
            ids, fs = self.postings[t]
            out[ids] += idf * fs * (self.k1 + 1) / (fs + self.k1 * (1 - self.b + self.b * self.lens[ids] / self.avg))
        return out
