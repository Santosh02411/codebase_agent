from __future__ import annotations
import pickle
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import numpy as np

from ..intel.graph import CodeGraph
from ..intel.model import FileFacts
from ..parsing.chunker import Chunk
from ..utils import tokenize
from .bm25 import BM25
from .embeddings import get_embedder


class StaleIndex(Exception):
    """Saved index was written by an older version; it must be rebuilt."""


INDEX_FORMAT = 2
_CONF_RANK = {"local": 0, "self": 0, "import": 0, "class": 1, "unique": 2, "ambiguous": 3}


class CodeIndex:
    """In-process hybrid index: BM25 (keyword) + dense vectors, fused with Reciprocal Rank Fusion.
    v1 persists to a pickle; Phase 7 moves vectors/chunks to PostgreSQL + pgvector."""

    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, tree: list[str], deps: dict,
                 imports: dict, embedder_name: str, embedder=None, facts: dict[str, FileFacts] | None = None,
                 graph: CodeGraph | None = None, context: dict | None = None) -> None:
        self.chunks, self.emb, self.tree, self.deps, self.imports = chunks, embeddings, tree, deps, imports
        self.facts = facts or {}
        self.context = context or {}
        self.graph = graph or CodeGraph(self.facts, self.context)
        self.report: dict = {}
        self.chunk_by_symbol = {c.symbol_id: c for c in chunks if c.symbol_id}
        self.embedder_name = embedder_name
        self.embedder = embedder or get_embedder(embedder_name)
        self.tokens = [tokenize(f"{c.file} {c.qualname} {c.route} {c.text}") for c in chunks]
        self.token_sets = [set(t) for t in self.tokens]
        self.bm25 = BM25(self.tokens)
        self.by_name: dict[str, list[Chunk]] = defaultdict(list)
        for c in chunks:
            if c.kind in ("function", "method", "class"):
                self.by_name[c.name].append(c)

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

    def _via_graph(self, chunk: Chunk, edges, limit: int) -> list[Chunk]:
        out: list[Chunk] = []
        for sym, conf in sorted(edges, key=lambda e: _CONF_RANK.get(e[1], 3)):
            c = self.chunk_by_symbol.get(sym.id)
            if c is not None and c.id != chunk.id and c not in out:
                out.append(c)
        return out[:limit]

    def callees(self, chunk: Chunk, limit: int = 3) -> list[Chunk]:
        if chunk.symbol_id:
            return self._via_graph(chunk, self.graph.callees(chunk.symbol_id), limit)
        out: list[Chunk] = []
        for name in chunk.calls:
            for c in self.by_name.get(name, []):
                if c.id != chunk.id and c not in out:
                    out.append(c)
        return out[:limit]

    def callers(self, chunk: Chunk, limit: int = 2) -> list[Chunk]:
        if chunk.symbol_id:
            return self._via_graph(chunk, self.graph.callers(chunk.symbol_id), limit)
        return [c for c in self.chunks if chunk.name in c.calls and c.id != chunk.id][:limit]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"format": INDEX_FORMAT, "chunks": [asdict(c) for c in self.chunks], "emb": self.emb, "tree": self.tree,
                         "deps": self.deps, "imports": self.imports, "embedder": self.embedder_name,
                         "facts": {p: ff.to_dict() for p, ff in self.facts.items()}, "context": self.context, "report": self.report}, f)

    @classmethod
    def load(cls, path: Path) -> "CodeIndex":
        with open(path, "rb") as f:
            d = pickle.load(f)
        if d.get("format") != INDEX_FORMAT:
            raise StaleIndex(str(path))
        facts = {p: FileFacts.from_dict(x) for p, x in d["facts"].items()}
        idx = cls([Chunk(**c) for c in d["chunks"]], d["emb"], d["tree"], d["deps"], d["imports"], d["embedder"],
                  facts=facts, context=d.get("context", {}))
        idx.report = d.get("report", {})
        return idx
