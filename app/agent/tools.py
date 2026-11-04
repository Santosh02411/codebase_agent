from __future__ import annotations
from pathlib import Path

from .. import sandbox
from ..retrieval.index import CodeIndex
from ..utils import safe_path


def chunk_dict(c, score: float | None = None, via: str = "search", why: str = "") -> dict:
    d = {"id": c.id, "file": c.file, "kind": c.kind, "name": c.name, "qualname": c.qualname,
         "start": c.start, "end": c.end, "text": c.text, "via": via, "route": c.route}
    if score is not None:
        d["score"] = round(float(score), 3)
    if why:
        d["why"] = why
    return d


class RepoTools:
    """Tools the agent can call. Each is a plain method so they can also be exposed as LLM function-calls."""

    def __init__(self, root: Path, index: CodeIndex, test_timeout: int = 120, llm=None) -> None:
        self.root, self.index, self.test_timeout, self.llm = root, index, test_timeout, llm
        self.last_trace: dict = {}

    def search_code(self, query: str, k: int = 5, candidates: int = 20) -> list[dict]:
        """Hybrid search (vectors + BM25, fused with RRF) -> rerank -> top-k chunks. `candidates` = fused pool size."""
        r = self.index.retriever(llm=self.llm).retrieve(query, k=k, pool=max(candidates, k))
        self.last_trace = r.trace
        return [chunk_dict(h.chunk, h.score, why=h.why()) for h in r.hits]

    def related(self, chunk_id: int) -> list[dict]:
        c = self.index.chunks[chunk_id]
        return ([chunk_dict(x, via="callee") for x in self.index.callees(c)]
                + [chunk_dict(x, via="caller") for x in self.index.callers(c)])

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        lines = safe_path(self.root, path).read_text(encoding="utf-8").splitlines()
        s = (start or 1) - 1
        return "\n".join(lines[s : end or len(lines)])

    def find_symbol(self, name: str) -> list[dict]:
        return [chunk_dict(c, via="symbol") for c in self.index.by_name.get(name, [])]

    def list_tree(self, max_lines: int = 80) -> str:
        t = self.index.tree
        return "\n".join(t[:max_lines]) + (f"\n... (+{len(t) - max_lines} more files)" if len(t) > max_lines else "")

    def get_dependencies(self, path: str | None = None) -> dict:
        """Declared dependencies of the repo, or for one file: what it imports, who imports it, external packages."""
        if path is None:
            return self.index.deps
        g = self.index.graph
        f = self.index.facts.get(path)
        return {"imports": sorted({i.module for i in f.imports if i.module}) if f else self.index.imports.get(path, []),
                "internal_files": sorted(g.imports_of.get(path, ())), "imported_by": sorted(g.imported_by.get(path, ())),
                "external": sorted(g.external.get(path, ()))}

    def _symbols(self, name: str):
        g = self.index.graph
        return [g.symbols[name]] if name in g.symbols else g.find(name)

    def callers(self, name: str) -> list[dict]:
        """Who calls this function/method (resolved through imports and class hierarchy)."""
        out = []
        for s in self._symbols(name)[:3]:
            for c, conf in self.index.graph.callers(s.id):
                out.append({"symbol": s.qualname, "caller": c.qualname, "file": c.file, "start": c.start, "end": c.end, "confidence": conf})
        return out

    def callees(self, name: str) -> list[dict]:
        out = []
        for s in self._symbols(name)[:3]:
            for c, conf in self.index.graph.callees(s.id):
                out.append({"symbol": s.qualname, "callee": c.qualname, "file": c.file, "start": c.start, "end": c.end, "confidence": conf})
        return out

    def impact(self, path: str) -> dict:
        """Files that would be affected by changing `path` (reverse import graph) and the tests among them."""
        return self.index.graph.impact(path)

    def relations(self, chunk_id: int) -> str:
        """One-line summary of how a chunk connects to the rest of the code (for prompts)."""
        c = self.index.chunks[chunk_id]
        if not c.symbol_id:
            return ""
        g = self.index.graph
        s = g.symbols[c.symbol_id]
        parts = []
        if s.bases:
            parts.append("extends " + ", ".join(s.bases[:4]))
        callees = [x.qualname for x, _ in g.callees(s.id)][:6]
        callers = [x.qualname for x, _ in g.callers(s.id)][:6]
        if callees:
            parts.append("calls " + ", ".join(callees))
        if callers:
            parts.append("called by " + ", ".join(callers))
        if s.kind in ("class", "interface", "struct", "trait") and g.derived.get(s.id):
            parts.append("subclassed by " + ", ".join(g.symbols[i].qualname for i in g.derived[s.id][:4]))
        return f"{c.file}::{c.qualname}: " + "; ".join(parts) if parts else ""

    def run_tests(self) -> dict:
        work = sandbox.copy_repo(self.root)
        try:
            return sandbox.run_tests(work, self.test_timeout)
        finally:
            sandbox.cleanup(work)
