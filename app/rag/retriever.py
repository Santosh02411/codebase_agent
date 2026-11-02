"""Hybrid retrieval pipeline:  query -> [vector search ‖ BM25 keyword search] -> Reciprocal Rank Fusion -> rerank -> top-k.

The two search legs come from a `SearchBackend`: in memory (numpy + inverted index) or PostgreSQL (pgvector + SQL BM25).
Every returned `Hit` records how it was found (rank in each leg, fused score, rerank score) so results are explainable."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..parsing.chunker import Chunk
from ..utils import tokenize
from .embedders import EmbeddingError
from .fusion import max_score, rrf
from ..retrieval.bm25 import top_n


@dataclass
class RetrievalConfig:
    mode: str = "hybrid"          # hybrid | vector | keyword
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    candidates: int = 50          # taken from each search leg
    pool: int = 30                # fused candidates handed to the reranker


@dataclass
class Hit:
    chunk: Chunk
    score: float = 0.0            # final: rerank score if reranked, else RRF scaled to [0, 1]
    rrf: float = 0.0
    rrf_norm: float = 0.0
    vector_rank: int | None = None
    vector_score: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    rank_pool: int = 0

    def why(self) -> str:
        parts = []
        if self.vector_rank:
            parts.append(f"vector #{self.vector_rank}")
        if self.keyword_rank:
            parts.append(f"keyword #{self.keyword_rank}")
        if self.rerank_score is not None:
            parts.append(f"rerank {self.rerank_score:.2f}")
        return ", ".join(parts)


@dataclass
class Retrieval:
    hits: list[Hit]
    trace: dict = field(default_factory=dict)


class SearchBackend(Protocol):
    def vector(self, qvec: np.ndarray, n: int) -> list[tuple[int, float]]:
        """Top-n (chunk position, cosine similarity), best first."""

    def keyword(self, query: str, n: int) -> list[tuple[int, float]]:
        """Top-n (chunk position, BM25 score) with score > 0, best first."""


class MemoryBackend:
    """numpy matrix + in-process BM25 (used when no database is configured, and by the offline experiments)."""

    def __init__(self, index) -> None:
        self.index = index

    def vector(self, qvec, n):
        if self.index.emb is None or not len(self.index.chunks):
            return []
        sims = self.index.emb @ qvec
        return [(i, float(sims[i])) for i in top_n(sims, n)]

    def keyword(self, query, n):
        scores = self.index.bm25.scores(tokenize(query))
        return [(i, float(scores[i])) for i in top_n(scores, n, positive_only=True)]


class Retriever:
    def __init__(self, index, embedder, backend: SearchBackend, reranker=None, config: RetrievalConfig | None = None) -> None:
        self.index, self.embedder, self.backend = index, embedder, backend
        self.reranker, self.cfg = reranker, config or RetrievalConfig()

    def retrieve(self, query: str, k: int = 5, *, mode: str | None = None, rerank: bool = True, pool: int | None = None,
                 candidates: int | None = None) -> Retrieval:
        cfg, mode = self.cfg, (mode or self.cfg.mode)
        n_cand = candidates or cfg.candidates
        trace: dict = {"mode": mode, "query": query, "warnings": []}
        if not self.index.chunks or not query.strip():
            return Retrieval([], trace)

        t0 = time.perf_counter()
        vec: list[tuple[int, float]] = []
        if mode in ("hybrid", "vector"):
            try:
                qvec = self.embedder.embed_query(query)
                trace["embed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                t1 = time.perf_counter()
                vec = self.backend.vector(qvec, n_cand)
                trace["vector_ms"] = round((time.perf_counter() - t1) * 1000, 1)
            except EmbeddingError as e:  # embedding service down: keep answering from keyword search
                trace["warnings"].append(f"vector search skipped: {e}")
                if mode == "vector":
                    raise
        kw: list[tuple[int, float]] = []
        if mode in ("hybrid", "keyword") or (mode == "vector" and not vec):
            t1 = time.perf_counter()
            kw = self.backend.keyword(query, n_cand)
            trace["keyword_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        trace["vector_candidates"], trace["keyword_candidates"] = len(vec), len(kw)

        rankings, weights = {}, {}
        if vec:
            rankings["vector"], weights["vector"] = [i for i, _ in vec], cfg.vector_weight
        if kw:
            rankings["keyword"], weights["keyword"] = [i for i, _ in kw], cfg.keyword_weight
        fused = rrf(rankings, cfg.rrf_k, weights)
        scale = max_score(len(rankings), cfg.rrf_k, list(weights.values())) if rankings else 1.0
        vrank = {i: (r, s) for r, (i, s) in enumerate(vec, 1)}
        krank = {i: (r, s) for r, (i, s) in enumerate(kw, 1)}
        want = max(pool or cfg.pool, k)
        hits = []
        for p, (i, s) in enumerate(fused[:want]):
            h = Hit(self.index.chunks[i], score=s / scale, rrf=s, rrf_norm=s / scale, rank_pool=p)
            if i in vrank:
                h.vector_rank, h.vector_score = vrank[i]
            if i in krank:
                h.keyword_rank, h.keyword_score = krank[i]
            hits.append(h)
        trace["fused"] = len(fused)
        if rerank and self.reranker is not None and hits:
            t2 = time.perf_counter()
            hits = self.reranker.rerank(query, hits, k)
            trace["rerank_ms"] = round((time.perf_counter() - t2) * 1000, 1)
            trace["reranker"] = self.reranker.name
        else:
            hits = hits[:k]
        trace["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return Retrieval(hits, trace)
