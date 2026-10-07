from __future__ import annotations
import pickle
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import numpy as np

from ..parsing.chunker import Chunk
from ..utils import tokenize
from .bm25 import BM25
from .embeddings import get_embedder


class CodeIndex:
    """In-process hybrid index: BM25 (keyword) + dense vectors, fused with Reciprocal Rank Fusion.
    v1 persists to a pickle; Phase 7 moves vectors/chunks to PostgreSQL + pgvector."""

    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, tree: list[str], deps: dict,
                 imports: dict, embedder_name: str, embedder=None) -> None:
        self.chunks, self.emb, self.tree, self.deps, self.imports = chunks, embeddings, tree, deps, imports
        self.embedder_name = embedder_name
        self.embedder = embedder or get_embedder(embedder_name)
        self.tokens = [tokenize(f"{c.file} {c.qualname} {c.route} {c.text}") for c in chunks]
        self.token_sets = [set(t) for t in self.tokens]
        self.bm25 = BM25(self.tokens)
        self.by_name: dict[str, list[Chunk]] = defaultdict(list)
        for c in chunks:
            if c.kind in ("function", "method", "class"):
                self.by_name[c.name].append(c)

    @classmethod
    def build(cls, chunks, tree, deps, imports, embedder) -> "CodeIndex":
        for i, c in enumerate(chunks):
            c.id = i
        texts = [f"{c.file}\n{c.qualname}\n{c.route}\n{c.text}" for c in chunks]
        emb = embedder.embed(texts) if texts else np.zeros((0, 1), dtype=np.float32)
        return cls(chunks, emb, tree, deps, imports, embedder.name, embedder)

    def search(self, query: str, k: int = 20) -> list[tuple[Chunk, float]]:
        """Hybrid retrieval. Returns (chunk, fused score in [0,1])."""
        if not self.chunks:
            return []
        bm = self.bm25.scores(tokenize(query))
        vec = self.emb @ self.embedder.embed([query])[0]
        scores: dict[int, float] = {}
        for ranking in (
            [int(i) for i in np.argsort(-bm)[:50] if bm[i] > 0],
            [int(i) for i in np.argsort(-vec)[:50]],
        ):
            for r, i in enumerate(ranking):
                scores[i] = scores.get(i, 0.0) + 1.0 / (60 + r + 1)
        top = sorted(scores.items(), key=lambda x: -x[1])[:k]
        norm = 2.0 / 61.0
        return [(self.chunks[i], s / norm) for i, s in top]

    def callees(self, chunk: Chunk, limit: int = 3) -> list[Chunk]:
        out: list[Chunk] = []
        for name in chunk.calls:
            for c in self.by_name.get(name, []):
                if c.id != chunk.id and c not in out:
                    out.append(c)
        return out[:limit]

    def callers(self, chunk: Chunk, limit: int = 2) -> list[Chunk]:
        out = [c for c in self.chunks if chunk.name in c.calls and c.id != chunk.id]
        return out[:limit]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"chunks": [asdict(c) for c in self.chunks], "emb": self.emb, "tree": self.tree,
                         "deps": self.deps, "imports": self.imports, "embedder": self.embedder_name}, f)

    @classmethod
    def load(cls, path: Path) -> "CodeIndex":
        with open(path, "rb") as f:
            d = pickle.load(f)
        return cls([Chunk(**c) for c in d["chunks"]], d["emb"], d["tree"], d["deps"], d["imports"], d["embedder"])
