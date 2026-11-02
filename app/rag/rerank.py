"""Rerankers: re-order the fused candidate pool before anything is sent to the LLM.

    none                   keep the fused order
    heuristic              offline lexical + structural priors (default; no model download)
    bge-reranker-base      BAAI/bge-reranker-base cross-encoder (also: -large, -v2-m3)  [needs sentence-transformers]
    cross-encoder:<model>  any sentence-transformers CrossEncoder, e.g. cross-encoder/ms-marco-MiniLM-L-6-v2
    llm                    listwise scoring by the configured LLM
"""
from __future__ import annotations
import math
from typing import Protocol

from ..retrieval.reranker import prior_multiplier, rerank as heuristic_rerank
from ..utils import tokenize


class RerankError(RuntimeError):
    pass


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, hits: list, top_n: int) -> list: ...


def doc_text(chunk, max_chars: int = 1800) -> str:
    head = " · ".join(x for x in (chunk.file, chunk.qualname if chunk.kind != "module" else "", chunk.signature, chunk.route) if x)
    return f"{head}\n{chunk.doc}\n{chunk.text[:max_chars]}".strip()


class NoopReranker:
    name = "none"

    def rerank(self, query, hits, top_n):
        return hits[:top_n]


class HeuristicReranker:
    """Term coverage + symbol/path/route matches, with priors that favour real code over docs/tests/config."""

    name = "heuristic"

    def __init__(self, index) -> None:
        self.index = index

    def rerank(self, query, hits, top_n):
        scored = heuristic_rerank(self.index, query, [(h.chunk, h.rrf_norm) for h in hits], top_n=top_n)
        by_id = {h.chunk.id: h for h in hits}
        out = []
        for c, s in scored:
            h = by_id[c.id]
            h.rerank_score, h.score = float(s), float(s)
            out.append(h)
        return out


class CrossEncoderReranker:
    """Joint (query, code) scoring by a cross-encoder: far more accurate than bi-encoder similarity, but needs one model
    forward pass per candidate, so it only sees the fused top-N. `priors=True` also applies the code-vs-doc/test/config
    multipliers, because cross-encoders trained on prose tend to over-rank READMEs."""

    _loaded: dict[str, object] = {}

    def __init__(self, model: str = "BAAI/bge-reranker-base", priors: bool = True, batch_size: int = 16, max_length: int = 512,
                 device: str | None = None) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise RerankError("cross-encoder reranking needs `pip install sentence-transformers`") from e
        self.model_name, self.priors, self.batch_size = model, priors, batch_size
        key = f"{model}|{device}|{max_length}"
        if key not in self._loaded:
            self._loaded[key] = CrossEncoder(model, max_length=max_length, device=device)
        self.model = self._loaded[key]
        self.name = f"cross-encoder:{model}"

    def rerank(self, query, hits, top_n):
        if not hits:
            return []
        scores = self.model.predict([(query, doc_text(h.chunk)) for h in hits], batch_size=self.batch_size, show_progress_bar=False)
        qtoks = set(tokenize(query))
        for h, raw in zip(hits, scores):
            p = 1 / (1 + math.exp(-max(min(float(raw), 30), -30)))   # logits -> (0, 1)
            h.rerank_score = p
            h.score = p * (prior_multiplier(h.chunk, qtoks) if self.priors else 1.0)
        return sorted(hits, key=lambda h: (-h.score, h.chunk.id))[:top_n]


class LLMReranker:
    """Listwise reranking by the configured LLM: one call scores every candidate 0-10. Falls back to the fused order if the
    model's answer can't be parsed, so it can never make retrieval fail."""

    def __init__(self, llm, max_candidates: int = 20) -> None:
        self.llm, self.max_candidates, self.name = llm, max_candidates, "llm"

    def rerank(self, query, hits, top_n):
        pool = hits[: self.max_candidates]
        listing = "\n\n".join(f"[{i}] {doc_text(h.chunk, 700)}" for i, h in enumerate(pool))
        prompt = (f"Question: {query}\n\nCandidate code snippets:\n{listing}\n\n"
                  'Score how useful each snippet is for answering the question, 0 (irrelevant) to 10 (essential). '
                  'Return JSON: {"scores": {"0": 7, "1": 0, ...}}')
        scores: dict[int, float] = {}
        try:
            raw = self.llm.json("rerank", "You rank code search results.", prompt, hints={}).get("scores", {})
            for k, v in raw.items():          # tolerate individual malformed entries instead of discarding the whole answer
                try:
                    i, val = int(k), float(v)
                except (TypeError, ValueError):
                    continue
                if 0 <= i < len(pool):
                    scores[i] = max(0.0, min(10.0, val))
        except Exception:  # noqa: BLE001 - provider error / non-dict reply
            scores = {}
        if not scores:
            return hits[:top_n]
        for i, h in enumerate(pool):
            h.rerank_score = scores.get(i, 0.0) / 10.0
            h.score = h.rerank_score
        return sorted(pool, key=lambda h: (-h.score, h.rank_pool))[:top_n]


_ALIASES = {"bge-reranker-base": "BAAI/bge-reranker-base", "bge-reranker-large": "BAAI/bge-reranker-large",
            "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3", "ms-marco-minilm": "cross-encoder/ms-marco-MiniLM-L-6-v2"}


def get_reranker(spec: str | None, index=None, llm=None):
    spec = (spec or "heuristic").strip()
    low = spec.lower()
    if low in ("none", "off", ""):
        return NoopReranker()
    if low == "heuristic":
        if index is None:
            raise RerankError("the heuristic reranker needs an index")
        return HeuristicReranker(index)
    if low == "llm":
        if llm is None:
            raise RerankError("the llm reranker needs an LLM")
        return LLMReranker(llm)
    if low.startswith("cross-encoder:"):
        return CrossEncoderReranker(spec.split(":", 1)[1])
    if low in _ALIASES:
        return CrossEncoderReranker(_ALIASES[low])
    if "/" in spec:
        return CrossEncoderReranker(spec)
    raise RerankError(f"unknown reranker: {spec!r}")
